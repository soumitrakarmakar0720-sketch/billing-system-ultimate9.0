-- BACK UP Neon before running. Execute once against the production PostgreSQL database.
-- This migration adds only nullable columns to the existing order table.
BEGIN;
ALTER TABLE "order" ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
ALTER TABLE "order" ADD COLUMN IF NOT EXISTS deleted_by VARCHAR(100);
ALTER TABLE "order" ADD COLUMN IF NOT EXISTS parent_order_id INTEGER REFERENCES "order"(id);
ALTER TABLE "order" ADD COLUMN IF NOT EXISTS installment_number INTEGER;
ALTER TABLE "order" ADD COLUMN IF NOT EXISTS due_date DATE;
ALTER TABLE "order" ADD COLUMN IF NOT EXISTS emi_months INTEGER;
CREATE INDEX IF NOT EXISTS ix_order_parent_order_id ON "order"(parent_order_id);
COMMIT;
