-- ─────────────────────────────────────────────────────────────────────────────
-- Migración 003 — Nuevas etapas de cliente (funnel de la agencia)
-- Etapas: oferta → reunión → negociación → cliente → descartado (terminal/congelada)
-- Migra las etapas viejas (prospecto/contactado/propuesta/perdido) a las nuevas.
-- Idempotente.
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE agency.clients ALTER COLUMN stage SET DEFAULT 'oferta';

UPDATE agency.clients SET stage = 'oferta'      WHERE stage IN ('prospecto', 'contactado');
UPDATE agency.clients SET stage = 'negociación' WHERE stage = 'propuesta';
UPDATE agency.clients SET stage = 'descartado'  WHERE stage = 'perdido';
-- 'reunión', 'cliente' y los ya nuevos quedan igual.
