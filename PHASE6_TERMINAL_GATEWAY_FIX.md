# Phase 6 — Terminal Gateway Fix (STAGING)

- Removes customer-phone/same-device selector from `/terminal/payment/<id>`.
- Legacy payment URL redirects to the active terminal Cashfree dispatch, if any.
- The Cashfree gateway page automatically attempts SDK checkout, with a visible manual retry only if needed.
- After checkout closes, payment status is verified via the existing server status endpoint; no browser event marks an invoice PAID.
- Reopening a dispatched gateway URL within its expiry is permitted for recovery, without creating another invoice or Cashfree order.
- The normal dashboard waiting flow and EMI code are unchanged.

**Caveats:** Cashfree's order return URL may still lead to the customer checkout after a full-page gateway redirect. Browser autoplay restrictions can require the retry button. Cashfree 400 errors require checking domain allowlisting, API environment, and session validity. Test in staging before production.

No new database migration beyond Phase 5 migrations 003–005.
