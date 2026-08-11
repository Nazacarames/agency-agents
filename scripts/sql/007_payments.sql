-- 007 — Libro de pagos: plata que ENTRÓ de verdad.
-- Hasta ahora el "facturado del año" se devengaba de la ficha del cliente
-- (alta + fee), así que servía para estimar pero no para conciliar con el banco,
-- y un cliente dado de baja hacía bajar el histórico retroactivamente.
-- Correr con DATABASE_URL apuntando a Supabase (schema `agency`), igual que 006.
-- Ej: psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f scripts/sql/007_payments.sql

SET search_path TO agency, public;

CREATE TABLE IF NOT EXISTS agency.payments (
    id          TEXT PRIMARY KEY,
    client_id   TEXT NOT NULL REFERENCES agency.clients(id) ON DELETE CASCADE,
    fecha       DATE NOT NULL,
    concepto    TEXT NOT NULL DEFAULT 'mensual',   -- unico | mensual | otro
    amount      NUMERIC NOT NULL DEFAULT 0,
    currency    TEXT NOT NULL DEFAULT 'USD',
    -- USD CONGELADO al día del cobro. No se recalcula: si un pago en ARS se
    -- revaluara con el dólar de hoy, el histórico cambiaría solo cada vez que se
    -- mueve el FX y no cerraría nunca contra el banco.
    amount_usd  NUMERIC NOT NULL DEFAULT 0,
    periodo     TEXT,                              -- YYYY-MM que cubre (mensual)
    metodo      TEXT NOT NULL DEFAULT '',          -- transferencia, USDT, efectivo…
    notes       TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS payments_client_idx ON agency.payments (client_id);
CREATE INDEX IF NOT EXISTS payments_fecha_idx  ON agency.payments (fecha);

-- Un cobro mensual por cliente y período: evita cargar dos veces el mismo mes.
-- Parcial porque `periodo` es NULL en los pagos únicos y en 'otro'.
CREATE UNIQUE INDEX IF NOT EXISTS payments_mes_unico
    ON agency.payments (client_id, periodo)
    WHERE concepto = 'mensual' AND periodo IS NOT NULL;

COMMENT ON TABLE agency.payments IS
  'Pagos efectivamente cobrados. amount_usd va congelado al FX del día del cobro.';
