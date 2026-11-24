# OWL STORE Pay Terminal — Phase 1

Adds `/terminal` code login, `/terminal/dashboard` and `/admin/terminal` code management.

## Staging deployment
1. Back up Neon and use a staging database/Render service.
2. Apply `migrations/003_terminal_access.sql` to staging Neon using its SQL editor.
3. Deploy the updated project with existing environment variables. Never commit secrets.
4. Log in via the existing `/login` admin page, then visit `/admin/terminal`.
5. Generate a code for an existing active staff/admin user. Copy it immediately (shown once).
6. Open a separate private browser at `/terminal`; enter username and code.
7. Test incorrect codes, five-attempt lockout, rotation, revocation and logout.
8. Run `python -m unittest discover -s tests -v` before production deployment.

**Scope:** Phase 1 only. No Cashfree payment collection or waiting popup is wired yet. Do not advertise terminal payments as live until Phase 2 is implemented and verified.

**Security:** Code login uses a separate `terminal_user_id` session key; it does not authenticate the existing admin/staff dashboard. Admin code management requires the existing admin password login. Codes are high-entropy, hashed and shown once. CSRF applies to forms.
