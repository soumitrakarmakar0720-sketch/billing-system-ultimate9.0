# Phase 5 — Dashboard waiting / terminal-only Cashfree checkout (STAGING)

## Exact behavior
- Normal-dashboard user creates a single-payment invoice. Existing `terminal_transaction` assigns it to that user.
- That same user selects **Pay online with Cashfree** on the original invoice. The existing Cashfree order is created/reused. Once Cashfree responds with a payment session, a 10-minute `terminal_dispatch` is stored and the normal-dashboard browser is redirected to a **Waiting for Payment** screen (no Cashfree SDK there).
- A terminal logged in with the **same user account** polls for its unacknowledged dispatches, navigates to the gateway route and automatically invokes Cashfree SDK checkout. A manual button is retained because browser gesture restrictions can block automatic checkout.
- The dashboard waiting page polls the original invoice's server-side status; the existing signed webhook remains the payment authority. No duplicate invoices or gateway orders.
- The staff terminal does not show My Assigned Bills or a payment-link selection page.

## Database
Apply `migrations/005_terminal_dispatch.sql` on a backed-up **staging Neon branch** after 003 and 004. No change to existing bill or payment tables.

## Known constraints / important tests
- This only redirects normal-dashboard staff sessions whose bill is assigned to the same user. Customer/public checkout continues to work as before, as do EMI installments.
- Cashfree's existing order `return_url` points to the original customer checkout; after the gateway returns, the terminal may land there. The dashboard waiting page still independently updates after verified payment. Return flow can be customized after validating Cashfree behavior in sandbox.
- If no terminal is signed in, the dashboard waits; the dispatch expires after 10 minutes. To retry, use the original invoice checkout and select Cashfree again.
- A Cashfree SDK call triggered automatically on page load may be blocked by browser policies. The gateway page retains a manual fallback.
- The existing checkout route is public. For non-dashboard sessions it intentionally still opens its usual Cashfree page; test this separately.
- Full Flask/Cashfree sandbox integration tests are required before production deployment; syntax compilation alone is not sufficient.
