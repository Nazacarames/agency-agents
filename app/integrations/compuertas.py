"""
compuertas — un humano tiene que decir que sí antes de que esto salga al mundo.

Por qué existe: la pausa de un agente se puso como bandera en UN camino y se
escaparon cuatro mensajes por los otros cinco. Una bandera por camino no se
sostiene; la compuerta va en el cuello de botella por donde pasa TODO lo que
sale (el mail que se manda, el post que se publica), así que apagar es apagar.

Qué hace y qué NO hace:
  • FRENA la acción y la deja anotada en la bitácora como `esperando_ok`.
  • NO suspende la corrida para retomarla después. Eso es justamente la parte
    que Buzz tiene a medio hacer (su executor no persiste el token de aprobación
    y el run falla). Acá no hace falta: los agentes corren todos los días y
    reintentan solos, así que la aprobación se pega al par (tipo, destino) y el
    próximo intento pasa derecho.

Se prende con `APPROVAL_GATES` (CSV). Vacío = ninguna compuerta, que es el
comportamiento de siempre.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..config import get_settings
from ..log import get_logger
from . import eventos

log = get_logger("compuertas")

# Para qué tipos la aprobación se RECUERDA por destino. Un mail va a una persona:
# aprobar "sí, podés hablar con este lead" y que los siguientes toques a ese mismo
# lead pasen solos tiene sentido. Un post no va dirigido a nadie — si "instagram"
# quedara aprobado, la primera aprobación abriría la red para siempre y la
# compuerta serviría exactamente una vez.
RECUERDA_DESTINO = {"mail"}


class Frenado(Exception):
    """La acción no salió: está esperando el OK de un humano.

    Es una excepción y no un `return ""` a propósito: los que mandan mail guardan
    el message id que les devuelve el cliente, y un id vacío se registraría como
    un envío exitoso que nunca ocurrió."""

    def __init__(self, tipo: str, destino: str, evento_id: Optional[int]):
        self.tipo, self.destino, self.evento_id = tipo, destino, evento_id
        super().__init__(
            f"frenado por compuerta: {tipo} → {destino or 'sin destino'} "
            f"espera aprobación (evento {evento_id})")


def activas() -> set:
    """Qué tipos de acción necesitan OK, según APPROVAL_GATES."""
    crudo = getattr(get_settings(), "approval_gates", "") or ""
    return {t.strip().lower() for t in crudo.split(",") if t.strip()}


def frena(tipo: str, destino: str, resumen: str,
          detalle: Optional[Dict[str, Any]] = None) -> None:
    """Levanta `Frenado` si esta acción necesita OK y todavía no lo tiene.

    Si no hay compuerta para `tipo`, o si el destino ya fue aprobado antes, no
    hace nada y el llamador sigue como siempre."""
    tipo = (tipo or "").lower()
    if tipo not in activas():
        return
    if tipo in RECUERDA_DESTINO and eventos.hay_aprobado(tipo, destino):
        return
    evento_id = eventos.registrar(
        tipo, resumen, destino=destino, ok=False, estado="esperando_ok",
        detalle=detalle or {})
    log.warning("compuerta_freno", tipo=tipo, destino=destino[:80], evento=evento_id)
    raise Frenado(tipo, destino, evento_id)


def pendientes(limite: int = 100) -> List[Dict[str, Any]]:
    return eventos.ultimos(limite, estado="esperando_ok")


def resolver(evento_id: int, aprobado: bool, por: str = "") -> bool:
    """Aprobar deja pasar a ese destino de acá en adelante; rechazar sólo deja el
    registro de que se dijo que no (el destino sigue frenado)."""
    ok = eventos.resolver(evento_id, "aprobado" if aprobado else "rechazado", por)
    log.info("compuerta_resuelta", evento=evento_id, aprobado=aprobado, por=por, ok=ok)
    return ok
