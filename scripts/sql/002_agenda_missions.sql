-- ─────────────────────────────────────────────────────────────────────────────
-- Migración 002 — Agenda de reuniones + Misiones del CEO (Fases CEO + meeting-prep)
-- Todo bajo el schema `agency`. Idempotente.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE SCHEMA IF NOT EXISTS agency;

-- ── Agenda de reuniones (el operador agenda: cliente + día + hora) ──
CREATE TABLE IF NOT EXISTS agency.meetings (
    id             BIGSERIAL PRIMARY KEY,
    client_id      TEXT REFERENCES agency.clients(id) ON DELETE SET NULL,
    client_name    TEXT DEFAULT '',                 -- snapshot por si se borra el cliente
    title          TEXT NOT NULL DEFAULT 'Reunión',
    scheduled_at   TIMESTAMPTZ NOT NULL,
    status         TEXT NOT NULL DEFAULT 'programada',  -- programada | realizada | cancelada
    location       TEXT DEFAULT '',                 -- zoom / meet / presencial / tel
    notes          TEXT DEFAULT '',
    prep_ready     BOOLEAN NOT NULL DEFAULT false,  -- ya se generó la preparación
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS meetings_when_idx ON agency.meetings (scheduled_at);
CREATE INDEX IF NOT EXISTS meetings_client_idx ON agency.meetings (client_id);

-- ── Misiones del CEO (un objetivo del operador repartido a varios agentes) ──
CREATE TABLE IF NOT EXISTS agency.missions (
    id           BIGSERIAL PRIMARY KEY,
    objective    TEXT NOT NULL,
    agents       TEXT[] NOT NULL DEFAULT '{}',
    client_id    TEXT REFERENCES agency.clients(id) ON DELETE SET NULL,
    status       TEXT NOT NULL DEFAULT 'lanzada',   -- lanzada | en_curso | completada
    run_ids      JSONB NOT NULL DEFAULT '{}',       -- {agente: run_id}
    notes        TEXT DEFAULT '',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS missions_status_idx ON agency.missions (status, created_at DESC);
