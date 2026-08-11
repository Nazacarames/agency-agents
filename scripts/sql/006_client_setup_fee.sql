-- 006 — Pago único por cliente, separado de la mensualidad.
-- Hasta ahora sólo existía `monthly_fee`, así que un contrato con anticipo no
-- entraba en el modelo: CLAMEVET (US$ 3.000 único + US$ 500/mes) tenía cargado
-- el 500 y los 3.000 sueltos en `notes`, donde ningún cálculo los ve.
-- Correr con DATABASE_URL apuntando a Supabase (schema `agency`), igual que 005.
-- Ej: psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f scripts/sql/006_client_setup_fee.sql

SET search_path TO agency, public;

-- Va en la MISMA moneda que `monthly_fee` (columna `currency` del cliente): un
-- contrato no se firma mitad en una moneda y mitad en otra.
ALTER TABLE agency.clients ADD COLUMN IF NOT EXISTS setup_fee NUMERIC NOT NULL DEFAULT 0;

COMMENT ON COLUMN agency.clients.setup_fee IS
  'Pago único (anticipo/setup/implementación), en la moneda de `currency`. NO entra al MRR.';
