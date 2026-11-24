-- Run AFTER migrations/003_terminal_access.sql. Back up Neon before applying.
CREATE TABLE IF NOT EXISTS terminal_transaction (
    id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL UNIQUE REFERENCES "order"(id),
    user_id INTEGER NOT NULL REFERENCES "user"(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_terminal_transaction_user_id ON terminal_transaction(user_id);
