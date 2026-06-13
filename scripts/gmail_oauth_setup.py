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
    # access_type=offline + prompt=consent → garantiza que devuelva refresh_token.
    # El mensaje incluye {url} para imprimir el link (por si el navegador no se abre solo).
    creds = flow.run_local_server(
        port=0, access_type="offline", prompt="consent", open_browser=True,
        authorization_prompt_message=(
            "Autorizá Gmail (leer + borradores). Si no se abrió el navegador, "
            "abrí esta URL y logueate como automiqaiagency@gmail.com:\n\n{url}\n"
        ),
    )

    if not creds.refresh_token:
        print("⚠️ No vino refresh_token. Revocá el acceso previo en "
              "https://myaccount.google.com/permissions y volvé a correr con prompt=consent.")
        return 1

    info = flow.client_config["installed"] if "installed" in flow.client_config else flow.client_config.get("web", {})
    out = {
        "GMAIL_CLIENT_ID": info.get("client_id", ""),
        "GMAIL_CLIENT_SECRET": info.get("client_secret", ""),
        "GMAIL_REFRESH_TOKEN": creds.refresh_token,
    }
    # Fuente confiable: escribir a archivo (la consola de Windows puede romper en emojis/encoding)
    import json as _json
    token_path = Path(__file__).parent / "gmail_token.json"
    token_path.write_text(_json.dumps(out, indent=2), encoding="utf-8")

    # Print defensivo (sin emojis, por si la consola es cp1252)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print("\n" + "=" * 70)
    print("OAuth OK. Las 3 env vars quedaron en: " + str(token_path))
    for k, v in out.items():
        print(f"{k}={v}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
