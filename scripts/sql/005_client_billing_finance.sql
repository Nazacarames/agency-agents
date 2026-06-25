-- 005 — Facturación por cliente (lo que paga, servicios, estado de la relación).
-- Las finanzas (gastos), tasas FX y métricas viven en JSON en el volume, no en DB.
-- Correr con DATABASE_URL apuntando a Supabase (schema `agency`), igual que 004.
-- Ej: psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f scripts/sql/005_client_billing_finance.sql

SET search_path TO agency, public;

ALTER TABLE agency.clients ADD COLUMN IF NOT EXISTS currency     TEXT    NOT NULL DEFAULT '';
ALTER TABLE agency.clients ADD COLUMN IF NOT EXISTS monthly_fee  NUMERIC NOT NULL DEFAULT 0;
ALTER TABLE agency.clients ADD COLUMN IF NOT EXISTS services     TEXT    NOT NULL DEFAULT '';
ALTER TABLE agency.clients ADD COLUMN IF NOT EXISTS status       TEXT    NOT NULL DEFAULT 'activo';
ALTER TABLE agency.clients ADD COLUMN IF NOT EXISTS start_date   DATE;

-- Los clientes ya cargados quedan como 'activo' por default; ajustá desde el panel.
