# OWL STORE Ultimate 3.0 — Phase 1 (staging candidate)

This is a **development build**, not an approved production deployment.

## Included
- Luxury Hybrid CSS refresh: midnight navy, champagne gold, warm ivory.
- EMI creation: choose 3/6/9/12/18/24/36 months or single payment. One parent `EMI_PLAN` order and N payable child orders; total split in integer paise, remainder assigned to final month. Monthly dates clamp to month-end.
- Admin EMI schedule and payment links. Existing Cashfree checkout and webhook continue to target the payable child order by its unique gateway order ID.
- Admin-only bill soft-delete and restore, audit records, and Trash. Paid, reported or gateway-attempted bills cannot be archived. No permanent deletion.
- Dashboard excludes parent EMI plans from revenue to avoid double counting.

## Not yet included
- The rest of the full 3.0 scope (CRM, WhatsApp, stock workflows, PWA, notifications, recurring billing, reports).
- Interest/fees, partial-payment allocation, early-settlement automation, automatic reminders, installment plan amendments, verified customer OTP access.

## Critical deployment precautions
1. Do **not** upload this directly to the production Render branch.
2. Back up Neon, create a staging database/branch and staging Render service with nonproduction Cashfree credentials.
3. Apply `migrations/001_ultimate3_emi_archive.sql` to the **staging** PostgreSQL database before starting the updated application. Flask `db.create_all()` does **not** alter existing tables.
4. Run existing tests and add integration tests for EMI rounding, dates, delete/restore, webhook idempotency and security. Check staging logs and manually verify gateway payments.
5. Only after validation, plan a production migration and deployment with rollback.

## Known limitations to resolve before production
- Customer bill lookup currently uses phone number alone; OTP verification should be added for privacy.
- Invoice PDF, export and analytics need a detailed accounting review for installment invoices and tax treatment.
- Existing manual payment reporting and gateway payment races require additional concurrency tests.
- A bill with no recorded gateway attempt could still have an external payment pending; operational review is required before deletion.
- The environment used to prepare this archive did not have Flask or internet package access, so automated tests could not run here. Python compilation passed.
