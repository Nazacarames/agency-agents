"""
Config — settings tipados con pydantic-settings.
Lee de variables de entorno + .env (si existe).
"""
from functools import lru_cache
from typing import List
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── MiniMax-M3 ──
    # Decisión 2026-06-04: usar M3 (NO M2.7 como en OpenClaw) como modelo
    # principal de los agentes. M3 es el modelo más reciente de MiniMax.
    # Fallbacks: M2.5 (estable) y M2.5-highspeed (cuando necesitamos más velocidad).
    minimax_base_url: str = "https://api.minimax.io/anthropic"
    minimax_api_key: str = Field(default="", description="API key de MiniMax")
    minimax_model_primary: str = "MiniMax-M3"
    minimax_model_fallbacks: str = "MiniMax-M2.5,MiniMax-M2.5-highspeed"
    minimax_max_tokens: int = 8192
    minimax_timeout_seconds: int = 120

    # ── Discord ──
    discord_webhook_url: str = ""              # fallback general (canal por defecto)
    discord_default_username: str = "Automiq Agents"
    discord_avatar_url: str = ""
    # Ruteo por agente: JSON {"leadhunter": "https://discord.com/api/webhooks/...", ...}
    # (claves = nombre interno del agente). Si un agente no está, cae al webhook general.
    discord_agent_webhooks: str = ""
    discord_webhook_errors: str = ""           # canal de errores (fallos de agentes)
    discord_images_webhook_url: str = ""       # canal para espejar imágenes generadas (cae al general)
    discord_images_enabled: bool = True        # espejar a Discord cada imagen generada

    # ── Scheduler ──
    scheduler_timezone: str = "America/Buenos_Aires"
    scheduler_enabled: bool = True
    global_pause: bool = False

    # ── Web ──
    port: int = 8000
    host: str = "0.0.0.0"
    log_level: str = "INFO"
    webhook_secret: str = ""

    # ── Base de datos (Supabase Postgres) ──
    # Capa de memoria/DB de la agencia (memoria general + por-cliente + lecciones).
    # TODO vive bajo el schema `agency` (aislado de las tablas de Paperclip que
    # comparten la instancia). Si está vacío, los stores caen a JSON en el volume.
    database_url: str = ""
    db_schema: str = "agency"

    # ── Generación de imágenes ──
    # Provider: "vertex" (Google Imagen 4 vía Vertex AI — misma credencial que Veo,
    # calidad muy superior) con fallback automático a "minimax" (image-01) si falla
    # o no está configurado. "minimax" fuerza el viejo motor.
    images_enabled: bool = True
    image_prompt_refine: bool = True   # refinar el prompt con el image-prompt-engineer
    # Provider: "nano" (Nano Banana Pro / Gemini 3 Pro Image — mejor fidelidad al prompt)
    # → fallback "vertex" (Imagen 4) → "minimax" (image-01). Todo con la misma credencial.
    image_provider: str = "nano"
    nano_image_model: str = "gemini-3-pro-image"
    vertex_image_model: str = "imagen-4.0-generate-001"
    image_model: str = "image-01"    # fallback MiniMax
    # Tope de seguridad: el agente decide CUÁNTAS imágenes generar según su
    # planificación (1 por idea/post). Esto sólo evita que un plan enorme dispare
    # costo/tiempo de MiniMax sin control.
    content_image_count: int = 8     # máx imágenes por reporte de contenido

    # ── Publicación a redes (Meta Graph API: Instagram + Facebook) ──
    # Se setean cuando se crean las cuentas: una Página de FB + una cuenta de IG
    # Business linkeada a esa página. El Page token (long-lived) sirve para ambas.
    # Si faltan, /api/publish responde "no configurado" (no rompe nada más).
    meta_graph_version: str = "v21.0"
    meta_page_id: str = ""           # ID de la Página de Facebook
    meta_page_token: str = ""        # Page access token long-lived (SECRET)
    ig_business_id: str = ""         # ID de la cuenta de Instagram Business
    # Meta Ads: cuenta de anuncios (ej. act_1001254446126619) y token con ads_read.
    # El token cae a meta_page_token si no se setea uno específico.
    meta_ad_account_id: str = ""
    meta_ads_token: str = ""         # System User token con ads_read (SECRET)
    # Webhooks de Meta (comment-gate auto-DM). El verify token es el string que
    # se pega en App Dashboard → Webhooks al suscribir el callback; el app secret
    # (opcional pero recomendado) valida la firma X-Hub-Signature-256 de cada POST.
    meta_webhook_verify_token: str = ""   # (SECRET) sólo en env vars
    meta_app_secret: str = ""             # (SECRET) App Secret de la app de Meta
    # URL pública del backend, para que la Graph API pueda DESCARGAR la imagen
    # (las imágenes viven en /media/<file>). Ej: https://...up.railway.app
    public_base_url: str = ""
    # Microservicio externo de montaje de video (automiq-montage, RAM propia). Si está
    # seteada, tiktok_creator arma el short con él (split+subs+color+broll); si no o si
    # falla, cae al armado local de video_assembler. Ej: https://automiq-montage.up.railway.app
    montage_service_url: str = ""
    # Auto-publicación: si está ON, los agentes que planifican contenido
    # (content_creator, social_media) publican CADA imagen que generan en las
    # redes indicadas, con el caption que planificaron. Requiere tokens Meta.
    social_auto_publish: bool = True
    social_publish_targets: str = "instagram,facebook"   # CSV: instagram,facebook
    # Auto-archivar prospectos/clientes no-activos sin movimiento hace N días
    # (libera su memoria). Los clientes 'activo' (pagando) nunca se archivan.
    client_archive_days: int = 10

    @property
    def social_publish_configured(self) -> bool:
        return bool(self.meta_page_token and (self.meta_page_id or self.ig_business_id))

    def social_targets_list(self) -> list:
        return [t.strip().lower() for t in (self.social_publish_targets or "").split(",") if t.strip()]

    # ── Render (auto-injected) ──
    render_service_id: str = ""
    render_external_url: str = ""

    # ── Gmail (Inbox Assistant) ──
    # Cuenta dedicada (automiqaiagency@gmail.com). OAuth2 con refresh token.
    # Scopes: gmail.readonly + gmail.compose (LEER + BORRADORES). El agente
    # NUNCA envía: sólo crea borradores para revisión humana.
    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    gmail_refresh_token: str = ""
    gmail_user_id: str = "me"            # "me" = la cuenta dueña del token
    gmail_enabled: bool = True
    drive_sync_enabled: bool = True      # subida diaria de contenido/reportes/backups a Drive
    inbox_max_threads: int = 8           # cuántos hilos no-leídos procesar por run
    inbox_lookback_days: int = 7         # ventana de antigüedad para considerar un hilo
    # ⚠️ Si inbox_auto_send=True, el Inbox Assistant RESPONDE solo (no borradores),
    # siempre empujando a agendar una reunión. Default OFF por seguridad.
    inbox_auto_send: bool = False
    # Link de agenda (Calendly / Cal.com) que se ofrece en cada respuesta para cerrar
    # la reunión sin ida y vuelta. Si está vacío, el agente propone horarios concretos.
    booking_url: str = ""

    # ── Web Optimizer (mejora la landing y deploya preview en Vercel) ──
    # El agente mejora el sitio (CRO/SEO/diseño) y crea un deploy PREVIEW en
    # Vercel para que apruebes antes de prod. Default OFF.
    vercel_token: str = ""               # token de Vercel (deploy via CLI/API)
    vercel_team_id: str = ""             # team/org id (scope) en Vercel
    vercel_project: str = ""             # nombre o ID del proyecto en Vercel
    # Si =True el agente promueve a PRODUCCIÓN solo; default False = sólo preview + aviso.
    web_auto_deploy: bool = False

    # ── Outbound (cold-email automático a los leads) ──
    # ⚠️ Si auto_send=True, el agente outbound ENVÍA cold-emails reales (no borradores).
    # Dedup por email (sent-log en el volume) + tope diario. Default OFF por seguridad.
    outbound_auto_send: bool = False
    outbound_daily_cap: int = 10         # máximo de emails nuevos por corrida
    outbound_from_name: str = "Equipo Automiq"
    outbound_from_email: str = ""        # alias "send as" verificado en Gmail (ej: hola@automiq.agency)
    discord_agencia_webhook_url: str = ""  # webhook del canal #agencia (leads de la web)

    # ── TikTok (Content Posting API + Login Kit) ──
    # App "Automiq Publisher" (developers.tiktok.com). Postea contenido de video
    # PROPIO a la cuenta oficial de la marca. Credenciales en env de Railway.
    tiktok_client_key: str = ""
    tiktok_client_secret: str = ""
    tiktok_redirect_uri: str = ""        # default = public_base_url + /auth/tiktok/callback
    tiktok_scopes: str = "user.info.basic,video.publish,video.upload"
    # Sandbox hasta que TikTok apruebe la app (en sandbox sólo postea a la cuenta
    # autorizada y como privado). Pasar a False recién con la app aprobada.
    tiktok_sandbox: bool = True
    # mp4 de prueba en un dominio VERIFICADO (la landing) para el demo de review.
    tiktok_test_video_url: str = ""

    # ── LinkedIn (Share on LinkedIn + OpenID Connect) ──
    # App en developers.linkedin.com: publica posts (texto+imagen) en el perfil
    # conectado. Credenciales SOLO en env de Railway (defaults vacíos).
    linkedin_client_id: str = ""
    linkedin_client_secret: str = ""

    # ── Google Veo (generación de video, créditos GCP via Vertex AI) ──
    # La org bloquea API keys (política de seguridad) → usamos Vertex AI con
    # service account (ADC). Los US$300 de GCP se descuentan directo. Veo 3
    # image-to-video: anima la foto de Nazareno → clip 9:16 ~8s.
    # GOOGLE_SERVICE_ACCOUNT_JSON = el JSON completo de la SA (rol Vertex AI User).
    google_service_account_json: str = ""
    vertex_project: str = ""          # default = project_id del JSON de la SA
    vertex_location: str = "us-central1"
    veo_model: str = "veo-3.1-fast-generate-001"  # Veo 3.1 Fast GA (sin allowlist). Full: "veo-3.1-generate-001"
    google_api_key: str = ""          # legacy/fallback (org bloquea keys → normalmente vacío)

    # ── NVIDIA (backend LLM alternativo: GLM 5.2 / DeepSeek V4 Pro) ──
    # Endpoint gratuito OpenAI-compatible. Ciertos agentes lo usan como backend
    # (bake-off 2026-07-04: mejor calidad que MiniMax-M3 en copy/razonamiento).
    # Si la key está vacía, el flag llm_provider de los agentes se ignora → MiniMax.
    nvidia_api_key: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"

    # ── TrendsMCP (tendencias de contenido: Google/YouTube/TikTok/Reddit) ──
    trends_api_key: str = ""
    trends_mcp_url: str = "https://api.trendsmcp.ai/mcp"

    # ── Meta Ad Library API (creativos reales de competidores) ──
    # Token de USUARIO con confirmación de identidad (facebook.com/ads/library/api).
    # El system-user token de publicación NO sirve para esta API.
    meta_ad_library_token: str = ""
    glm_model: str = "z-ai/glm-5.2"
    deepseek_model: str = "deepseek-ai/deepseek-v4-pro"
    # OpenCode: harness headless (tools + skills de .claude/skills) sobre los
    # modelos NVIDIA. Kill-switch: OPENCODE_ENABLED=false → NVIDIA directo.
    opencode_enabled: bool = True
    # Hermes (hermes-agent, Nous Research): harness PRINCIPAL de todos los
    # agentes desde 2026-07-14. Kill-switch: HERMES_ENABLED=false → cadena vieja.
    hermes_enabled: bool = True

    # ── YouTube (Data API v3 — subir Shorts del canal de Nazareno) ──
    # Reusa la credencial OAuth de Google re-autorizada con scope youtube.upload.
    # youtube_oauth_json = opcional, credencial dedicada (si no, usa google_service_account_json).
    youtube_oauth_json: str = ""
    youtube_privacy: str = "private"   # privado hasta auditar el proyecto; luego "public"
    youtube_autoupload: bool = False   # que tiktok_creator suba el short armado solo

    @field_validator("minimax_api_key", "discord_webhook_url", "webhook_secret", mode="before")
    @classmethod
    def _empty_string_to_default(cls, v):
        """Si las vars tienen placeholders de .env.example, tratarlas como vacías."""
        if v in (None, "", "***", "REEMPLAZAR", "REEMPL...n"):
            return ""
        return v

    @property
    def minimax_fallbacks_list(self) -> List[str]:
        return [m.strip() for m in self.minimax_model_fallbacks.split(",") if m.strip()]

    @property
    def is_production(self) -> bool:
        return bool(self.render_service_id)

    @property
    def gmail_configured(self) -> bool:
        return bool(self.gmail_client_id and self.gmail_client_secret and self.gmail_refresh_token)

    @property
    def web_optimizer_configured(self) -> bool:
        """Mínimo para que el web_optimizer trabaje (modo CLI): token + proyecto Vercel."""
        return bool(self.vercel_token and self.vercel_project)

    @property
    def db_configured(self) -> bool:
        return bool(self.database_url)

    @property
    def tiktok_configured(self) -> bool:
        return bool(self.tiktok_client_key and self.tiktok_client_secret)

    @property
    def veo_configured(self) -> bool:
        return bool(self.google_service_account_json or self.google_api_key)

    @property
    def tiktok_redirect_uri_effective(self) -> str:
        if self.tiktok_redirect_uri:
            return self.tiktok_redirect_uri
        base = (self.public_base_url or "").rstrip("/")
        return f"{base}/auth/tiktok/callback" if base else ""

    @property
    def tiktok_scopes_list(self) -> List[str]:
        return [s.strip() for s in self.tiktok_scopes.split(",") if s.strip()]

    @property
    def discord_agent_webhooks_map(self) -> dict:
        """Parsea DISCORD_AGENT_WEBHOOKS (JSON) a dict. Tolerante a errores."""
        import json
        if not self.discord_agent_webhooks:
            return {}
        try:
            data = json.loads(self.discord_agent_webhooks)
            return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
        except (ValueError, TypeError):
            return {}

    def discord_webhook_for(self, agent_name: str) -> str:
        """URL del webhook del agente (su canal) o el general como fallback."""
        return self.discord_agent_webhooks_map.get(agent_name) or self.discord_webhook_url

    @property
    def discord_configured(self) -> bool:
        return bool(self.discord_webhook_url or self.discord_agent_webhooks_map or self.discord_webhook_errors)


@lru_cache
def get_settings() -> Settings:
    return Settings()
