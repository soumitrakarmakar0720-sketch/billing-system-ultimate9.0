# Phase 7 — Terminal return after Cashfree checkout

- Cashfree SDK terminal checkout uses `redirectTarget: '_modal'` instead of `_self` so the terminal browser does not navigate to the original bill's customer return URL.
- The existing verified payment-status endpoint is polled every 3 seconds. Only after `paid: true` does the terminal navigate back to `/terminal`.
- The normal dashboard waiting page, Cashfree order creation, webhook, EMI workflows, and customer checkout are unchanged.
- If Cashfree requires a full-page redirect for a particular payment method, test that method in staging: the original Cashfree order return URL may still lead to the customer bill page. A robust full-page return solution would require a separate server-side terminal-specific return URL at Cashfree order creation and carefully preserve public checkout behavior.
- Test both successful and failed/cancelled Cashfree sandbox payments before production rollout.
