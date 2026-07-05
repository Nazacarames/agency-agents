#!/usr/bin/env python3
"""
scout_watch — motor del "visual scout": baja contenido REAL de competidores y marcas
de referencia (YouTube + TikTok) y arma un contact sheet (varios frames en 1 PNG) +
captions por fuente, para que un humano/Claude Code lo MIRE y destile el playbook de
edición/hooks/visual (data/visual-scout.md), que después se inyecta a los agentes.

Corre LOCAL a propósito (IP residencial): yt-dlp desde un datacenter (Railway) lo
bloquean seguido YouTube/TikTok. Deps: yt-dlp + ffmpeg (ya instalados en la máquina).

Uso:
    python scripts/scout_watch.py                # todo el roster por defecto
    python scripts/scout_watch.py kommo shopify  # solo esas claves
Salida: data/scout/<fecha por args>/<clave>_sheet.png + <clave>.caption.txt + manifest.md
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

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

# Instagram: se activa SOLO si existe el cookies.txt exportado (Chrome nuevo no deja
# leer sus cookies en vivo). Perfiles reales del roster; se bajan los reels recientes.
IG_COOKIES = Path.home() / ".config" / "scout" / "ig_cookies.txt"
IG_ROSTER = {
    "kommo_ig":      ("Kommo IG",      "https://www.instagram.com/kommo/"),
    "manychat_ig":   ("ManyChat IG",   "https://www.instagram.com/manychat/"),
    "tiendanube_ig": ("Tiendanube IG", "https://www.instagram.com/tiendanube/"),
    "shopify_ig":    ("Shopify IG",    "https://www.instagram.com/shopify/"),
    "meli_ig":       ("Mercado Libre IG", "https://www.instagram.com/mercadolibre/"),
}


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


def _download_ig(profile_url: str, out_mp4: Path) -> bool:
    """Baja el reel más reciente de un perfil de IG usando el cookies.txt exportado.
    IG bloquea sin sesión → requiere IG_COOKIES."""
    if not IG_COOKIES.exists():
        return False
    cmd = ["yt-dlp", "--no-warnings", "-q", "--cookies", str(IG_COOKIES),
           "--playlist-items", "1", "-f", "b[height<=720]/b/best",
           "--merge-output-format", "mp4", "-o", str(out_mp4), profile_url]
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
    keys = [k for k in keys if k in ROSTER] or list(ROSTER)
    manifest = ["# Scout — contact sheets para MIRAR y destilar\n"]
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

    # Instagram (solo si hay cookies exportadas)
    if IG_COOKIES.exists():
        for k, (label, url) in IG_ROSTER.items():
            mp4 = out / f"{k}.mp4"
            print(f"[scout] {k}: bajando IG…", flush=True)
            if not _download_ig(url, mp4):
                manifest.append(f"- **{label}** — no se pudo bajar (reel privado/sin video)\n")
                continue
            sheet = out / f"{k}_sheet.png"
            ok = _sheet(mp4, sheet)
            try:
                mp4.unlink()
            except OSError:
                pass
            print(f"[scout] {k}: sheet={'OK' if ok else 'FAIL'}")
            manifest.append(f"## {label}\n- sheet: `{sheet.name}`\n")
    else:
        print(f"[scout] IG: salteado (falta {IG_COOKIES})")
        manifest.append(f"\n> IG salteado: falta el cookies.txt en `{IG_COOKIES}`\n")

    (out / "manifest.md").write_text("\n".join(manifest), encoding="utf-8")
    print(f"[scout] listo -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
