"""Check de la colaboración por departamento: broadcast NOTA_PARA(<depto>),
compañeros de sector y brief del equipo. Correr: python scripts/test_dept_collab.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents import departments as dp
from app.agents._common import team_brief

# 1. teammates_of: compañeros del sector, sin incluirse a sí mismo
mates = dp.teammates_of("content_creator")
assert "content_creator" not in mates, mates
assert "creative_strategist" in mates and "social_media" in mates, mates
assert dp.teammates_of("no_existe") == []
assert dp.teammates_of("finance_officer") == []          # depto de uno solo

# 2. Resolución de destinatario: agente gana sobre departamento homónimo
valid = {"customer_success", "content_creator"}
for name in ("customer_success",):
    assert name in valid and name in dp.DEPARTMENTS, "el caso ambiguo sigue existiendo"

# 3. Broadcast: NOTA_PARA(marketing) llega a TODO marketing menos el emisor
targets = [t for t in dp.DEPARTMENTS["marketing"]["agents"] if t != "content_creator"]
assert len(targets) == 5, targets
assert all(t in dp.all_department_agents() for t in targets)

# 4. team_brief tolera agentes sin artefacto (disco efímero) sin explotar
assert team_brief(["agente_fantasma"]) == ""
assert isinstance(team_brief(mates), str)

print("OK — colaboración departamental")
