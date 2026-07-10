"""
Parser/formatter del MD de LeadHunter.

`parse_leads(md_text)`: extrae los leads del bloque "## 🟢 Lead #N" o
"## Lead #N" del MD. Devuelve una lista de dicts con los campos
principales (empresa, web, ciudad, fit_score, contacto, etc.).

`format_leads_md(leads, ...)`: regenera el MD completo con el bloque
de detalle por lead enriquecido con `contacto_validado` cuando existe.

Es un parser tolerante: si el formato exacto no matchea, devuelve lista
vacía y el caller deja el MD como estaba.
"""
from __future__ import annotations

import re
from typing import List, Dict, Optional

# Detecta un lead por su heading: "## 🟢 Lead #1" o "## Lead #1" o "## Lead 1".
# Separador OPCIONAL, igual que leads_store.py — con separador obligatorio un
# heading "## Lead 3 Empresa" era ingestado por leads_store pero este parser
# devolvía [] y el enriquecimiento se salteaba en silencio.
_LEAD_HEADER_RE = re.compile(
    r"^#{2,4}\s+(?:🟢\s+)?Lead\s*#?\s*(\d+)\s*[:\-—–]?\s*(.*?)\s*$",
    re.IGNORECASE,
)
# Detecta líneas "| **campo** | valor |"
_FIELD_RE = re.compile(
    r"^\|\s*\*\*([^*]+)\*\*\s*\|\s*(.+?)\s*\|",
    re.IGNORECASE,
)


def parse_leads(md_text: str) -> List[Dict]:
    """Devuelve lista de leads parseados del MD. Vacía si no matchea formato."""
    if not md_text:
        return []
    lines = md_text.splitlines()
    leads: List[Dict] = []
    current: Optional[Dict] = None
    for line in lines:
        m = _LEAD_HEADER_RE.match(line)
        if m:
            if current:
                leads.append(current)
            current = {
                "numero": int(m.group(1)),
                "titulo": m.group(2),
                "campos": {},
            }
            continue
        if current is None:
            continue
        fm = _FIELD_RE.match(line)
        if fm:
            key = fm.group(1).strip().lower().replace(" ", "_")
            val = fm.group(2).strip()
            current["campos"][key] = val
    if current:
        leads.append(current)

    # Normalizar: aplanar campos comunes a nivel top para conveniencia
    out: List[Dict] = []
    for lead in leads:
        campos = lead.get("campos", {})
        out.append({
            "numero": lead.get("numero"),
            "titulo": lead.get("titulo", ""),
            "empresa": campos.get("empresa", ""),
            "web": campos.get("web", ""),
            "ciudad": campos.get("ubicación") or campos.get("ubicacion") or campos.get("ciudad", ""),
            "industria": campos.get("industria", ""),
            "fit_score": campos.get("fit_score", ""),
            "contacto_raw": campos.get("contacto_(raw)") or campos.get("contacto", ""),
            "contacto_tipo": campos.get("contacto_tipo", ""),
            "contacto_verified_raw": campos.get("contacto_verified", ""),
            "decisor": campos.get("decisor", ""),
        })
    return out


def _strip_brackets(s: str) -> str:
    """Quita [...] markers de un valor de campo del MD."""
    return re.sub(r"\[.*?\]", "", s or "").strip()


def _has_real_value(s: str) -> bool:
    """True si el campo tiene un valor real (no es placeholder [PENDIENTE] / [EJEMPLO])."""
    if not s:
        return False
    if "[" in s and "]" in s:
        return False
    return bool(s.strip())


def format_leads_md(leads: List[Dict], today: str, base_md: str) -> str:
    """Reescribe el bloque de detalle de leads agregando `contacto_validado`.

    Si el MD no matchea el formato esperado, devuelve `base_md` tal cual.
    """
    if not leads:
        return base_md

    # Construir el bloque enriquecido
    enriched_blocks: List[str] = []
    for lead in leads:
        n = lead.get("numero")
        titulo = (lead.get("titulo") or "").strip(" —-–:")
        # Header
        if titulo:
            block = f"## 🟢 Lead #{n} — {titulo}\n"
        else:
            block = f"## 🟢 Lead #{n}\n"
        # Tabla con los campos existentes
        campos = [
            ("empresa", lead.get("empresa", "")),
            ("industria", lead.get("industria", "")),
            ("ubicación", lead.get("ciudad", "")),
            ("web", lead.get("web", "")),
            ("fit_score", lead.get("fit_score", "")),
            ("contacto (raw)", lead.get("contacto_raw", "")),
            ("contacto_tipo", lead.get("contacto_tipo", "")),
            ("contacto_verified", lead.get("contacto_verified_raw", "false")),
            ("decisor", lead.get("decisor", "")),
        ]
        block += "\n| Campo | Valor |\n|---|---|\n"
        for k, v in campos:
            if v:
                block += f"| **{k}** | {v} |\n"
        # Bloque de validación si existe
        val = lead.get("contacto_validado")
        if val:
            block += "\n✅ **Contacto verificado por scraping:**\n"
            if val.get("telefono"):
                block += f"- 📞 Teléfono: `{val['telefono']}`\n"
            if val.get("email"):
                block += f"- 📧 Email: `{val['email']}`\n"
            if val.get("source_url"):
                block += f"- 🔗 Fuente: {val['source_url']}\n"
        enriched_blocks.append(block)

    # Reemplazar el rango de bloques en base_md
    # Estrategia: encontrar el primer "## 🟢 Lead #" o "## Lead #" y
    # mantener todo lo anterior. Reemplazar desde ahí hasta el final
    # o hasta el próximo bloque que no sea detail de lead.
    lines = base_md.splitlines()
    first_lead_idx = None
    for i, line in enumerate(lines):
        if _LEAD_HEADER_RE.match(line):
            first_lead_idx = i
            break
    if first_lead_idx is None:
        return base_md

    # Header + intro: conservar todo lo anterior al primer lead
    header = "\n".join(lines[:first_lead_idx])
    # Reemplazar todo el resto con los bloques enriquecidos
    return header.rstrip() + "\n\n" + "\n\n".join(enriched_blocks) + "\n"
