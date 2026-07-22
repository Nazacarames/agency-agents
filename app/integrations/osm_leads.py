"""
osm_leads — descubrimiento de PyMEs argentinas desde OpenStreetMap (Overpass API).

POR QUÉ ESTO EXISTE
-------------------
El descubrimiento venía dependiendo de que el MODELO decidiera buscar. Medido el
2026-07-21: seis corridas seguidas de leadhunter con el buscador funcionando y
CERO búsquedas — el agente prefería adivinar dominios con curl. Reproducir el run
exacto en una sonda daba 33 búsquedas, así que no había nada roto: simplemente el
descubrimiento no era determinístico.

Acá el descubrimiento pasa a ser CÓDIGO: buscamos nosotros, en Python, y le
pasamos al agente empresas reales ya encontradas. El modelo hace lo que hace bien
(calificar, detectar dolor, escribir el outreach) y no decide si busca o no.

POR QUÉ OSM Y NO OTRA COSA
--------------------------
Restricción vigente: no gastar más que hosting + Workspace.
- Overpass API: sin API key, sin signup, sin cuota comercial, datos abiertos
  (ODbL). No se cae si se agota un free tier porque no hay free tier.
- Google Maps scraping: zona gris de ToS y bloqueo desde IP de datacenter.
- Apify / Serper / Tavily: cuestan o se agotan (ya nos pasó con Tavily: 1000/1000).

Serper sigue en la cascada de `web_search` para el ENRIQUECIMIENTO (buscar el
decisor, noticias, señales). OSM es la fuente de DESCUBRIMIENTO, que es la que
tiene que ser gratis y no agotarse.

Medido el 2026-07-21: 80 empresas con web, 48 con teléfono, en una sola consulta
(Metalúrgica Alem SRL, Distribuidora Racer, Baterías Marozzi) — justo el perfil
PyME regional desconocida que buscamos.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from ..log import get_logger

log = get_logger("osm_leads")

_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
# Overpass pide identificarse. Sin User-Agent propio devuelve 406.
_UA = {"User-Agent": "AutomiqLeadResearch/1.0 (+https://automiq.agency; hola@automiq.agency)"}

_CACHE = Path(__file__).resolve().parent.parent.parent / "data" / "osm-leads-cache.json"
# 7 días: OSM no cambia rápido y así no golpeamos Overpass en cada corrida
# (es infraestructura donada por voluntarios — abusarla nos gana un bloqueo).
_TTL_DIAS = 7

# Segundos entre consultas a Overpass. No es una optimización: es no abusar de
# un servicio gratuito sostenido por voluntarios (nos empezó a devolver 429).
_PAUSA = 4.0

# Perfiles por vertical. El regex va sobre el NOMBRE porque es como se identifican
# las PyMEs argentinas del rubro; los tags de OSM solos traen poquísimo
# (`shop=wholesale` en AR está casi vacío).
PERFILES: Dict[str, List[str]] = {
    # Varios regex chicos por vertical en vez de uno grande: uno largo hace que
    # Overpass devuelva 504 (medido). Cada entrada es una consulta aparte.
    "distribucion": [r"[Dd]istribuidora|[Dd]istribuciones", r"[Mm]ayorista"],
    # Manufactura tiene MÁS slices a propósito: es el vertical que mejor convierte
    # (3% vs 1% de distribución, dato real del pipeline) y el que menos trae por
    # nombre — las fábricas se llaman por su apellido, no "Fábrica de X".
    "manufactura": [r"[Pp]l[áa]sticos|[Ee]nvases", r"[Mm]etal[úu]rgica|[Aa]utopartes",
                    r"[Ii]ndustrias", r"[Ff]undici[óo]n|[Mm]atricer[íi]a",
                    r"[Ff]rigor[íi]fico|[Aa]limenticia", r"[Tt]extil|[Cc]urtiembre",
                    r"[Mm]aderera|[Aa]serradero", r"[Qq]u[íi]mica|[Pp]inturas",
                    r"[Cc]art[óo]n|[Pp]apelera", r"[Mm]aquinaria|[Aa]groindustria"],
    "logistica": [r"[Tt]ransporte", r"[Ll]og[íi]stica|[Ee]xpreso"],
}

# Marcas grandes: el filtro de tamaño del system prompt, aplicado ANTES de gastar
# turnos del modelo. La lista sale de las que el propio prompt prohíbe.
_GRANDES = re.compile(
    r"\b(coto|carrefour|dia|walmart|jumbo|vea|disco|arcor|molinos|ledesma|techint|"
    r"ypf|aluar|quilmes|cervecer[íi]a y malter[íi]a|andreani|oca|correo argentino|"
    r"mercado ?libre|newsan|bag[óo]|sancor|serenisima|mastellone|paladini|"
    r"la an[óo]nima|fate|pirelli|bridgestone|shell|axion|petrobras|remax|re\/max|"
    # sumadas tras ver el primer pool real (2026-07-21): mayoristas grandes que
    # el regex de nombre traía igual porque se llaman "Mayorista ..."
    r"yaguar|jaguar|maxiconsumo|vital|diarco|makro|nini|parodi|"
    # sumadas tras ampliar manufactura: multinacionales y grandes industriales
    # que el regex de nombre traía igual ("Fábrica Holcim")
    r"holcim|vacal[íi]n|loma negra|cementos|petroqu[íi]mica|siderar|acindar|"
    r"antares|bimbo|fargo|dan[óo]ne|nestl[ée]|unilever|procter|impsa|pescarmona)\b",
    re.I)

# NO son empresas: reparticiones públicas, escuelas, cámaras. El regex de nombre
# las trae ("Dirección de Tránsito y Transporte") y le hacen perder turnos al
# agente descartándolas una por una.
_NO_EMPRESA = re.compile(
    r"^\s*(direcci[óo]n|municipalidad|secretar[íi]a|ministerio|subsecretar[íi]a|"
    r"delegaci[óo]n|comuna|instituto|escuela|universidad|facultad|hospital|"
    r"terminal|estaci[óo]n|c[áa]mara|sindicato|cooperativa de trabajo|"
    # gremios y obras sociales: aparecen con "industrias" en el nombre
    # ("Federación Trabajadores de Industrias...") y no son empresas
    r"federaci[óo]n|obra social|asociaci[óo]n|mutual|fundaci[óo]n|colegio)\b", re.I)

# Dominios que descalifican: estado/educación, y redes sociales como "sitio".
# Si el único "sitio" es un Facebook no podemos verificar contacto ni investigar.
# Ruido que el regex de nombre arrastra: en español "fábrica" nombra teatros
# ("La Fábrica" Sala de Teatro), centros culturales, bares y pizzerías. Nada de
# eso es una PyME industrial y le hace perder turnos al agente descartándolas.
_RUIDO = re.compile(
    r"(teatro|cultural|museo|club|bar|resto|restaurant|pizza|helader[íi]a|"
    r"panader[íi]a|caf[ée]|hotel|gimnasio|peluquer[íi]a|kiosco|farmacia|"
    r"sala de|centro de|espacio)", re.I)

_DOMINIOS_MALOS = (".gob.ar", ".gov.ar", ".edu.ar", ".mil.ar", "facebook.", "instagram.",
                   "twitter.", "x.com", "linkedin.", "wa.me", "wixsite.com", "blogspot.",
                   "sites.google.com", "pedidosya.", "rappi.", "tripadvisor.",
                   # .org.ar es casi siempre gremio, cámara u ONG en AR
                   ".org.ar", ".org/")


def _consultar(query: str, timeout: float = 180.0) -> List[Dict[str, Any]]:
    """Corre una consulta Overpass probando los mirrors. Nunca lanza.

    CORTESÍA OBLIGATORIA: Overpass lo sostienen voluntarios y no nos cobra nada.
    Al ampliar los perfiles pasamos a ~15 consultas seguidas y empezamos a comer
    429 (throttling) y 504. Pausa fija entre consultas + backoff ante 429. El
    refresco completo tarda unos minutos, pero corre UNA vez por semana (cache
    de 7 días): la lentitud acá no le cuesta nada a nadie.
    """
    import time
    for intento, host in enumerate(_ENDPOINTS):
        try:
            r = httpx.post(host, data={"data": query}, headers=_UA, timeout=timeout)
            if r.status_code == 200:
                time.sleep(_PAUSA)          # respirar antes de la próxima
                return r.json().get("elements", []) or []
            log.warning("osm_http", host=host, status=r.status_code)
            # 429 = nos están frenando: esperar de verdad, no saltar al otro mirror
            # y seguir golpeando.
            time.sleep(_PAUSA * (4 if r.status_code == 429 else 1))
        except Exception as e:
            log.warning("osm_error", host=host, error=str(e)[:150])
            time.sleep(_PAUSA)
    return []


def _query(regex: str, limite: int) -> str:
    """Consulta deliberadamente barata.

    Overpass es infraestructura donada por voluntarios y devuelve 504 si la
    consulta es cara. Tres decisiones para que entre:
    - sólo `node` y `way` (las `relation` son las más caras y acá no aportan);
    - un solo filtro de tag (`website`), no dos con OR;
    - regex chico: los perfiles largos se parten en varias consultas.
    Sin sitio web además no sirve: no podríamos verificar el contacto.
    """
    return f"""[out:json][timeout:90];
area["name"="Argentina"]["admin_level"="2"]->.a;
(
  node(area.a)["name"~"{regex}",i]["website"];
  way(area.a)["name"~"{regex}",i]["website"];
);
out center {limite};"""


def _query_industrial(limite: int) -> str:
    """Plantas industriales por TAG, no por nombre.

    La mayoría de las fábricas argentinas no se llaman "Fábrica de X": se llaman
    por el apellido del dueño (Zaplast, Arenera Nóbile, Metalúrgica Finke). El
    regex de nombre las pierde; el tag de uso de suelo las encuentra igual.
    """
    return f"""[out:json][timeout:90];
area["name"="Argentina"]["admin_level"="2"]->.a;
(
  way(area.a)["landuse"="industrial"]["name"]["website"];
  way(area.a)["man_made"="works"]["name"]["website"];
  node(area.a)["man_made"="works"]["name"]["website"];
);
out center {limite};"""


def _normalizar(el: Dict[str, Any], vertical: str) -> Optional[Dict[str, Any]]:
    t = el.get("tags", {}) or {}
    nombre = (t.get("name") or "").strip()
    web = (t.get("website") or t.get("contact:website") or "").strip()
    if not nombre or not web:
        return None
    if _GRANDES.search(nombre) or _NO_EMPRESA.match(nombre) or _RUIDO.search(nombre):
        return None
    # "supermayorista el turco" en el campo website: hay tags mal cargados en OSM.
    if not re.match(r"^https?://", web):
        if "." not in web or " " in web:
            return None
        web = "https://" + web
    dominio = web.lower()
    # El RUIDO también se busca en el dominio: el Teatro Colón figura como
    # "Colón Fábrica" (el nombre no lo delata, teatrocolon.org.ar sí).
    if any(d in dominio for d in _DOMINIOS_MALOS) or _RUIDO.search(dominio):
        return None
    tel = (t.get("phone") or t.get("contact:phone") or "").split(";")[0].strip()
    return {
        "empresa": nombre,
        "web": web,
        "telefono": tel or "",
        "email": (t.get("email") or t.get("contact:email") or "").strip(),
        "ciudad": (t.get("addr:city") or t.get("addr:town") or "").strip(),
        "provincia": (t.get("addr:province") or t.get("addr:state") or "").strip(),
        "vertical": vertical,
        "fuente": "OpenStreetMap",
    }


def _huella() -> str:
    """Huella de la CONFIGURACIÓN de búsqueda (perfiles + filtros).

    El TTL solo mide tiempo, y eso escondió una mejora: al ampliar los perfiles
    de manufactura, prod siguió sirviendo el pool viejo del cache y el cambio no
    iba a tomar efecto hasta 7 días después. Guardando la huella, cualquier
    cambio de perfiles o filtros invalida el cache y se rearma solo.
    """
    import hashlib
    crudo = json.dumps(PERFILES, sort_keys=True) + _GRANDES.pattern + \
        _NO_EMPRESA.pattern + _RUIDO.pattern + "".join(_DOMINIOS_MALOS)
    return hashlib.sha256(crudo.encode()).hexdigest()[:16]


def _leer_cache() -> Optional[List[Dict[str, Any]]]:
    try:
        if not _CACHE.is_file():
            return None
        data = json.loads(_CACHE.read_text(encoding="utf-8"))
        if data.get("huella") != _huella():
            log.info("osm_cache_invalidado", motivo="cambió la config de búsqueda")
            return None
        cuando = datetime.fromisoformat(data["actualizado"])
        if datetime.now(timezone.utc) - cuando > timedelta(days=_TTL_DIAS):
            return None
        return data.get("empresas") or None
    except Exception:
        return None


def _guardar_cache(empresas: List[Dict[str, Any]]) -> None:
    try:
        _CACHE.parent.mkdir(exist_ok=True)
        _CACHE.write_text(json.dumps(
            {"actualizado": datetime.now(timezone.utc).isoformat(),
             "huella": _huella(), "empresas": empresas},
            ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:
        log.warning("osm_cache_write_failed", error=str(e)[:150])


def refrescar(limite_por_perfil: int = 250, objetivo: int = 160) -> List[Dict[str, Any]]:
    """Consulta Overpass por cada vertical y devuelve el pool.

    Corta al llegar a `objetivo`: son ~15 consultas y este refresco puede caer en
    medio de una corrida de leadhunter. Con 160 empresas ya hay pool para semanas
    (se entregan 25 por día, rotando) y no tiene sentido hacer esperar al agente
    ni seguir golpeando Overpass.
    """
    pool: List[Dict[str, Any]] = []
    vistos: set = set()
    for vertical, regexes in PERFILES.items():
        for regex in regexes:
            if len(pool) >= objetivo:
                break
            for el in _consultar(_query(regex, limite_por_perfil), timeout=70.0):
                emp = _normalizar(el, vertical)
                if not emp:
                    continue
                # Dedupe por DOMINIO: la misma empresa aparece como node y como
                # way (el punto y el edificio), y a veces con sucursales.
                clave = re.sub(r"^www\.", "",
                               emp["web"].split("//")[-1].split("/")[0].lower())
                if clave in vistos:
                    continue
                vistos.add(clave)
                pool.append(emp)
    # Pasada extra por tags industriales (ver _query_industrial).
    for el in _consultar(_query_industrial(limite_por_perfil), timeout=70.0):
        emp = _normalizar(el, "manufactura")
        if not emp:
            continue
        clave = re.sub(r"^www\.", "", emp["web"].split("//")[-1].split("/")[0].lower())
        if clave in vistos:
            continue
        vistos.add(clave)
        pool.append(emp)

    log.info("osm_pool", empresas=len(pool),
             manufactura=sum(1 for e in pool if e["vertical"] == "manufactura"),
             con_telefono=sum(1 for e in pool if e["telefono"]))
    if pool:
        _guardar_cache(pool)
    return pool


def candidatos_por_cupo(cupo: Dict[str, int],
                        excluir: Optional[set] = None) -> List[Dict[str, Any]]:
    """Candidatas respetando un cupo por vertical: {"manufactura": 6, ...}.

    Existe para que la priorización por tasa de respuesta sea REAL. Decirle al
    modelo "priorizá manufactura" es una sugerencia que puede ignorar (medido
    todo el 2026-07-21); entregarle 6 empresas de manufactura y 3 de
    distribución es un hecho.
    """
    salida: List[Dict[str, Any]] = []
    for vertical, n in cupo.items():
        if n <= 0:
            continue
        salida.extend(candidatos(n, excluir, vertical=vertical))
    return salida


def candidatos(cantidad: int = 25, excluir: Optional[set] = None,
               vertical: Optional[str] = None) -> List[Dict[str, Any]]:
    """Empresas listas para prospectar, sin las que ya están en el pipeline.

    Rota por día para que dos corridas seguidas no traigan las mismas: sin esto
    el agente recibiría siempre las primeras 25 y el pool nunca avanzaría.
    """
    pool = _leer_cache()
    if pool is None:
        pool = refrescar()
    if not pool:
        return []
    excluir = {e.lower().strip() for e in (excluir or set())}

    def ya_esta(emp: Dict[str, Any]) -> bool:
        n = emp["empresa"].lower()
        return any(x and (x in n or n in x) for x in excluir)

    libres = [e for e in pool if not ya_esta(e)
              and (vertical is None or e["vertical"] == vertical)]
    if not libres:
        return []
    # Offset por día del año: avanza sobre el pool sin repetir el mismo tramo.
    inicio = (datetime.now(timezone.utc).timetuple().tm_yday * cantidad) % len(libres)
    rotado = libres[inicio:] + libres[:inicio]
    # Con teléfono primero: son los que más rápido se verifican.
    rotado.sort(key=lambda e: 0 if e["telefono"] else 1)
    return rotado[:cantidad]


def bloque_por_cupo(cupo: Dict[str, int], excluir: Optional[set] = None) -> str:
    """Igual que `bloque_prompt` pero respetando el cupo por vertical."""
    try:
        emps = candidatos_por_cupo(cupo, excluir)
    except Exception as e:
        log.warning("osm_bloque_cupo_failed", error=str(e)[:150])
        return ""
    return _formatear(emps)


def bloque_prompt(cantidad: int = 25, excluir: Optional[set] = None) -> str:
    """El bloque que se le inyecta al agente. Vacío si no hay nada (nunca rompe)."""
    try:
        emps = candidatos(cantidad, excluir)
    except Exception as e:
        log.warning("osm_bloque_failed", error=str(e)[:150])
        return ""
    return _formatear(emps)


def _formatear(emps: List[Dict[str, Any]]) -> str:
    if not emps:
        return ""
    filas = [f"{i}. **{e['empresa']}** — {e['web']}"
             + (f" — tel {e['telefono']}" if e["telefono"] else "")
             + (f" — {e['ciudad']}" if e["ciudad"] else "")
             for i, e in enumerate(emps, 1)]
    return (
        "\n\n## 🎯 CANDIDATAS YA DESCUBIERTAS (OpenStreetMap — datos abiertos, reales)\n"
        "Estas empresas EXISTEN y su sitio está publicado. **Empezá por acá**: no "
        "gastes turnos buscando desde cero ni adivinando dominios.\n"
        "Tu trabajo con cada una: abrir el sitio, confirmar rubro y tamaño (25–100 "
        "empleados), sacar el contacto REAL del sitio, detectar el dolor concreto y "
        "escribir el outreach. Descartá las que no den el perfil y seguí con la "
        "siguiente — no fuerces una que no encaja.\n"
        "Si necesitás más (o querés el decisor, noticias o señales de dolor), ahí sí "
        "usá la búsqueda web.\n\n" + "\n".join(filas) + "\n"
    )
