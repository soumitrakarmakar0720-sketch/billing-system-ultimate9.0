# Phase 3: Customer EMI foreclosure — staging candidate

This update adds a customer-facing Foreclose all EMIs action to the existing token-based customer EMI page. It creates/reuses a single pending `EMIForeclosure` record, obtains a Cashfree payment session, and displays the existing Cashfree SDK checkout. Successful settlement still depends on the existing verified webhook. Normal sequential installment rules remain in place.

## Prerequisite
Apply `migrations/001_ultimate3_emi_archive.sql` and `migrations/002_emi_foreclosure.sql` **to a test Neon branch first**. Verify the `emi_foreclosure` table exists. Do not blindly run migrations on production. Back up your production database.

## Important limitations — do NOT deploy to production without addressing
- The preexisting Phase 2 webhook handling and admin foreclosure initiation are not fully concurrency-safe. A simultaneous successful installment and foreclosure webhook can create reconciliation problems; all payment status transitions must be serialized and idempotent.
- Existing installment Cashfree orders require authoritative gateway reconciliation before foreclosure. This candidate conservatively blocks foreclosure if an unpaid installment has a gateway order ID, until an admin resolves it.
- Failed/expired Cashfree foreclosure attempts require an authenticated reconciliation and retry/expiry workflow; a pending record may otherwise block installments.
- Customer access currently relies on possession of a public token. Add authenticated/OTP access and appropriate rate limits before public rollout.
- The customer foreclosure route requires the existing session CSRF token. Verify cookie/SameSite behavior in browsers.
- Gateway webhook success should be verified end-to-end on Cashfree sandbox and staging Neon. Do not test with production charges.
- The original Phase 2 application has no automated regression coverage for this workflow. Python syntax compilation alone is not sufficient.

## Suggested staging checks
1. EMI 1 paid, EMI 2 unpaid: EMI 2 only is payable.
2. Customer foreclosure with no pending installment gateway order: Cashfree sandbox session starts for exact outstanding amount.
3. Repeat foreclosure request: reuses the same `emi_foreclosure` record and Cashfree order ID.
4. Cashfree verified success: parent becomes FORECLOSED; remaining children become SETTLED_FORECLOSURE.
5. Forged, duplicated, failed, or delayed webhooks: no false settlement.
6. Concurrent payment and foreclosure attempts: do not overcharge or double-settle.
