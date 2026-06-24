-- ─────────────────────────────────────────────────────────────────────────────
-- Migración 004 — CEO planner + clientes multi-país (hispanohablante)
--  · agency.missions.plan: el plan descompuesto del CEO (sub-tarea por agente)
--  · agency.clients.country: país del cliente (ISO-2). Default 'AR' (retro-compat).
-- Idempotente.
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE agency.missions ADD COLUMN IF NOT EXISTS plan JSONB DEFAULT '[]'::jsonb;

ALTER TABLE agency.clients  ADD COLUMN IF NOT EXISTS country TEXT NOT NULL DEFAULT 'AR';

-- Los clientes existentes (sin país) quedan en Argentina por defecto.
UPDATE agency.clients SET country = 'AR' WHERE country IS NULL OR country = '';
