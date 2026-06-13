#!/usr/bin/env python3
"""
Setup OAuth de Gmail para el Inbox Assistant — se corre UNA SOLA VEZ, local.

Mintea un refresh_token para la cuenta dedicada (automiqaiagency@gmail.com) con
scopes LEER + BORRADORES (gmail.readonly + gmail.compose). Después se cargan
GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET / GMAIL_REFRESH_TOKEN como env vars en Railway.

── Pasos previos (en Google Cloud Console, con la cuenta automiqaiagency@gmail.com) ──
 1. Crear/seleccionar un proyecto.
 2. APIs & Services → Library → habilitar "Gmail API".
 3. APIs & Services → OAuth consent screen → User type "External" → completar →
    en "Test users" agregar automiqaiagency@gmail.com.
 4. APIs & Services → Credentials → Create Credentials → OAuth client ID →
    Application type "Desktop app" → Create → Download JSON.
 5. Guardar ese JSON como  client_secret.json  al lado de este script.

── Correr ──
    pip install google-auth-oauthlib google-api-python-client
    python scripts/gmail_oauth_setup.py            # usa ./client_secret.json
    python scripts/gmail_oauth_setup.py ruta.json  # o pasá la ruta

Se abre el navegador → logueate como automiqaiagency@gmail.com → aceptá los permisos.
Al final imprime el CLIENT_ID / CLIENT_SECRET / REFRESH_TOKEN para pegar en Railway.
"""
import sys
from pathlib import Path

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]


def main() -> int:
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Falta dependencia. Corré:\n  pip install google-auth-oauthlib google-api-python-client")
        return 1

    secret_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "client_secret.json"
    if not secret_path.exists():
        print(f"❌ No encuentro el client JSON en: {secret_path}")
        print("   Descargalo de Google Cloud Console (OAuth client ID, Desktop app) y guardalo ahí.")
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(str(secret_path), SCOPES)
    # access_type=offline + prompt=consent → garantiza que devuelva refresh_token
    creds = flow.run_local_server(
        port=0, access_type="offline", prompt="consent",
        authorization_prompt_message="Abriendo el navegador para autorizar Gmail (leer + borradores)…",
    )

    if not creds.refresh_token:
        print("⚠️ No vino refresh_token. Revocá el acceso previo en "
              "https://myaccount.google.com/permissions y volvé a correr con prompt=consent.")
        return 1

    info = flow.client_config["installed"] if "installed" in flow.client_config else flow.client_config.get("web", {})
    print("\n" + "=" * 70)
    print("✅ OAuth OK. Cargá estas 3 env vars en Railway (Service → Variables):\n")
    print(f"GMAIL_CLIENT_ID={info.get('client_id','')}")
    print(f"GMAIL_CLIENT_SECRET={info.get('client_secret','')}")
    print(f"GMAIL_REFRESH_TOKEN={creds.refresh_token}")
    print("=" * 70)
    print("\nDespués redeployá y probá:  POST /run/inbox_assistant  (args opcional dry_run=true)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
