#!/usr/bin/env python3
"""
scout_watch — motor del "visual scout": baja contenido REAL de competidores y marcas
de referencia (YouTube + TikTok) y arma un contact sheet (varios frames en 1 PNG) +
captions por fuente, para que un humano/Claude Code lo MIRE y destile el playbook de
edición/hooks/visual (data/visual-scout.md), que después se inyecta a los agentes.

Corre LOCAL a propósito (IP residencial): yt-dlp desde un datacenter (Railway) lo
bloquean seguido YouTube/TikTok. Deps: yt-dlp + ffmpeg (ya instalados en la máquina).

Uso:
    python scripts/scout_watch.py                       # todo el roster (YT+TikTok)
    python scripts/scout_watch.py kommo shopify         # solo esas claves
    python scripts/scout_watch.py https://instagram.com/reel/XXXX/   # URL directa (IG usa cookies)
Salida: data/scout/latest/<clave>_sheet.png + <clave>.caption.txt + manifest.md
Nota: yt-dlp NO lista perfiles de IG (extractor roto) → para IG pasá URLs de reel directas.
"""
from __future__ import annotations

import subprocess
import sys
import urllib.request
from pathlib import Path

# reusa la integración de la app para descubrir reels de IG por API oficial (Business
# Discovery) — así NO hace falta pegar URLs a mano. Requiere META_PAGE_TOKEN +
# IG_BUSINESS_ID en el entorno (o correrlo donde la app tenga la config).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from app.integrations import ig_discovery
except Exception:
    ig_discovery = None

# Roster: clave -> (etiqueta, query de búsqueda). YouTube+TikTok andan por búsqueda.
# TikTok se fuerza con el prefijo del sitio en la query cuando conviene.
ROSTER = {
    # Competidores (bot/CRM de mensajería)
    "kommo":      ("Kommo (competidor)",      "Kommo CRM WhatsApp salesbot español"),
    "manychat":   ("ManyChat (competidor)",   "ManyChat instagram dm automation demo"),
    # Marcas de referencia e-commerce (mucho ad — de acá robamos estética/edición)
    "tiendanube": ("Tiendanube (ref e-comm)", "Tiendanube comercial anuncio emprendedores"),
    "shopify":    ("Shopify (ref e-comm)",    "Shopify commercial small business ad"),
    "meli":       ("Mercado Libre (ref)",     "Mercado Libre comercial anuncio vendedores"),
}

# Cookies exportadas (Chrome nuevo no deja leerlas en vivo). Se usan para URLs de IG.
# OJO: yt-dlp NO puede listar perfiles/reels de IG (extractor roto) → IG sólo funciona
# pasando URLs DIRECTAS de un reel (instagram.com/reel/<code>/), no el perfil.
IG_COOKIES = Path.home() / ".config" / "scout" / "ig_cookies.txt"


def _sh(cmd: list[str], timeout: int = 240) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _download(query: str, out_mp4: Path) -> bool:
    """Baja los primeros ~28s del mejor match corto (garantiza clip, evita el 429 de
    subtítulos que aborta el download)."""
    cmd = ["yt-dlp", "--no-warnings", "-q", "--playlist-items", "1",
           "--download-sections", "*0-28", "-f", "b[height<=720]/b/best",
           "--merge-output-format", "mp4", "-o", str(out_mp4), f"ytsearch6:{query}"]
    _sh(cmd)
    return out_mp4.exists()


def _caption(query: str, prefix: Path) -> str:
    """Intenta bajar captions (aparte del video para no arriesgar el 429). Best-effort."""
    import re
    cmd = ["yt-dlp", "--no-warnings", "-q", "--skip-download", "--write-auto-sub",
           "--sub-lang", "es,es-419,en", "--playlist-items", "1",
           "-o", str(prefix) + ".%(ext)s", f"ytsearch1:{query}"]
    _sh(cmd, timeout=90)
    # junta el texto plano del primer sub (.srt o .vtt) que aparezca
    subs = sorted(prefix.parent.glob(prefix.name + "*.vtt")) + \
        sorted(prefix.parent.glob(prefix.name + "*.srt"))
    text = ""
    for sub in subs:
        lines = []
        for ln in sub.read_text(encoding="utf-8", errors="ignore").splitlines():
            ln = ln.strip()
            if (not ln or ln.isdigit() or "-->" in ln or ln.startswith("WEBVTT")
                    or ln.startswith(("Kind:", "Language:", "align:", "position:"))):
                continue
            ln = re.sub(r"<[^>]+>", "", ln).strip()      # saca tags de tiempo inline del vtt
            if ln:
                lines.append(ln)
        out, prev = [], None
        for ln in lines:                                  # dedup consecutivos (auto-subs repiten)
            if ln != prev:
                out.append(ln)
            prev = ln
        text = " ".join(out)[:2000]
        break
    for sub in subs:                                      # limpieza de los archivos de subs
        try:
            sub.unlink()
        except OSError:
            pass
    return text


def _download_url(url: str, out_mp4: Path) -> bool:
    """Baja un video de una URL directa (reel de IG, video de TikTok/YT, etc.).
    Para IG usa las cookies exportadas (si existen)."""
    ck = ["--cookies", str(IG_COOKIES)] if ("instagram.com" in url and IG_COOKIES.exists()) else []
    cmd = ["yt-dlp", "--no-warnings", "-q", "--playlist-items", "1", *ck,
           "-f", "b[height<=720]/b/best", "--merge-output-format", "mp4",
           "-o", str(out_mp4), url]
    _sh(cmd)
    return out_mp4.exists()


def _sheet(mp4: Path, out_png: Path) -> bool:
    """6 frames a timestamps fijos (robusto sin duración) → montage 3x2."""
    work = out_png.parent
    tmp = [work / f"_{out_png.stem}_f{i}.png" for i in range(6)]
    for t, f in zip([1, 5, 9, 13, 18, 24], tmp):
        _sh(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(mp4),
             "-frames:v", "1", "-vf", "scale=300:-1", str(f), "-y"], timeout=60)
    have = [f for f in tmp if f.exists()]
    if not have:
        return False
    for f in tmp:  # rellena faltantes (video corto) con el último disponible
        if not f.exists():
            _sh(["ffmpeg", "-v", "error", "-i", str(have[-1]), "-c", "copy", str(f), "-y"])
    _sh(["ffmpeg", "-v", "error", *sum([["-i", str(f)] for f in tmp], []),
         "-filter_complex", "[0][1][2]hstack=3[a];[3][4][5]hstack=3[b];[a][b]vstack",
         str(out_png), "-y"], timeout=60)
    for f in tmp:
        try:
            f.unlink()
        except OSError:
            pass
    return out_png.exists()


def main(keys: list[str]) -> int:
    root = Path(__file__).resolve().parent.parent
    out = root / "data" / "scout" / "latest"
    out.mkdir(parents=True, exist_ok=True)
    urls = [a for a in keys if a.startswith("http")]
    keys = [k for k in keys if k in ROSTER] or ([] if urls else list(ROSTER))
    manifest = ["# Scout — contact sheets para MIRAR y destilar\n"]
    sheets: list[tuple[str, str, str]] = []   # (label, sheet_path, caption) para el distill
    for k in keys:
        label, query = ROSTER[k]
        mp4 = out / f"{k}.mp4"
        print(f"[scout] {k}: bajando…", flush=True)
        if not _download(query, mp4):
            print(f"[scout] {k}: sin video")
            manifest.append(f"- **{label}** — ❌ no se pudo bajar\n")
            continue
        sheet = out / f"{k}_sheet.png"
        ok = _sheet(mp4, sheet)
        cap = _caption(query, out / f"{k}")
        (out / f"{k}.caption.txt").write_text(cap, encoding="utf-8")
        try:
            mp4.unlink()
        except OSError:
            pass
        print(f"[scout] {k}: sheet={'OK' if ok else 'FAIL'} caption={len(cap)} chars")
        manifest.append(f"## {label}\n- sheet: `{sheet.name}`\n- caption: "
                        f"{(cap[:180] + '…') if cap else '(sin captions)'}\n")
        if ok:
            sheets.append((label, str(sheet), cap))

    # Instagram AUTOMÁTICO vía Business Discovery (API oficial, no scraping). Baja el
    # video_url del CDN directo → sheet. Se activa si hay token (META_PAGE_TOKEN + IG_BUSINESS_ID).
    if ig_discovery and ig_discovery.enabled():
        for key, handle in ig_discovery.IG_HANDLES.items():
            reels = ig_discovery.recent_reels(handle, n=1)
            if not reels:
                print(f"[scout] ig:{key} ({handle}): sin reels")
                manifest.append(f"- **IG {handle}** — sin reels (handle o cuenta no business)\n")
                continue
            r = reels[0]
            mp4 = out / f"ig_{key}.mp4"
            try:
                urllib.request.urlretrieve(r["media_url"], str(mp4))
            except Exception as e:
                print(f"[scout] ig:{key}: download fail {str(e)[:80]}")
                continue
            sheet = out / f"ig_{key}_sheet.png"
            ok = _sheet(mp4, sheet)
            try:
                mp4.unlink()
            except OSError:
                pass
            print(f"[scout] ig:{key}: sheet={'OK' if ok else 'FAIL'} | {r.get('permalink')}")
            manifest.append(f"## IG {handle}\n- sheet: `{sheet.name}`\n- {r.get('permalink')}\n"
                            f"- caption: {(r.get('caption') or '')[:160]}\n")
            if ok:
                sheets.append((f"IG {handle}", str(sheet), r.get("caption") or ""))
    else:
        print("[scout] IG auto: salteado (falta META_PAGE_TOKEN / IG_BUSINESS_ID)")

    # URLs directas (reels de IG, videos de TikTok/YT que pases a mano)
    for i, url in enumerate(urls):
        name = f"url{i+1}"
        mp4 = out / f"{name}.mp4"
        print(f"[scout] {name}: bajando {url[:60]}…", flush=True)
        if not _download_url(url, mp4):
            manifest.append(f"- **{url}** — no se pudo bajar\n")
            continue
        sheet = out / f"{name}_sheet.png"
        ok = _sheet(mp4, sheet)
        try:
            mp4.unlink()
        except OSError:
            pass
        print(f"[scout] {name}: sheet={'OK' if ok else 'FAIL'}")
        manifest.append(f"## {url}\n- sheet: `{sheet.name}`\n")
        if ok:
            sheets.append((url, str(sheet), ""))

    (out / "manifest.md").write_text("\n".join(manifest), encoding="utf-8")
    # Cierra el loop: Gemini MIRA los sheets y escribe el playbook (data/visual-scout.md).
    _distill(sheets, root / "data" / "visual-scout.md")
    print(f"[scout] listo -> {out}")
    return 0


_DISTILL_PROMPT = (
    "Sos director de contenido de una agencia argentina que hace TikToks/Reels para "
    "dueños de PyME sobre IA y bots de WhatsApp. Adjunto contact sheets (6 frames c/u) "
    "de reels REALES de competidores y marcas e-commerce de referencia. MIRALOS y escribí "
    "un playbook de EDICIÓN/hooks/formato, concreto y accionable, en español rioplatense, "
    "con estas secciones EXACTAS:\n"
    "## Regla madre (variar formato, orgánico)\n## Dónde va la demo del bot\n"
    "## Hooks (con ejemplos concretos que veas)\n## Edición que se siente orgánica\n"
    "## Imágenes/banners para ads\n"
    "Basate SOLO en lo que ves en los frames (y las captions de contexto abajo). Nada de "
    "genéricos: citá qué hacen (dónde ponen la demo, tipografía de carteles, cortes, PiP, "
    "b-roll). Máx ~350 palabras. Contexto (captions):\n"
)


def _distill(sheets: list, out_md: Path) -> bool:
    """Gemini mira los sheets y escribe data/visual-scout.md. Best-effort: si no hay
    visión configurada o falla, no toca el archivo (queda el SEED en código)."""
    if not sheets:
        return False
    try:
        from app.integrations import vision
    except Exception:
        print("[scout] distill: sin módulo vision"); return False
    if not vision.enabled():
        print("[scout] distill: visión no configurada (falta GOOGLE_SERVICE_ACCOUNT_JSON) → queda el SEED")
        return False
    ctx = "\n".join(f"- {lbl}: {(cap or '')[:180]}" for lbl, _p, cap in sheets)
    paths = [p for _l, p, _c in sheets]
    txt = vision.describe(paths, _DISTILL_PROMPT + ctx)
    if not txt or len(txt) < 200:
        print("[scout] distill: respuesta vacía/corta → queda el SEED"); return False
    body = ("=== VISUAL SCOUT — playbook de EDICIÓN / hooks / formato (MIRADO por Gemini) ===\n"
            "_Auto-destilado de reels reales (YT+TikTok+IG) por el scout. Foco VIDEO._\n\n"
            + txt.strip() + "\n=== fin visual scout ===\n")
    out_md.write_text(body, encoding="utf-8")
    print(f"[scout] distill OK -> {out_md} ({len(txt)} chars)")
    return True


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
