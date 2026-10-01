# TimePocket

A small, self-hosted time budget and reflection app with a Telegram bot and Mini App. Make room for what matters, record progress, and get a gentle reminder when you choose. No streaks, no penalties, and no AI service required.

TimePocket is an early-stage personal-use application. It includes an English interface, a local demo, a Python standard-library backend, and a persistent SQLite reminder queue. Read the [testing status](TESTING.md) and [security guidance](SECURITY.md) before deploying it.

## Features

- **Flexible weekly budgets:** rename projects and adjust their budgets without treating unused time as debt
- **One focus timer:** start and stop a session, or manually record 1–1,440 minutes of past activity
- **Small reflections:** save accomplishments, blockers, and next steps with a time entry
- **Weekly review:** compare completed time with budgets and see daily totals and project distribution
- **Time-zone-aware accounting:** local Monday-to-Monday weeks, cross-week splitting, and daylight-saving boundaries
- **One-time reminders:** schedule a specific date and time, snooze for 15 minutes, or skip
- **Telegram access:** owner-allowlisted private chats, signed Mini App authentication, and `/start`, `/help`, `/today`, and `/stop` commands
- **Persistent local storage:** SQLite retains budgets, logs, timer state, and reminder status across restarts

New accounts start in **UTC** with a **10-hour weekly budget**: Learning (3h), Side Project (2h), Exercise (2h), Reading (1h), Writing (1h), and Weekly Review (1h). Change the time zone and project names to suit your routine.

## Quick start

Requirements:

- Python **3.11 or newer**, including SQLite support and access to an IANA time-zone database
- A modern browser with JavaScript enabled
- Node.js only if you want to run the optional JavaScript checks

There are no third-party Python packages to install and no frontend build step.

```sh
git clone https://github.com/songying/TimePocket.git
cd TimePocket
python server.py
```

Open **http://127.0.0.1:8787** on the same computer. Use `python3` instead of `python` if that is how Python 3 is installed on your system. Stop the server with Ctrl+C.

The default is `APP_MODE=demo`; no `.env` file or Telegram token is needed. Demo mode uses one shared local identity and a separate `demo.sqlite3` database. It does not load the Telegram SDK or call Telegram APIs. The **Try a reminder** button records a simulated delivery locally; it does not send a message.

Keep demo mode bound to localhost. Anyone who can reach a demo server can use its shared identity, so do not put private data in a publicly reachable demo. Localhost is not a hosted preview, and reminders cannot run after the server stops.

## Everyday use

1. Set your IANA time zone, such as `UTC`, `America/New_York`, or `Europe/London`
2. Edit a project's name and weekly budget
3. Start a focus timer, or log work you already completed
4. Add a few notes when saving the entry
5. Open **Weekly review** to reflect on completed time
6. Add an individual reminder when a nudge would help

Weekly totals count completed entries. An active timer is shown separately until it is stopped. Manual entries cannot be in the future or overlap another entry or an active timer.

Opening a week creates its budget snapshot. Editing a budget changes the selected week and the default used for weeks that do not yet have a snapshot; other initialized weeks retain their budgets. Project names are shared across weeks.

Reminders are **one-time only**. There is no recurring weekly reminder scheduler. During a daylight-saving transition, the interface rejects nonexistent local times and uses the first occurrence of an ambiguous local time.

## Private Telegram setup

Use a server you control, an HTTPS domain, and persistent storage. A Telegram bot token is a credential: enter it privately on the server, never in an issue, screenshot, chat, commit, or browser-side code.

1. Create a bot through Telegram's official [BotFather](https://t.me/BotFather)
2. Copy `.env.example` to `.env` and edit it privately on your server
3. Supply your bot token, the numeric Telegram user IDs allowed to use the app, and your HTTPS URL
4. Put a hardened HTTPS reverse proxy in front of the loopback-only application server
5. Configure the bot's Mini App or menu button in BotFather to use the same `APP_URL`
6. Start `python server.py`, send `/start` to your bot, and open TimePocket using its button

Example configuration, with placeholders to replace privately:

```dotenv
APP_MODE=production
HOST=127.0.0.1
PORT=8787
TELEGRAM_BOT_TOKEN=replace_privately_on_your_server
TELEGRAM_OWNER_IDS=123456789
APP_URL=https://timepocket.example.com
DB_PATH=/var/lib/timepocket/production.sqlite3
```

Create the parent directory for `DB_PATH` and make it writable only by the service account as appropriate. Restrict `.env` and database access. The example user ID is a placeholder, not an authorized account to reuse.

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_MODE` | `demo` | `demo` or `production` |
| `HOST` | `127.0.0.1` | Application bind address; keep it on loopback behind a proxy |
| `PORT` | `8787` | Application HTTP port |
| `TELEGRAM_BOT_TOKEN` | Empty | Required in production; server-side credential |
| `TELEGRAM_OWNER_IDS` | Empty | Required in production; comma-separated positive numeric Telegram user IDs |
| `APP_URL` | Empty | Required in production; HTTPS Mini App URL |
| `DB_PATH` | `<mode>.sqlite3` beside `server.py` | SQLite file; use a persistent, private location in production |

Existing process environment variables take precedence over `.env`. The built-in `.env` reader supports simple `KEY=value` lines, optional surrounding quotes, and full-line comments. It does not provide shell expansion or advanced dotenv syntax.

Each allowed Telegram user has separate projects, logs, timers, and reminders. Usernames are not numeric owner IDs. The bot operates in private chats only; users must start the bot before it can send them reminders.

This implementation uses `getUpdates` polling. Run **one application instance with one background worker**, and do not run another poller for the same bot. An existing webhook conflicts with polling; review and remove it deliberately before switching this bot to TimePocket.

### Deployment checklist

The bundled `http.server` is a minimal application server, not a hardened public edge. Production mode enables Telegram integration and authentication; it is not a deployment-hardening switch.

- [ ] Use a valid HTTPS certificate and a hardened reverse proxy with request timeouts, body-size limits, and rate limits
- [ ] Keep the Python server off the public network and run it as an unprivileged service account
- [ ] Restrict access to `.env`, database files, and backups; use encrypted storage when appropriate
- [ ] Use persistent disk, a process supervisor, restart policy, and operational monitoring
- [ ] Run only one application instance and confirm that no webhook or other bot poller conflicts
- [ ] Verify owner IDs, Mini App authentication, the configured time zone, and actual Telegram delivery
- [ ] Test snooze, skip, restart recovery, and backup restoration
- [ ] Review [SECURITY.md](SECURITY.md) and the unverified items in [TESTING.md](TESTING.md)

For SQLite backups, use a consistent SQLite backup procedure or stop the service before copying its data. Copying only a live main database file can omit transactions stored in its WAL file.

## Reminder delivery semantics

Reminders are persisted and atomically claimed in SQLite. Repeated creation of an identical pending reminder is deduplicated. A successfully recorded delivery is not automatically sent again after restart.

The queue deliberately bounds catch-up traffic:

- Pending reminders more than one hour overdue expire
- Each scheduler pass selects at most the three newest due reminders per user; older due backlog expires
- Explicit HTTP 429 responses allow at most three delivery attempts, with 60- and 120-second backoffs
- Other HTTP 4xx responses fail without automatic retry
- Network errors, HTTP 5xx responses, and unconfirmed delivery outcomes become `uncertain`, without automatic resend
- A delivery claim left unfinished for more than 60 seconds becomes `uncertain`

There is no exactly-once delivery guarantee. Telegram delivery and a local database update are separate operations. To reduce duplicate messages, an uncertain outcome is not retried automatically, so a reminder can be missed. Manually snoozing it may produce another message if the earlier attempt actually arrived. The interface exposes reminder statuses.

Bot update IDs are recorded before handling an update to avoid replaying effects. A crash in that interval can lose a command or reply; the user can issue the command again.

Do not use TimePocket for medical, safety-critical, or other high-consequence reminders.

## Architecture

| Path | Responsibility |
| --- | --- |
| `server.py` | HTTP routes, environment configuration, demo/production isolation, and worker lifecycle |
| `auth.py` | Server-side Telegram Mini App signature, freshness, and owner validation |
| `store.py` | SQLite schema, per-user ownership, timers, logs, budgets, and time-zone calculations |
| `worker.py` | Persistent reminder queue, Telegram API adapter, and bot polling |
| `static/` | English browser interface using plain HTML, CSS, and JavaScript |
| `tests/` | Python unit/integration checks and optional Node.js helper tests |

The browser calls the same-origin API. Production requests authenticate with signed Telegram `initData`, which the server verifies rather than trusting a client-provided user ID. Demo and production databases have a stored mode marker and cannot be reused across modes.

The token remains on the server. Normal reminder messages contain the project name and reminder text; bot command replies contain their relevant status. Reflection notes are not automatically included in Telegram messages. SQLite data is not encrypted by the application.

## Development and tests

```sh
python -m unittest discover -s tests -v
python -m compileall -q server.py auth.py store.py worker.py tests
```

Optional JavaScript checks require Node.js, with no npm install:

```sh
node --check static/app.js
node tests/test_ui.cjs
```

See [TESTING.md](TESTING.md) for coverage and validation gaps, and [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidance.

## Current limitations

- Early-stage personal-use scope; no availability or delivery guarantee
- No recurring reminders, project creation/deletion interface, historical-entry editor, or data export/deletion interface
- No distributed scheduler, multi-instance deployment, or production migration framework
- No browser visual or interaction acceptance completed in the initial validation environment
- No live Telegram end-to-end validation completed; no bot token was available for that validation
- No public HTTPS deployment, long-running uptime, or production load validation completed

These limits are documented rather than hidden behind passing unit tests. Validate your own deployment before relying on it.

## References and license

- [Telegram Mini App data validation](https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app)
- [Telegram Bot API: sendMessage](https://core.telegram.org/bots/api#sendmessage)
- [Telegram Bot API: getUpdates](https://core.telegram.org/bots/api#getupdates)

TimePocket is licensed under the [MIT License](LICENSE).
