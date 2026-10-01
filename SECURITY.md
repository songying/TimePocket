# Security

TimePocket is an early-stage, self-hosted personal application. Its authentication and isolation checks reduce specific risks; they are not a security audit or a guarantee that a public deployment is safe.

## Reporting a vulnerability

Do not put exploit details, bot tokens, signed Telegram `initData`, private notes, databases, or other sensitive data in a public issue or pull request.

If GitHub shows a private **Report a vulnerability** option under this repository's **Security** tab, use it. If a private reporting option is not available, open a public issue asking the maintainer for a private contact method, without including vulnerability details or sensitive data. No separate security email address or response-time commitment is published here.

A useful private report includes the affected commit, impact, minimal reproduction using synthetic data, and a suggested mitigation if you have one. Avoid testing against someone else's bot, account, or deployment without permission.

## Scope and support

The current source on the default branch is the development baseline. There is no published long-term-support or backport policy. Review changes and run the tests before updating a deployment.

TimePocket must not be used for medical, safety-critical, or other high-consequence reminders. Delivery can be missed, and uncertain results are deliberately not resent automatically.

## Authentication and access

Production mode requires:

- A server-side Telegram bot token
- An explicit allowlist of numeric Telegram user IDs
- An HTTPS Mini App URL
- Server-side validation of Telegram's signed Mini App `initData`

The server checks the HMAC with a constant-time comparison, authentication-data age, field formats, and owner membership. The default acceptance window is one hour, with at most 30 seconds of future clock tolerance. Client-supplied user IDs do not establish identity.

Signed `initData` acts as a bearer credential during its validity window. Do not log it, put it in URLs, attach it to bug reports, or share it in screenshots. Keep the host clock accurate and reopen the Mini App when authentication expires.

The bot processes allowlisted users in their own private chats only. This is a personal allowlist model, not a general public registration or organization-permissions system.

## Demo isolation

Demo mode uses a shared local identity and makes no Telegram API calls. Its demo header is a mode selector, not an authentication secret. Anyone who can reach a demo instance can use its shared data.

Keep demo mode on localhost and use synthetic data. Demo and production should use distinct database files; a stored mode marker rejects cross-mode reuse. Production does not fall back to demo authentication.

## Secrets and personal data

- Enter bot credentials privately on your own server; never commit them or put them in browser code
- Restrict `.env`, service configuration, database files, and backups to the necessary service account and operators
- Git ignore rules reduce accidental staging but do not remove secrets already committed
- If a bot token is exposed, revoke or rotate it through Telegram's official BotFather and update your private server configuration
- Review repository history and any published artifacts after a disclosure; removing the latest visible copy does not invalidate a leaked credential
- SQLite data, including reflection notes, is not encrypted by the application; protect the disk and backups appropriately
- Reminder project names, reminder text, and bot command replies are sent to Telegram; reflection fields are not automatically included in those messages

HTTP request logging is disabled in the application, and worker failures use generic messages. A reverse proxy, process supervisor, hosting provider, or custom instrumentation may still collect logs. Configure those systems so that credentials and personal content are not recorded.

## Deployment responsibilities

Do not expose the bundled Python HTTP server directly to the public internet. Put it behind a hardened HTTPS reverse proxy and keep its bind address on loopback or an appropriately restricted internal interface.

The operator is responsible for:

- TLS, request timeouts, body-size limits, rate limits, and network access controls
- An unprivileged service account and restrictive file permissions
- System and Python security updates
- Persistent disk, monitoring, process restart behavior, and consistent SQLite backups
- Testing recovery and securing the backup destination and retention policy
- A single application instance and background worker, with no conflicting Telegram webhook or poller

The application does not provide a hardened public edge, distributed coordination, application-level database encryption, or an administrative export/deletion interface. It has not undergone browser acceptance, live Telegram end-to-end verification, or a production deployment audit. See [TESTING.md](TESTING.md) for the actual validation scope.
