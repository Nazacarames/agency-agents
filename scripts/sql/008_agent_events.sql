-- 008 — Bitácora de agentes: UNA línea de tiempo con lo que hicieron.
--
-- Hasta ahora `write_run_log` escribía en logs/agent_runs.jsonl, adentro del
-- contenedor y sin disco montado (render.yaml no declara ninguno): el archivo
-- se borra en cada deploy. Y aun si sobreviviera, guardaba tokens y latencia,
-- no ACCIONES: qué mail salió, a quién, qué se publicó y con qué link vivía
-- desparramado en 13 JSON de data/, en Discord y en el backlog. Por eso las
-- fichas que nadie cierra y el loop de aprendizaje muerto un mes aparecieron
-- recién cuando alguien se puso a escarbar.
--
-- Correr con DATABASE_URL apuntando a Supabase (schema `agency`), igual que 007:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f scripts/sql/008_agent_events.sql

SET search_path TO agency, public;

CREATE TABLE IF NOT EXISTS agency.agent_events (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    tipo        TEXT NOT NULL,                     -- run | mail | post | tiktok | linkedin
    agente      TEXT NOT NULL DEFAULT '',
    run_id      TEXT NOT NULL DEFAULT '',
    resumen     TEXT NOT NULL DEFAULT '',
    destino     TEXT NOT NULL DEFAULT '',          -- a quién / dónde salió
    ref         TEXT NOT NULL DEFAULT '',          -- id externo: message id, permalink…
    ok          BOOLEAN NOT NULL DEFAULT TRUE,
    -- hecho → ya salió al mundo. esperando_ok → frenado en una compuerta de
    -- aprobación. aprobado/rechazado → lo que decidió el humano.
    estado      TEXT NOT NULL DEFAULT 'hecho',
    detalle     JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS agent_events_ts_idx     ON agency.agent_events (ts DESC);
CREATE INDEX IF NOT EXISTS agent_events_agente_idx ON agency.agent_events (agente, ts DESC);
CREATE INDEX IF NOT EXISTS agent_events_estado_idx ON agency.agent_events (estado, ts DESC);
