"""
Delivery PM — gestión de proyectos de clientes (departamento Producto/Delivery).

Trackea el trabajo real que se entrega a los clientes (ej: plataforma CLAMEVET,
CRM): en qué etapa está cada proyecto, qué está frenado, qué sigue y qué necesita
del dueño. On-demand (sin schedule). Lee clientes + misiones + tareas.
"""
from .base import BaseAgent, AgentContext
from ._common import get_context_block
from ..log import get_logger

log = get_logger("delivery_pm")

PM_INSTRUCTIONS = """
# Delivery PM — Automiq

## Quién sos
Sos el PROJECT MANAGER de entrega de Automiq. Tu foco es el TRABAJO que se le
entrega a los clientes (desarrollo de plataformas, CRM, integraciones), no la
venta ni el marketing. Convertís el estado disperso de cada proyecto en un
tablero claro de etapas, bloqueos y próximos pasos.

## Reglas de oro
1. **Por proyecto/cliente**: cada entregable tiene su etapa, su próximo hito y
   su fecha objetivo. Nada de "avanzando bien".
2. **Bloqueos primero**: lo que está frenado (esperando una credencial, una
   decisión, un pago, algo del cliente) va arriba, con quién lo destraba.
3. **Criterios verificables**: un hito es "hecho" solo si hay algo que lo
   demuestra (deploy, demo, entrega). Si no, está en curso.
4. **Riesgo de fecha**: si un proyecto se está por pasar de tiempo, decilo con
   la causa. En proyectos de precio fijo, el riesgo es nuestro.
5. **Acciones del humano** = decisiones, entregas, cosas que un agente no hace.

## Formato de salida
Un tablero en markdown:
- **Proyectos activos**: por cada uno → etapa, % o hito actual, próximo hito +
  fecha, estado (en curso / frenado / en riesgo).
- **Bloqueos**: qué frena qué, y quién lo destraba.
- **Esta semana**: los 2-3 hitos que hay que cerrar.
- **Acciones del dueño (hoy)**: 1-3 concretas.
"""


class DeliveryPMAgent(BaseAgent):
    name = "delivery_pm"
    description = "Project manager de entrega: etapas, bloqueos y próximos hitos por proyecto"
    schedule = "15 7 * * mon"  # activo: lun 07:15 (cron en scheduler.DEFAULT_SCHEDULES)
    max_tokens = 5000
    llm_provider = "deepseek"

    @property
    def system_prompt(self) -> str:
        from .departments import autonomy_note
        return f"{get_context_block()}\n\n{autonomy_note(self.name)}\n\n{PM_INSTRUCTIONS}"

    def build_user_message(self, ctx: AgentContext) -> str:
        parts = ["Armá el tablero de entrega con el estado de abajo.\n"]
        try:
            from ..integrations import clients_store as cs, client_memory_store as cms
            for c in cs.list_clients()[:15]:
                cid = c.get("id", "")
                dig = cms.context_digest(cid, max_items=8, max_chars=1800) if cid else ""
                parts.append(f"### Proyecto: {c.get('name', cid)}\n"
                             f"Estado cliente: {c.get('status', '?')}\nNotas/avances:\n"
                             f"{dig or '(sin notas)'}\n")
        except Exception as e:
            log.warning("pm_clients_failed", error=str(e)[:150])
        try:
            from ..integrations import missions_store as ms
            miss = ms.list_missions(limit=20)
            if miss:
                parts.append(f"## Misiones abiertas\n{miss}\n")
        except Exception as e:
            log.warning("pm_missions_failed", error=str(e)[:150])
        if len(parts) == 1:
            parts.append("(Sin proyectos de clientes cargados todavía — decilo y listá "
                         "como proyectos los desarrollos en curso conocidos, ej: la "
                         "plataforma CLAMEVET y el CRM, con su etapa aproximada.)")
        return "\n".join(parts)
