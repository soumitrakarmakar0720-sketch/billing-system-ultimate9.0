# Phase 4 — Auto Cashfree terminal (STAGING)

- The terminal dashboard is now an idle listener; **My Assigned Bills** is removed.
- When a normal-dashboard staff user creates a single-payment bill, the existing `terminal_transaction` assigns the original order to that user.
- When **Pay online with Cashfree** is clicked on the normal checkout, the existing `/pay/<token>/cashfree` route creates the gateway order. The signed-in terminal checks `/terminal/next-payment` every 3 seconds and navigates to the Cashfree SDK checkout page.
- The gateway session is fetched from Cashfree's existing order ID. No new invoice, payment order or webhook handler is created.
- The terminal gateway page attempts automatic Cashfree checkout and includes a manual button if browser popup/gesture restrictions prevent it.
- Existing `/terminal/payment/<id>` monitors payment status and provides receipt after server verification.

## Important limitations
- The terminal code login and normal dashboard login must refer to the **same staff account**.
- Normal dashboard Cashfree initiation still opens its own checkout page, as before; the terminal independently launches the same Cashfree order. Avoid attempting to pay twice on two devices.
- The terminal detects Cashfree initiation by the existing `gateway_order_id`. Because Phase 3 creates that ID before contacting Cashfree, a brief retry may be necessary while Cashfree is creating the session.
- The idle terminal remembers opened orders in browser sessionStorage to avoid repeatedly launching the same checkout. Reopening a tab/browser session may show an older pending Cashfree bill. A future version should add an explicit payment-dispatch table/event with expiry and acknowledgement.
- Do not deploy to production before staging validation of webhook verification, failed/expired payments, multi-staff isolation and browser checkout behavior.
- No additional SQL migration beyond 003 and 004 is required for this patch.
