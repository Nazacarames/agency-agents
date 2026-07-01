#!/usr/bin/env python3
"""
Setup OAuth de YouTube para subir Shorts — se corre UNA SOLA VEZ, local.

Usa NUESTRO cliente OAuth (client_secret.json, Desktop app del proyecto
project-aa6a207a) — el mismo que ya funciona con automiqaiagency@gmail.com para
Gmail. A diferencia de la app "Google Cloud SDK" (gcloud), nuestro cliente SÍ puede
pedir el permiso de YouTube (no cae en "app bloqueada").

Mintea un refresh_token con scopes youtube.upload + youtube.readonly y escribe
scripts/youtube_token.json en formato authorized_user, listo para cargar como
YOUTUBE_OAUTH_JSON en Railway.

── Requisitos (ya deberían estar) ──
 - YouTube Data API habilitada en el proyecto (hecho).
 - automiqaiagency@gmail.com como Test user del consent screen (ya está, por Gmail).
 - Si el flow tira "scope no permitido": en Cloud Console → OAuth consent screen →
   Edit → Scopes → Add → youtube.upload y youtube.readonly → Save. Después reintentar.

── Correr ──
    python scripts/youtube_oauth_setup.py            # usa ./client_secret.json
Se abre el navegador → logueate como automiqaiagency@gmail.com → si dice "app no
verificada": Configuración avanzada → Continuar → aceptá los permisos de YouTube.
"""
import json
import sys
from pathlib import Path

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]


def main() -> int:
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Falta dependencia: pip install google-auth-oauthlib")
        return 1

    secret_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "client_secret.json"
    if not secret_path.exists():
        print(f"No encuentro el client JSON en: {secret_path}")
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(str(secret_path), SCOPES)
    creds = flow.run_local_server(
        port=0, access_type="offline", prompt="consent", open_browser=True,
        authorization_prompt_message=(
            "Autorizá YouTube (subir videos). Si no se abrió el navegador, abrí esta "
            "URL y logueate como automiqaiagency@gmail.com:\n\n{url}\n"
        ),
    )
    if not creds.refresh_token:
        print("No vino refresh_token. Revocá el acceso en "
              "https://myaccount.google.com/permissions y reintentá.")
        return 1

    # client_id/secret: leerlos del archivo del cliente (flow.client_config puede no
    # exponerlos bien → quedarían vacíos y el refresh falla con "client ID from request").
    cs = json.loads(secret_path.read_text(encoding="utf-8"))
    cs = cs.get("installed") or cs.get("web") or {}
    out = {
        "type": "authorized_user",
        "client_id": cs.get("client_id", ""),
        "client_secret": cs.get("client_secret", ""),
        "refresh_token": creds.refresh_token,
    }
    token_path = Path(__file__).parent / "youtube_token.json"
    token_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print("\n" + "=" * 60)
    print("OAuth YouTube OK. Credencial en: " + str(token_path))
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
