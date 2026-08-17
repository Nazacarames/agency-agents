"""dmarc_reports — lee los informes agregados DMARC y dice quién manda mail como nosotros.

Por qué existe: `_dmarc.automiq.agency` publica `rua=mailto:dmarc@automiq.agency`,
así que todos los días llega un XML comprimido de cada proveedor que recibió mail
diciendo ser de automiq.agency. Nadie los abre (son XML dentro de un .gz), así que
la única visibilidad que tenemos sobre suplantación del dominio se estaba tirando
a la basura mail por mail.

Qué mira: `policy_evaluated`. Un mensaje falla DMARC cuando NO alinea ni por DKIM
ni por SPF — o sea, el `From:` dice automiq.agency pero la firma/el envelope son de
otro dominio. Eso es lo único accionable: con `p=reject` esos mensajes se caen.
Los que alinean por DKIM pero no por SPF son reenvíos normales y no se reportan.

Sólo lectura del buzón. No borra ni marca nada.
"""
from __future__ import annotations

import base64
import gzip
import io
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple
from xml.etree import ElementTree as ET

from ..config import Settings
from ..log import get_logger

log = get_logger("dmarc")

RUA_BUZON = "dmarc@automiq.agency"


def _service(settings: Settings):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from .gmail_client import GMAIL_SCOPES, TOKEN_URI

    creds = Credentials(
        token=None, refresh_token=settings.gmail_refresh_token,
        client_id=settings.gmail_client_id, client_secret=settings.gmail_client_secret,
        token_uri=TOKEN_URI, scopes=GMAIL_SCOPES,
    )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _adjuntos(svc, user_id: str, msg: Dict[str, Any]) -> List[Tuple[str, bytes]]:
    """Todos los adjuntos del mensaje, recorriendo el árbol MIME completo."""
    out, pila = [], [msg.get("payload", {})]
    while pila:
        parte = pila.pop()
        pila.extend(parte.get("parts") or [])
        att_id = (parte.get("body") or {}).get("attachmentId")
        if not att_id:
            continue
        data = svc.users().messages().attachments().get(
            userId=user_id, messageId=msg["id"], id=att_id).execute()
        out.append((parte.get("filename", ""), base64.urlsafe_b64decode(data["data"])))
    return out


def _desempaquetar(nombre: str, crudo: bytes) -> List[bytes]:
    """Los informes vienen .xml.gz (Google) o .zip (Microsoft/Yahoo)."""
    n = nombre.lower()
    if n.endswith(".gz"):
        return [gzip.decompress(crudo)]
    if n.endswith(".zip"):
        z = zipfile.ZipFile(io.BytesIO(crudo))
        return [z.read(x) for x in z.namelist()]
    if n.endswith(".xml"):
        return [crudo]
    return []


def _auth(rec: ET.Element, tag: str) -> str:
    """Quién firmó / de quién es el envelope, según auth_results."""
    ar = rec.find("auth_results")
    if ar is None:
        return ""
    return ",".join(sorted({(e.findtext("domain") or "?") for e in ar.findall(tag)}))


def _dominios_conocidos() -> set:
    """Dominios a los que NOSOTROS les mandamos mail (leads + clientes).

    Existe por un falso positivo real: el 2026-08-06 mandamos un mail a
    info@tmlogistica.com.ar y su servidor lo repartió a 8 buzones internos,
    re-firmando cada copia con SU dominio y dejando nuestro `From:`. DMARC lo
    reporta como 8 mensajes no alineados. Es nuestro propio mail reenviado, y
    pasa con cualquier prospecto que tenga una lista de distribución detrás:
    sin este filtro el watchdog gritaría "suplantación" cada vez que el motor
    de outbound hace su trabajo, y la alerta dejaría de significar algo.
    """
    doms = set()
    try:
        from . import leads_store
        for lead in (leads_store.load_store().get("leads") or {}).values():
            correo = (lead.get("email") or "").lower()
            if "@" in correo:
                doms.add(correo.rsplit("@", 1)[1])
    except Exception as e:
        log.warning("dmarc_dominios_leads_failed", error=str(e)[:120])
    try:
        from . import clients_store
        for c in clients_store.list_clients():
            for campo in ("email", "contact_email", "website"):
                v = (c.get(campo) or "").lower().strip()
                if "@" in v:
                    doms.add(v.rsplit("@", 1)[1])
                elif v:
                    doms.add(v.replace("https://", "").replace("http://", "").split("/")[0])
    except Exception as e:
        log.warning("dmarc_dominios_clientes_failed", error=str(e)[:120])
    return {d for d in doms if d and "." in d}


def resumen(settings: Settings, dias: int = 7, max_mensajes: int = 40) -> Dict[str, Any]:
    """Agrega los informes de los últimos `dias`. Best-effort: nunca levanta.

    Devuelve `fallas` con una fila por (IP, dominio que firmó) — sin agrupar el
    volumen se pierde de vista si son 3 mensajes sueltos o una campaña entera.
    """
    salida: Dict[str, Any] = {
        "ok": False, "informes": 0, "mensajes": 0, "fallan": 0, "reenviados": 0,
        "fallas": [], "reporteros": [], "desde": "", "hasta": "", "error": "",
    }
    if not settings.gmail_configured:
        salida["error"] = "Gmail sin credenciales"
        return salida
    try:
        svc = _service(settings)
        user_id = settings.gmail_user_id or "me"
        # `in:anywhere` NO es opcional: los informes llegan al grupo DMARC ("via
        # DMARC" en el From) y Gmail los deja fuera del alcance de una búsqueda
        # normal. Sin esto la consulta devolvía 0 informes en 30 días mientras en
        # el buzón había 15 — o sea, el watchdog miraba una casilla vacía y no lo
        # decía. Medido el 2026-08-17: misma query con `in:anywhere` → 15.
        query = f"to:{RUA_BUZON} has:attachment in:anywhere newer_than:{int(dias)}d"
        ids = svc.users().messages().list(
            userId=user_id, q=query, maxResults=int(max_mensajes)
        ).execute().get("messages", []) or []

        # (ip, dominio_dkim, dominio_spf) → mensajes. El header_from siempre es el
        # nuestro (es un informe de NUESTRO dominio), así que no aporta a la clave.
        fallas: Dict[Tuple[str, str, str], int] = defaultdict(int)
        reporteros: set = set()
        ventanas: List[int] = []
        total = 0

        for meta in ids:
            full = svc.users().messages().get(
                userId=user_id, id=meta["id"], format="full").execute()
            for nombre, crudo in _adjuntos(svc, user_id, full):
                for xml in _desempaquetar(nombre, crudo):
                    try:
                        root = ET.fromstring(xml)
                    except ET.ParseError:
                        continue
                    salida["informes"] += 1
                    md = root.find("report_metadata")
                    if md is not None:
                        reporteros.add(md.findtext("org_name") or "?")
                        rango = md.find("date_range")
                        if rango is not None:
                            ventanas += [int(rango.findtext("begin") or 0),
                                         int(rango.findtext("end") or 0)]
                    for rec in root.findall("record"):
                        n = int(rec.findtext("row/count") or 0)
                        total += n
                        pe = rec.find("row/policy_evaluated")
                        if pe is None:
                            continue
                        dkim_ok = (pe.findtext("dkim") or "").lower() == "pass"
                        spf_ok = (pe.findtext("spf") or "").lower() == "pass"
                        if dkim_ok or spf_ok:
                            continue        # alinea por al menos uno → DMARC pasa
                        clave = (rec.findtext("row/source_ip") or "?",
                                 _auth(rec, "dkim") or "(sin firma)",
                                 _auth(rec, "spf") or "(sin spf)")
                        fallas[clave] += n

        ventanas = [v for v in ventanas if v > 0]
        conocidos = _dominios_conocidos()
        detalle = []
        for (ip, dk, spf), n in sorted(fallas.items(), key=lambda kv: -kv[1]):
            # Basta con que el dominio que firmó sea alguien a quien le escribimos:
            # es nuestro propio mail reenviado por su servidor, no suplantación.
            nuestro = any(d == dk or dk.endswith("." + d) for d in conocidos)
            detalle.append({"ip": ip, "dkim": dk, "spf": spf, "mensajes": n,
                            "reenvio_de_lead": nuestro})
        salida.update({
            "ok": True,
            "mensajes": total,
            "fallan": sum(f["mensajes"] for f in detalle if not f["reenvio_de_lead"]),
            "reenviados": sum(f["mensajes"] for f in detalle if f["reenvio_de_lead"]),
            "reporteros": sorted(reporteros),
            "desde": datetime.fromtimestamp(min(ventanas), timezone.utc).date().isoformat() if ventanas else "",
            "hasta": datetime.fromtimestamp(max(ventanas), timezone.utc).date().isoformat() if ventanas else "",
            "fallas": detalle,
        })
        log.info("dmarc_resumen", informes=salida["informes"], mensajes=total,
                 fallan=salida["fallan"], reenviados=salida["reenviados"])
    except Exception as e:
        salida["error"] = str(e)[:200]
        log.warning("dmarc_resumen_failed", error=salida["error"])
    return salida
