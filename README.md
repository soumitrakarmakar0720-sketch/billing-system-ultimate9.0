# OWL STORE Ultimate — full standalone upgrade project

**This is a new application version, not a drop-in replacement for your old `app.py`.** Do NOT overwrite the live Render service or point this application at the old SQLite file. It uses a new SQLAlchemy schema. Rehearse the migration on a staging service first.

## Architecture

- Flask web app + server-rendered responsive templates
- SQLAlchemy ORM → PostgreSQL on Render, SQLite for local development
- Admin and staff sessions; only admin can confirm/reject payments, manage staff and export records
- CSRF-protected forms, hashed passwords, secure cookies, unpredictable customer checkout tokens
- Product catalog → bill creation → customer UPI QR or Cashfree-hosted checkout → payment verification → invoice
- Manual UPI reports require bank verification; **only** a verified Cashfree webhook or explicit admin action sets `PAID`
- Payment audit trail, CSV export, PDF invoice, staff accounts, customer checkout portal

## Local setup

```bash
python -m venv .venv
# activate your environment (Windows: .venv\\Scripts\\activate)
pip install -r requirements.txt
# copy .env.example values to your environment (Flask does not automatically load .env here)
export SECRET_KEY="$(python -c 'import secrets;print(secrets.token_hex(32))')"
export COOKIE_SECURE=0
export ADMIN_USERNAME=admin
export ADMIN_PASSWORD='choose-a-strong-unique-password'
flask --app app init-db
flask --app app create-admin
flask --app app run
```

On Windows PowerShell, use `$env:SECRET_KEY='...'` and similar `$env:` assignments.

## Safe Render deployment (do not modify production yet)

1. Back up the current repository, Render environment variable names, current service settings, and the **existing SQLite DB file**. If SQLite is on Render ephemeral storage, capture it **before redeploying**. Render free services do not provide persistent disk; use PostgreSQL for production.
2. Create a **new GitHub branch or separate staging repository** for this folder. Create a **new staging Render web service** with `pip install -r requirements.txt` and `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --threads 4`. Do not use the production service's database.
3. Provision PostgreSQL on Render and set `DATABASE_URL` to its **internal** database URL; set `SECRET_KEY` to a long random value; set `COOKIE_SECURE=1`; set `UPI_ID`, `UPI_NAME`, `ADMIN_USERNAME`, and `ADMIN_PASSWORD` in Render Environment. Never commit secrets.
4. Run **once**, via a Render shell or a one-off job using the same `DATABASE_URL`: `flask --app app init-db` then `flask --app app create-admin`. The app intentionally does not create schema at import time or silently reset passwords.
5. Test login, products, create bill, customer QR, UTR report, reject, confirm, staff restrictions, PDF, CSV and audit. Keep `CASHFREE_ENV=sandbox` until production account activation.
6. Optional existing-data migration: first back up your old SQLite database; run `LEGACY_SQLITE=/path/old.db python scripts/import_legacy.py` for dry run, then `... --apply` against an **empty** staging Ultimate DB. Existing orders receive new private customer tokens; old public checkout URLs change. Migration should be rehearsed and audited before cutover.
7. For Cashfree, obtain credentials from your merchant account, configure Cashfree webhook URL `https://YOUR-STAGING-HOST/webhooks/cashfree`, subscribe to the payment-success event, and test a successful and failed sandbox payment. Cashfree's production activation, webhook event schema and SDK compatibility must be validated against your merchant account before going live.
8. Cut over with a maintenance window: stop accepting new orders on the old service, take a final consistent backup, import the delta or reimport into a fresh Ultimate DB, reconcile order totals and payment statuses, then deploy this branch to production or switch domain routing. Retain the old service and DB for rollback until reconciled.
9. To roll back, route traffic to the previous service and **its original DB snapshot**. Do not switch back to the old code against the new schema.

## Environment variables

| Variable | Description |
| --- | --- |
| `SECRET_KEY` | Required, 32+ random bytes equivalent |
| `DATABASE_URL` | PostgreSQL URL on Render; local defaults to SQLite |
| `COOKIE_SECURE` | `1` in HTTPS production, `0` for local HTTP |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | Used only by one-time `create-admin` CLI command |
| `UPI_ID`, `UPI_NAME` | Merchant UPI destination/name |
| `CASHFREE_ENV` | `sandbox` or `production` |
| `CASHFREE_CLIENT_ID`, `CASHFREE_CLIENT_SECRET` | Optional; enables Cashfree checkout |

## Important production hardening before full-scale commercial use

- Cashfree verification: webhook HMAC uses the raw request body and timestamp; confirm current signature format and payload against Cashfree documentation, and add a server-side gateway order/payment reconciliation job before production activation. Never mark `PAID` from browser return alone.
- This starter does not implement GST-compliant invoice fields, refunds, inventory deduction, WhatsApp delivery, email verification, password reset, multi-tenant permissions, or automated reconciliation. Add these in later phases, with tests and any required regulatory review.
- Add reverse-proxy request rate limiting, login lockout, structured logging, monitoring, database backups, and migration tooling (Alembic) before processing significant volume.
- Protect access to checkout tokens; anyone with a valid link can see customer/order information. Don't publish tokenized URLs in public places.
- Manual approval must be done **only after bank credit is independently verified**; customer-entered UTR is not proof of payment.
- The QR and Cashfree methods are alternatives. Prevent double payment operationally by checking transaction status before manually approving. A production system should add reconciliation and refund workflows.

## Quick checks

`python -m compileall app.py scripts` and `python -m unittest discover -s tests`.

## Verification status of this ZIP

Python syntax compilation completed successfully. Automated runtime tests were **not run** in the packaging environment because the required Flask dependencies could not be installed there (network package index unavailable). Run dependency installation and the test suite in your local environment or staging CI before deploying. This is a substantial working starter with production-oriented patterns, **not** a certified or audited payment processing product.
