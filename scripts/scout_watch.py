#!/usr/bin/env python3
"""
scout_watch — "visual scout" de video: baja contenido REAL de competidores/marcas de
referencia, se lo pasa a **Gemini que analiza el VIDEO ENTERO** (movimiento + AUDIO +
texto en pantalla en el tiempo) y destila un playbook de edición/hooks/formato
(data/visual-scout.md) que se inyecta a los agentes. Cierra el loop descubre→mira→destila.

Corre LOCAL a propósito (IP residencial): yt-dlp desde un datacenter (Railway) lo
bloquean TikTok/YouTube. Deps: yt-dlp + ffmpeg. Vision: Gemini vía Vertex (necesita
GOOGLE_SERVICE_ACCOUNT_JSON en el entorno; se puede traer con `railway variables --json`).
IG no usa yt-dlp (extractor de perfiles roto) → Business Discovery API (ig_discovery).

Uso:
    python scripts/scout_watch.py                 # TikTok + IG (+ YT backup)
    python scripts/scout_watch.py --yt            # además YouTube por búsqueda
    python scripts/scout_watch.py https://tiktok.com/@x/video/123   # URL suelta
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

try:  # consola de Windows (cp1252) rompe con acentos/flechas en los prints
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from app.integrations import ig_discovery, vision
except Exception:
    ig_discovery = vision = None

# TikTok = perfil (lo que el usuario produce); YT = búsqueda (backup). Handles best-effort.
TIKTOK = {   # handles VERIFICADOS 2026-07-05 (kommo TikTok es privado → cae a YT backup)
    "manychat":   "https://www.tiktok.com/@manychat",
    "shopify":    "https://www.tiktok.com/@shopify",
    "tiendanube": "https://www.tiktok.com/@nuvemshop",
    "meli":       "https://www.tiktok.com/@mercadolibre.ar",
    "kommo":      "https://www.tiktok.com/@kommo",  # privado → backup YouTube
}
YT = {
    "kommo":      "Kommo CRM WhatsApp salesbot español",
    "manychat":   "ManyChat instagram dm automation demo",
    "tiendanube": "Tiendanube comercial anuncio emprendedores",
    "shopify":    "Shopify commercial small business ad",
    "meli":       "Mercado Libre comercial anuncio vendedores",
}


def _sh(cmd: list[str], timeout: int = 240) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _dl(url_or_search: str, out_mp4: Path, cookies: Path | None = None) -> bool:
    ck = ["--cookies", str(cookies)] if cookies and cookies.exists() else []
    cmd = ["yt-dlp", "--no-warnings", "-q", "--playlist-items", "1", *ck,
           "-f", "b[height<=720]/b/best", "--merge-output-format", "mp4",
           "-o", str(out_mp4), url_or_search]
    _sh(cmd)
    return out_mp4.exists()


def _dl_cdn(url: str, out_mp4: Path) -> bool:
    import urllib.request
    try:
        urllib.request.urlretrieve(url, str(out_mp4))
        return out_mp4.exists()
    except Exception:
        return False


def _shrink(src: Path, dst: Path) -> bool:
    """Achica el video para caber inline en Gemini (<~18MB): 480p, primeros 45s, audio
    conservado (Gemini lo escucha)."""
    _sh(["ffmpeg", "-v", "error", "-y", "-t", "45", "-i", str(src),
         "-vf", "scale=-2:480", "-c:v", "libx264", "-crf", "30", "-preset", "veryfast",
         "-c:a", "aac", "-b:a", "64k", str(dst)])
    return dst.exists() and dst.stat().st_size < 18 * 1024 * 1024


_NOTE_PROMPT = (
    "Analizá este TikTok/reel de un competidor o marca de referencia (mirá el video Y "
    "escuchá el audio). En español rioplatense, MUY concreto y breve (~120 palabras), con: "
    "HOOK exacto (primeros 3s: qué dice/muestra), FORMATO/EDICIÓN (cortes, PiP, texto en "
    "pantalla, ritmo, música), DÓNDE va la demo del producto, y QUÉ ROBAR para TikToks de "
    "bots de WhatsApp para PyMEs argentinas. Nada genérico: citá lo que ves y oís."
)
_SYNTH_PROMPT = (
    "Sos director de contenido de una agencia argentina (TikToks/Reels sobre IA y bots de "
    "WhatsApp para PyMEs). Abajo hay notas de análisis de reels REALES de competidores y "
    "marcas de referencia. Sintetizalas en UN playbook accionable en español rioplatense, "
    "con estas secciones EXACTAS:\n## Regla madre (variar formato, orgánico)\n"
    "## Dónde va la demo del bot\n## Hooks (con ejemplos concretos)\n"
    "## Edición que se siente orgánica\n## Imágenes/banners para ads\n"
    "Citá ejemplos concretos de las notas. Máx ~380 palabras. NOTAS:"
)


def _analyze(mp4: Path, work: Path, label: str) -> str:
    """Achica + Gemini analiza el video entero → nota. "" si algo falla."""
    if not (vision and vision.enabled()):
        return ""
    small = work / f"s_{mp4.stem}.mp4"
    if not _shrink(mp4, small):
        return ""
    note = vision.describe_video(str(small), _NOTE_PROMPT)
    try:
        small.unlink()
    except OSError:
        pass
    return note


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parent.parent
    out = root / "data" / "scout" / "latest"
    out.mkdir(parents=True, exist_ok=True)
    do_yt = "--yt" in argv
    urls = [a for a in argv if a.startswith("http")]
    if not (vision and vision.enabled()):
        print("[scout] OJO: visión no configurada (falta GOOGLE_SERVICE_ACCOUNT_JSON) → "
              "no puedo destilar. Seteá la credencial (railway variables --json).")

    notes: list[tuple[str, str]] = []

    def handle(label: str, mp4: Path):
        if not mp4.exists():
            print(f"[scout] {label}: sin video"); return
        note = _analyze(mp4, out, label)
        try:
            mp4.unlink()
        except OSError:
            pass
        if note:
            notes.append((label, note))
            print(f"[scout] {label}: analizado ({len(note)} chars)")
        else:
            print(f"[scout] {label}: sin nota")

    # 1) TikTok por perfil (con backup a YouTube por búsqueda)
    for key, url in TIKTOK.items():
        print(f"[scout] tiktok:{key} …", flush=True)
        mp4 = out / f"tt_{key}.mp4"
        if _dl(url, mp4):
            handle(f"TikTok @{url.split('@')[-1]}", mp4)
        elif key in YT:
            print(f"[scout] tiktok:{key} falló → YouTube backup")
            if _dl(f"ytsearch1:{YT[key]}", mp4):
                handle(f"YouTube {key}", mp4)

    # 2) YouTube extra (opcional)
    if do_yt:
        for key, q in YT.items():
            mp4 = out / f"yt_{key}.mp4"
            if _dl(f"ytsearch1:{q}", mp4):
                handle(f"YouTube {key}", mp4)

    # 3) Instagram vía Business Discovery (API oficial, no yt-dlp)
    if ig_discovery and ig_discovery.enabled():
        for key, h in ig_discovery.IG_HANDLES.items():
            reels = ig_discovery.recent_reels(h, n=15)
            if not reels:
                continue
            print(f"[scout] ig:{key} ({h}) …", flush=True)
            mp4 = out / f"ig_{key}.mp4"
            if _dl_cdn(reels[0]["media_url"], mp4):
                handle(f"IG @{h}", mp4)

    # 4) URLs sueltas
    for i, url in enumerate(urls):
        mp4 = out / f"url{i+1}.mp4"
        ck = ig_discovery.IG_COOKIES if False else None  # (IG usa Business Discovery, no cookies)
        if _dl(url, mp4):
            handle(url, mp4)

    # 5) Sintetizar el playbook y escribir data/visual-scout.md
    if not notes:
        print("[scout] sin notas → no toco visual-scout.md (queda el SEED)")
        return 0
    blob = "\n\n".join(f"### {lbl}\n{note}" for lbl, note in notes)
    (out / "notes.md").write_text(blob, encoding="utf-8")
    playbook = vision.synthesize(blob, _SYNTH_PROMPT) if (vision and vision.enabled()) else ""
    if not playbook or len(playbook) < 200:
        print("[scout] síntesis vacía → guardo las notas crudas como playbook")
        playbook = blob
    body = ("=== VISUAL SCOUT — playbook de EDICIÓN / hooks / formato (MIRADO por Gemini, video nativo) ===\n"
            "_Auto-destilado de reels reales (TikTok/IG/YT) por el scout. Foco VIDEO._\n\n"
            + playbook.strip() + "\n=== fin visual scout ===\n")
    (root / "data" / "visual-scout.md").write_text(body, encoding="utf-8")
    print(f"[scout] LISTO: {len(notes)} fuentes → data/visual-scout.md ({len(playbook)} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
