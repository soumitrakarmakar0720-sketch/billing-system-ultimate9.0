# Ultimate 9.0 — Stage 9.1
Admin-only command center and customer invoice lookup. No schema changes. Existing payment code and terminal scripts are unchanged. Terminal registry indicates access, not connectivity. Stock values are existing fields, not a stock ledger. Customer lookup is invoice-based, not a unified customer identity.

Deploy to a staging Render service using the existing start command and a separate test database (copy schema and sanitized data). Preserve production environment variables on eventual production rollout; do not apply render.yaml defaults over production settings. No new variables or migrations for this stage.

Checks performed: Python AST and Jinja syntax, ZIP integrity. Runtime dependencies unavailable in build environment; no runtime or live gateway tests performed.

Acceptance: admin sees command center and customer search; staff gets 403 on both admin URLs; compare totals to existing orders; verify terminal dispatch and modal, signed webhook, EMI and foreclosure, Trash restore in staging before promotion.

Remaining stages: live terminal monitoring, branches and staff scope, customer identity profiles, inventory ledger and cash shifts, settlement reconciliation, notifications, PWA, AI analytics. These are not implemented in this stage.
