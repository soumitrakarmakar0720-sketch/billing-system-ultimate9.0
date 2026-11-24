-- Apply to a staging Neon branch after 003 and 004. Backup before production.
CREATE TABLE IF NOT EXISTS terminal_dispatch (
 id SERIAL PRIMARY KEY,
 order_id INTEGER NOT NULL REFERENCES "order"(id),
 user_id INTEGER NOT NULL REFERENCES "user"(id),
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 expires_at TIMESTAMPTZ NOT NULL,
 acknowledged_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_terminal_dispatch_order_id ON terminal_dispatch(order_id);
CREATE INDEX IF NOT EXISTS ix_terminal_dispatch_user_id ON terminal_dispatch(user_id);
CREATE INDEX IF NOT EXISTS ix_terminal_dispatch_pending ON terminal_dispatch(user_id, expires_at) WHERE acknowledged_at IS NULL;
