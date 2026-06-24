-- ─────────────────────────────────────────────────────────────────────────────
-- Migración 001 — Capa de memoria/DB de la agencia (Fase 1)
--
-- TODO vive bajo el schema dedicado `agency` para NO tocar las tablas de
-- Paperclip que comparten esta misma instancia de Supabase (public.clients, etc).
-- Idempotente: se puede correr varias veces.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE SCHEMA IF NOT EXISTS agency;

-- ── Memoria general (knowledge base) — seed desde Obsidian + contexto de empresa ──
CREATE TABLE IF NOT EXISTS agency.company_memory (
    id          BIGSERIAL PRIMARY KEY,
    section     TEXT NOT NULL DEFAULT 'general',   -- identidad | servicios | pricing | playbook | contexto | …
    title       TEXT NOT NULL,
    content     TEXT NOT NULL,
    source      TEXT DEFAULT '',                   -- p.ej. obsidian:00-Agency/Agency-MOC.md
    tags        TEXT[] DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- una entrada por (section,title) para poder hacer upsert idempotente del seed
CREATE UNIQUE INDEX IF NOT EXISTS company_memory_section_title_uq
    ON agency.company_memory (section, title);

-- ── Objetivos de growth por sector ──
CREATE TABLE IF NOT EXISTS agency.growth_objectives (
    id          BIGSERIAL PRIMARY KEY,
    sector      TEXT NOT NULL DEFAULT 'general',
    objective   TEXT NOT NULL,
    metric      TEXT DEFAULT '',
    target      TEXT DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'activo',     -- activo | pausado | logrado
    notes       TEXT DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS growth_objectives_sector_status_idx
    ON agency.growth_objectives (sector, status);

-- ── Clientes de la agencia (migra clients_store.json) ──
CREATE TABLE IF NOT EXISTS agency.clients (
    id             TEXT PRIMARY KEY,               -- hex de 12 (compatible con el dashboard actual)
    name           TEXT NOT NULL DEFAULT 'Cliente sin nombre',
    vertical       TEXT DEFAULT '',
    contact_name   TEXT DEFAULT '',
    contact_phone  TEXT DEFAULT '',
    contact_email  TEXT DEFAULT '',
    stage          TEXT NOT NULL DEFAULT 'prospecto',
    notes          TEXT DEFAULT '',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS clients_stage_idx ON agency.clients (stage);

-- ── Memoria POR CLIENTE — reports + info recaudada que escriben los agentes ──
CREATE TABLE IF NOT EXISTS agency.client_memory (
    id          BIGSERIAL PRIMARY KEY,
    client_id   TEXT NOT NULL REFERENCES agency.clients(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL DEFAULT 'note',      -- profile | report | audit | gathered | note
    agent       TEXT DEFAULT '',                   -- agente que lo generó ('' = manual/CEO)
    title       TEXT NOT NULL DEFAULT '',
    content     TEXT NOT NULL DEFAULT '',
    meta        JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS client_memory_client_idx
    ON agency.client_memory (client_id, created_at DESC);
CREATE INDEX IF NOT EXISTS client_memory_kind_idx
    ON agency.client_memory (client_id, kind);

-- ── Lecciones por agente — loop de mejora continua (Fase 2 lo llena) ──
CREATE TABLE IF NOT EXISTS agency.agent_lessons (
    id          BIGSERIAL PRIMARY KEY,
    agent       TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'feedback',  -- feedback (CEO) | outcome (resultado) | directive
    lesson      TEXT NOT NULL,
    weight      INT NOT NULL DEFAULT 1,
    active      BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS agent_lessons_agent_active_idx
    ON agency.agent_lessons (agent, active);
