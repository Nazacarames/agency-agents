"""Check del corte por llamada de Hermes (2026-08-02): el tier gratis de NVIDIA
lleva timeout corto por request para que el reintento de Hermes entre entero;
MiniMax queda intacto. Correr:
    python scripts/test_hermes_timeout.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.clients import hermes
from app.config import Settings

s = Settings(webhook_secret="x", minimax_api_key="mm", nvidia_api_key="nv")

capturado = {}


def _fake_killtree(cmd, *, cwd, env, stdout_file, stderr_file, timeout):
    capturado["env"] = dict(env)
    stdout_file.write(b"entregable")
    return 0


hermes.run_cli_killtree = _fake_killtree
hermes.hermes_available = lambda: True

# 1. NVIDIA (deepseek/glm): corte por llamada de 60s en AMBAS variables.
#    El total (1800s por default) es el que dejaba el request colgado media hora;
#    el de lectura (120s por default) hacía arrancar el reintento recién a los
#    ~120s, o sea DESPUÉS de la mitad del presupuesto viejo de 180s.
for prov in ("deepseek", "glm"):
    hermes.run_hermes("hola", settings=s, llm_provider=prov, timeout=420)
    env = capturado["env"]
    assert env["HERMES_API_TIMEOUT"] == "60", (prov, env.get("HERMES_API_TIMEOUT"))
    assert env["HERMES_STREAM_READ_TIMEOUT"] == "60", prov

# 2. MiniMax: NO se toca (es más lento por llamada y nunca mostró el cuelgue).
hermes.run_hermes("hola", settings=s, llm_provider="", timeout=600)
env = capturado["env"]
assert "HERMES_API_TIMEOUT" not in env, env.get("HERMES_API_TIMEOUT")
assert "HERMES_STREAM_READ_TIMEOUT" not in env

# 3. El respaldo de proceso tiene que dejar entrar los 3 intentos (3x60=180s)
#    del peor turno MÁS una corrida sana (90s). Si alguien lo vuelve a bajar,
#    esto falla en vez de descubrirse en prod.
from app.agents.base import BaseAgent   # noqa: E402

fuente = Path(hermes.__file__).parent.parent / "agents" / "base.py"
linea = [l for l in fuente.read_text(encoding="utf-8").splitlines()
         if "p_timeout =" in l][0]
respaldo = int(linea.split("=")[1].split("if")[0].strip())
assert respaldo >= 3 * 60 + 90, f"respaldo {respaldo}s corta reintentos"
assert respaldo < BaseAgent.claude_code_timeout, "tiene que seguir siendo fail-fast vs MiniMax"

# 4. Que nada del config.yaml de Hermes pise las env vars (los defaults de
#    `providers.<id>` ganan por encima). Si algún día se escribe un
#    request_timeout_seconds ahí, este check avisa. Solo donde esté instalado.
try:
    from hermes_cli.timeouts import get_provider_request_timeout
except ImportError:
    print("   (hermes_cli no instalado — salteado el check de config.yaml)")
else:
    assert get_provider_request_timeout("nvidia", s.deepseek_model) is None, \
        "hay un request_timeout_seconds en config.yaml que pisa la env var"

print("OK — corte por llamada NVIDIA 60s, MiniMax intacto, respaldo 420s")
