#!/usr/bin/env python3
"""
Setup OAuth de Google Ads — se corre UNA SOLA VEZ, local. Mintea el refresh_token
para que media_auditor lea la cuenta de Ads por la API.

── Pasos previos (Google Cloud Console) ──
 1. Crear/seleccionar un proyecto.
 2. APIs & Services → Library → habilitar "Google Ads API".
 3. APIs & Services → OAuth consent screen → User type "External" → completar →
    en "Test users" agregar la cuenta con acceso al Ads (ej: ventas@automiq.agency).
 4. APIs & Services → Credentials → Create Credentials → OAuth client ID →
    Application type "Desktop app" → Create → Download JSON.
 5. Guardar ese JSON como  client_secret_ads.json  al lado de este script.

APARTE (no es Cloud Console): el DEVELOPER TOKEN sale de una cuenta Manager (MCC)
→ Herramientas → API Center. Pedí "Basic access" para leer cuentas reales (~1-2 días).

── Correr ──
    pip install google-auth-oauthlib
    python scripts/google_ads_oauth.py                    # usa ./client_secret_ads.json
    python scripts/google_ads_oauth.py ruta.json          # o pasá la ruta

Se abre el navegador → logueate con la cuenta que tiene acceso al Ads → aceptá.
Al final imprime CLIENT_ID / CLIENT_SECRET / REFRESH_TOKEN para pegar en Railway
(GOOGLE_ADS_CLIENT_ID / _CLIENT_SECRET / _REFRESH_TOKEN). Falta sumar a mano
GOOGLE_ADS_DEVELOPER_TOKEN, GOOGLE_ADS_CUSTOMER_ID y (si aplica) _LOGIN_CUSTOMER_ID.
"""
import sys
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/adwords"]


def main() -> int:
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Falta dependencia. Corré:\n  pip install google-auth-oauthlib")
        return 1

    secret_path = (Path(sys.argv[1]) if len(sys.argv) > 1
                   else Path(__file__).parent / "client_secret_ads.json")
    if not secret_path.exists():
        print(f"❌ No encuentro el client JSON en: {secret_path}")
        print("   Descargalo de Cloud Console (OAuth client ID, Desktop app) y guardalo ahí.")
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(str(secret_path), SCOPES)
    creds = flow.run_local_server(
        port=0, access_type="offline", prompt="consent", open_browser=True,
        authorization_prompt_message=(
            "Autorizá Google Ads (solo lectura). Si no se abrió el navegador, abrí "
            "esta URL y logueate con la cuenta que tiene acceso al Ads:\n\n{url}\n"),
    )

    if not creds.refresh_token:
        print("⚠️ No vino refresh_token. Revocá el acceso previo en "
              "https://myaccount.google.com/permissions y volvé a correr.")
        return 1

    info = (flow.client_config.get("installed") or flow.client_config.get("web") or {})
    out = {
        "GOOGLE_ADS_CLIENT_ID": info.get("client_id", ""),
        "GOOGLE_ADS_CLIENT_SECRET": info.get("client_secret", ""),
        "GOOGLE_ADS_REFRESH_TOKEN": creds.refresh_token,
    }
    import json as _json
    token_path = Path(__file__).parent / "google_ads_token.json"
    token_path.write_text(_json.dumps(out, indent=2), encoding="utf-8")

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print("\n" + "=" * 70)
    print("OAuth OK. Las 3 env vars quedaron en: " + str(token_path))
    for k, v in out.items():
        print(f"{k}={v}")
    print("Falta sumar a mano: GOOGLE_ADS_DEVELOPER_TOKEN, GOOGLE_ADS_CUSTOMER_ID"
          " (y GOOGLE_ADS_LOGIN_CUSTOMER_ID si accedés vía MCC).")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
