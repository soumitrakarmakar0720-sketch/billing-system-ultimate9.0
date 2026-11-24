# OWL STORE Pay Terminal Phase 3 — Normal dashboard integration (STAGING)

## Changes
- Normal `/create-order` creates one original Order and a TerminalTransaction assignment to the normal logged-in user, only for non-EMI bills. No duplicate Order.
- `/terminal/dashboard` shows bills assigned to the terminal code user. Historical unassigned pending bills can be claimed using POST with CSRF; concurrent claims fail safely.
- Existing `/pay/<token>` Cashfree initiation and `/webhooks/cashfree` signed webhook remain unchanged.
- `/terminal/payment/<order_id>` monitors the assigned original order, polling every four seconds; PDF receipt requires PAID.
- EMI parents and children are unchanged. Terminal does not collect EMI payments; existing EMI routes retain their sequential restrictions.

## Important limitations / staging checks
- Staff must use the same underlying User account for normal dashboard and terminal code for automatic ownership. Other staff will not see another person's assigned bills.
- Cashfree starts from the normal checkout page after clicking Pay online with Cashfree; it does not automatically charge on saving a bill. Staff can open terminal monitor in another tab/device.
- Terminal access codes are separate sessions. Logging into the terminal in the same browser will clear normal dashboard login. Use another browser profile/incognito/device for parallel sessions.
- Run migration 003 and 004 before deploying this project if not already applied. No new migration required for this phase.
- Do not use production Cashfree or Neon to test. Confirm webhook idempotency, status polling, customer checkout, staff role permissions and receipt on staging.
