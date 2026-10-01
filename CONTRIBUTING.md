# Contributing to TimePocket

Contributions that keep TimePocket small, understandable, and reliable are welcome. The current focus is personal time budgeting, useful reflection, and gentle one-time reminders.

## Before you start

- Read [README.md](README.md), [TESTING.md](TESTING.md), and [SECURITY.md](SECURITY.md)
- For a substantial behavior change, open an issue describing the problem and proposed approach before investing in a large implementation
- Keep bug reports and examples free of tokens, signed Telegram data, private notes, and personal database contents
- Discuss security vulnerabilities privately as described in the security policy

## Local setup

Fork or clone the repository and create a branch for your change:

```sh
git clone https://github.com/songying/TimePocket.git
cd TimePocket
git switch -c describe-your-change
python server.py
```

Use Python 3.11+ with SQLite and an IANA time-zone database. The backend uses the standard library; there is no pip install step. Node.js is optional for JavaScript checks and requires no npm packages.

The default server runs a local demo at `http://127.0.0.1:8787`. Use synthetic data. You do not need a Telegram token for normal automated development.

## Implementation guidelines

- Keep changes focused and document user-visible behavior
- Preserve demo/production isolation and server-verified user ownership
- Keep bot credentials server-side; do not log authorization headers, signed Mini App data, Telegram request URLs, or private content
- Store timestamps as UTC instants and use IANA time zones for local calendar boundaries
- Preserve idempotency and the queue's documented uncertain-delivery behavior; do not add automatic resends that hide duplicate-message risk
- Keep public documentation, interface text, and examples in English until an explicit localization design is introduced
- Use text-safe DOM updates for user content and maintain labels, keyboard access, and meaningful status messages
- Prefer the existing dependency-light design; explain why any new dependency is necessary
- Add regression tests for fixes, especially ownership, time-zone, overlap, retry, and restart behavior
- Explain schema changes and any migration impact before changing persistent data formats

## Checks before opening a pull request

```sh
python -m unittest discover -s tests -v
python -m compileall -q server.py auth.py store.py worker.py tests
node --check static/app.js
node tests/test_ui.cjs
git diff --check
git status --short
```

If Node.js is unavailable, run the Python checks and clearly state that the JavaScript checks were not run. For UI changes, also perform the relevant manual checks in [TESTING.md](TESTING.md). Automated helper tests do not replace browser testing.

Review the diff before committing. `.env`, SQLite files, and runtime caches are ignored, but ignore rules are not a substitute for checking that no sensitive data was staged.

## Pull requests

Describe:

- The problem and the behavior that changed
- How to reproduce or exercise the change
- Tests and manual checks run, with any remaining validation gaps
- Any configuration, security, delivery, or persistent-data implications

For visible UI changes, include screenshots only when you have actually rendered the change, using synthetic data. Do not imply that a live Telegram or deployment test passed unless it was performed.

Keep unrelated cleanup in a separate change where practical. Update documentation alongside behavior changes, especially configuration and reminder semantics.

## License

TimePocket uses the [MIT License](LICENSE). Contributions should be compatible with that license. Do not add code or assets you do not have permission to contribute.
