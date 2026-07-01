"""
legal — páginas públicas de compliance para la auditoría de la YouTube Data API.

Sirve /privacy, /terms y /youtube (página informativa con branding de YouTube +
enlace a la política) desde el backend. Incluye las cláusulas que YouTube exige:
enlace a los Términos de YouTube, a la Política de Privacidad de Google, y la
política de acceso/retención/borrado de datos.
"""
from __future__ import annotations

_CSS = """
<style>
  :root{--bg:#0b1220;--card:#111a2e;--tx:#e8eefc;--mut:#9fb0d0;--ac:#22d3ee;--ln:rgba(255,255,255,.08)}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--tx);font:16px/1.7 -apple-system,Segoe UI,Roboto,system-ui,sans-serif}
  .wrap{max-width:820px;margin:0 auto;padding:48px 22px 80px}
  header{display:flex;align-items:center;gap:12px;border-bottom:1px solid var(--ln);padding-bottom:18px;margin-bottom:28px}
  .logo{font-weight:800;letter-spacing:.5px}
  .logo b{color:var(--ac)}
  h1{font-size:28px;margin:.2em 0}
  h2{font-size:19px;margin:1.6em 0 .5em;color:#fff}
  a{color:var(--ac)}
  .mut{color:var(--mut)}
  .yt{display:inline-flex;align-items:center;gap:8px;background:#0f1830;border:1px solid var(--ln);
      border-radius:10px;padding:10px 14px;margin:8px 0}
  .yt svg{width:26px;height:auto}
  .card{background:var(--card);border:1px solid var(--ln);border-radius:14px;padding:22px 24px;margin:18px 0}
  footer{margin-top:40px;color:var(--mut);font-size:13px;border-top:1px solid var(--ln);padding-top:18px}
  ul{padding-left:20px}
</style>
"""

_YT_BADGE = """
<div class="yt">
  <svg viewBox="0 0 90 20" xmlns="http://www.w3.org/2000/svg" aria-label="YouTube">
    <rect x="0" y="1" width="28" height="18" rx="5" fill="#FF0000"/>
    <polygon points="11,6 11,14 18,10" fill="#fff"/>
    <text x="34" y="14" fill="#fff" font-family="Arial,Helvetica,sans-serif" font-size="12" font-weight="700">YouTube</text>
  </svg>
  <span class="mut">Esta aplicación usa los servicios de la API de YouTube.</span>
</div>
"""


def _page(title: str, body: str) -> str:
    return (f"<!doctype html><html lang='es'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{title} · Automiq</title>{_CSS}</head><body><div class='wrap'>"
            f"<header><span class='logo'>Autom<b>iq</b></span>"
            f"<span class='mut'>· Automiq Publisher</span></header>{body}"
            f"<footer>Automiq · Contacto: <a href='mailto:automiqaiagency@gmail.com'>"
            f"automiqaiagency@gmail.com</a></footer></div></body></html>")


def info_html() -> str:
    body = f"""
    <h1>Automiq Publisher</h1>
    <p class="mut">Herramienta interna de Automiq para publicar nuestro propio contenido de video
    corto en nuestro canal oficial de YouTube.</p>
    {_YT_BADGE}
    <div class="card">
      <h2>Qué hace</h2>
      <p>Automiq Publisher sube automáticamente los videos de marketing <b>propios</b> de Automiq a
      <b>nuestro propio canal</b> de YouTube ("Automiq · Nazareno") mediante <code>videos.insert</code>,
      y usa <code>channels.list</code> (mine=true) solo para confirmar el canal conectado. No accede a
      datos de terceros ni de otros usuarios.</p>
      <h2>Enlaces legales</h2>
      <ul>
        <li><a href="/privacy">Política de Privacidad</a></li>
        <li><a href="/terms">Términos del Servicio</a></li>
        <li><a href="https://www.youtube.com/t/terms" target="_blank" rel="noopener">Términos del Servicio de YouTube</a></li>
        <li><a href="https://policies.google.com/privacy" target="_blank" rel="noopener">Política de Privacidad de Google</a></li>
      </ul>
    </div>
    """
    return _page("Automiq Publisher", body)


def privacy_html() -> str:
    body = f"""
    <h1>Política de Privacidad</h1>
    <p class="mut">Última actualización: julio 2026. Aplica a la herramienta interna <b>Automiq Publisher</b>.</p>
    {_YT_BADGE}
    <div class="card">
      <h2>1. Uso de los servicios de la API de YouTube</h2>
      <p>Automiq Publisher utiliza los <b>Servicios de la API de YouTube</b> para publicar videos en el
      canal de YouTube propiedad de Automiq. Al usar esta herramienta, también aceptás los
      <a href="https://www.youtube.com/t/terms" target="_blank" rel="noopener">Términos del Servicio de YouTube</a>.
      El tratamiento de datos por parte de Google se rige por la
      <a href="https://policies.google.com/privacy" target="_blank" rel="noopener">Política de Privacidad de Google</a>.</p>

      <h2>2. Qué datos accedemos</h2>
      <ul>
        <li><b>Subida de videos</b> (<code>youtube.upload</code>): subimos videos creados por Automiq a nuestro propio canal.</li>
        <li><b>Lectura del canal propio</b> (<code>youtube.readonly</code>, <code>channels.list</code> mine=true):
        solo para confirmar que la herramienta está conectada a nuestro canal.</li>
      </ul>
      <p>No accedemos, recopilamos ni procesamos datos de otros usuarios o canales. Es una herramienta
      de uso exclusivamente interno de Automiq.</p>

      <h2>3. Qué datos almacenamos</h2>
      <p>Solo guardamos el identificador (ID) de los videos que <b>nosotros mismos</b> subimos, para
      referencia interna. No almacenamos datos personales de terceros ni información de la audiencia.</p>

      <h2>4. Retención y borrado de datos</h2>
      <p>Los tokens de autorización se conservan solo mientras la herramienta está en uso. Podés revocar
      el acceso en cualquier momento desde
      <a href="https://myaccount.google.com/permissions" target="_blank" rel="noopener">myaccount.google.com/permissions</a>,
      lo que elimina nuestra capacidad de acceder a la cuenta. Para solicitar la eliminación de cualquier
      dato asociado, escribinos a automiqaiagency@gmail.com y lo borramos.</p>

      <h2>5. Compartir datos</h2>
      <p>No vendemos ni compartimos datos con terceros. Los datos obtenidos vía la API de YouTube no se
      usan para publicidad ni se transfieren fuera de la herramienta.</p>

      <h2>6. Contacto</h2>
      <p>Automiq — <a href="mailto:automiqaiagency@gmail.com">automiqaiagency@gmail.com</a></p>
    </div>
    """
    return _page("Política de Privacidad", body)


def terms_html() -> str:
    body = f"""
    <h1>Términos del Servicio</h1>
    <p class="mut">Última actualización: julio 2026.</p>
    {_YT_BADGE}
    <div class="card">
      <h2>1. Descripción</h2>
      <p>Automiq Publisher es una herramienta interna de Automiq para publicar contenido de video propio
      en el canal de YouTube de la marca. No es un producto público ni se ofrece a terceros.</p>
      <h2>2. Uso aceptable</h2>
      <p>La herramienta se usa exclusivamente para subir contenido del que Automiq es titular, cumpliendo
      los <a href="https://www.youtube.com/t/terms" target="_blank" rel="noopener">Términos de YouTube</a>
      y las políticas de la comunidad.</p>
      <h2>3. Privacidad</h2>
      <p>El uso de datos se detalla en nuestra <a href="/privacy">Política de Privacidad</a>.</p>
      <h2>4. Contacto</h2>
      <p>Automiq — <a href="mailto:automiqaiagency@gmail.com">automiqaiagency@gmail.com</a></p>
    </div>
    """
    return _page("Términos del Servicio", body)
