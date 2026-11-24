-- Run after 001_ultimate3_emi_archive.sql; back up and test on a Neon branch first.
BEGIN;
CREATE TABLE IF NOT EXISTS emi_foreclosure (
 id SERIAL PRIMARY KEY,
 parent_order_id INTEGER NOT NULL REFERENCES "order"(id),
 gateway_order_id VARCHAR(90) NOT NULL UNIQUE,
 amount NUMERIC(12,2) NOT NULL,
 status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
 payment_ref VARCHAR(120),
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_emi_foreclosure_parent_order_id ON emi_foreclosure(parent_order_id);
COMMIT;
