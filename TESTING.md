# Testing

This document separates automated checks from browser, Telegram, and deployment validation. Passing the automated suite does not establish production readiness.

## Requirements

- Python 3.11+ with SQLite support and an IANA time-zone database
- Node.js for the optional JavaScript checks; no npm dependencies are needed
- Permission to bind loopback sockets for HTTP integration tests

Run all commands from the repository root. Automated database tests use temporary files and do not require a real Telegram token or live Telegram account.

## Automated checks

```sh
python -m unittest discover -s tests -v
python -m compileall -q server.py auth.py store.py worker.py tests
node --check static/app.js
node tests/test_ui.cjs
```

The JavaScript suite executes date and aggregation helpers from the actual application source with Node's built-in modules. It is not a browser emulator or a browser end-to-end test.

### Coverage

- **Authentication:** HMAC validation, constant-time comparison, tampering, expired or future authentication data, malformed fields, duplicate fields, and owner allowlisting
- **HTTP integration:** demo requests, production signature validation, server-derived identity, input validation, mode isolation, and local static assets
- **Storage:** timer idempotency, one active timer per user, manual-entry overlap rejection, adjacent-entry boundaries, request UUID deduplication, and per-user ownership
- **Budgets and dates:** local Monday boundaries, cross-week time splitting, retained weekly budget snapshots, and 167-/169-hour daylight-saving weeks
- **Reminder queue:** restart deduplication, bounded 429 retries, uncertain outcomes without automatic resend, interrupted claim recovery, overdue expiration, and backlog limits
- **Bot handling:** allowlisted private chats and duplicate update suppression
- **Frontend helpers:** time-zone conversion, fractional UTC offsets, nonexistent and ambiguous local times, midnight splitting, 23-/25-hour days, week clipping, and English date/number formatting
- **Static checks:** unique HTML IDs, JavaScript element references, served assets, avoidance of `innerHTML` for user content, and untranslated CJK text in the public source and documentation

## Recorded validation

Validation date: **2026-10-01**.

- **78 Python tests passed** in the automated suite
- **16 JavaScript date/time-zone and English-locale cases passed**
- Python compilation and JavaScript syntax checks passed
- An independent local server smoke test returned HTTP 200 for the app, configuration, JavaScript, stylesheet, demo SDK stub, and authenticated demo state
- The demo's initial weekly budgets totaled 10 hours

The test runner output is the source of truth for exact counts because new cases may be added as the application changes.

## Not yet validated

- **Browser acceptance:** the available cloud browser was blocked from accessing the loopback demo with `ERR_BLOCKED_BY_CLIENT`. No visual, mobile-layout, keyboard, touch, or real-click end-to-end acceptance was completed
- **Live Telegram:** no real bot token was available, so Mini App launch, signed data from a live session, actual message delivery, and callback interaction were not tested end to end
- **Production hosting:** no public HTTPS proxy, continuous service operation, production load, or deployed backup/recovery workflow was validated

No browser screenshot or live-delivery claim should be treated as established by the automated checks above.

## Manual acceptance checklist

Use synthetic data and a dedicated test bot where possible. Keep credentials and signed Mini App data out of reports and screenshots.

### Local demo

1. Start `python server.py` and open `http://127.0.0.1:8787`
2. Confirm that demo mode is visible, the default time zone is UTC, and the initial budget is 10 hours
3. Check a narrow mobile viewport and a desktop viewport for clipping, readable controls, and dialog scrolling
4. Navigate and operate controls using the keyboard; check focus visibility and dialog closing
5. Start a timer, refresh, stop it with notes, and confirm the completed entry appears
6. Add a valid past entry; confirm that an overlapping or future entry is rejected
7. Edit a project budget and compare initialized weeks to confirm snapshot behavior
8. Change the time zone and inspect week navigation, day totals, and date inputs around a daylight-saving boundary
9. Use **Try a reminder** and confirm its state is simulated, with no outbound Telegram request
10. Restart the process and confirm the local data remains

### Private Telegram deployment

1. Verify that an allowed user can open the Mini App from a private bot chat
2. Verify that an unlisted account, missing signature, altered signature, and expired session cannot access production data
3. Schedule a near-future test reminder and confirm its actual Telegram arrival
4. Exercise snooze and skip, then check database-backed status in the Mini App
5. Test `/start`, `/help`, `/today`, and `/stop`; `/today` currently reports the weekly total
6. Restart the service with pending and completed test reminders and confirm the expected recovery behavior
7. Test a consistent backup and restore in an isolated environment
8. Confirm the reverse proxy, loopback binding, persistent storage, service permissions, and single-worker operation

Use the automated suite's fake senders to exercise delivery failures. Do not deliberately exhaust Telegram rate limits to test retries.

## Reporting a failure

Include the commit, Python/Node versions, operating system, relevant test command, and a minimal sanitized reproduction. State whether the failure occurred in demo mode, a live Mini App, or a deployed service. Do not attach `.env`, databases, bot tokens, authorization headers, or private reflection notes.

For security issues, follow [SECURITY.md](SECURITY.md).
