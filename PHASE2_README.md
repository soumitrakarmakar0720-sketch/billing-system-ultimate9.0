# OWL STORE Pay Terminal Phase 2 (STAGING ONLY)

- Apply `migrations/004_terminal_transactions.sql` to a **staging** Neon branch, after Phase 1 migration.
- Keep existing Cashfree keys, `SECRET_KEY`, and webhook endpoint settings unchanged.
- `/terminal` staff login -> `/terminal/dashboard` -> `/terminal/new-bill` -> waiting screen.
- Customer-phone mode: share the existing `/pay/<token>` bill page; customer clicks Cashfree.
- Same-device mode: open the bill page in a separate tab and click Cashfree.
- Status polling is authenticated and scoped to the creating staff account; it displays server-recorded payment status only.
- The existing signed Cashfree webhook is unchanged and remains the source of gateway payment confirmation.
- Receipts are available only after `PAID` status; receipt PDF uses the existing invoice renderer.
- No Cashfree API secrets are sent to the browser. No new payment APIs or public order lookup endpoints.

## Staging checklist
1. Log in with a valid terminal code; verify invalid/revoked code behavior.
2. Create a bill for a valid 10-digit customer phone and active product.
3. Test customer-phone and same-device checkout in Cashfree sandbox.
4. Confirm waiting screen remains pending until a **signed webhook** is processed.
5. Confirm successful webhook results in PAID and PDF receipt.
6. Verify a different staff session cannot view another staff member's order/status/receipt.
7. Test browser logout, network failures, duplicate webhook, and ordinary admin billing/EMI flows.

IMPORTANT: This is not production-verified. Do not deploy to live `owldigital.shop` until the above checks pass.
