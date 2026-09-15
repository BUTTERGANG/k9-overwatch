# 🔐 SECRETS & Local Setup

How secrets for this repo are stored, exported, and pulled — so the **values never
appear in plaintext in git, logs, or chat**, and every new machine/dev box can
stand it up with one command.

## Model: hub-and-spoke (buttergang-dev is the single secrets hub)

```
Replit app secrets  ──(one-way EXPORT)──►  buttergang-dev:~[repo]/.env   (chmod 600, gitignored)
        ▲                                        │
        └── this repo NEVER reads other apps'     │ secret-pull (Tailscale ssh)
            secrets; nothing imports back in      ▼
                                          ~/.secrets/<repo>.env   (chmod 600)
                                              │
                                          run the app: source by NAME, never echo
```

- The **dev VPS `buttergang-dev`** is the ONLY writable mirror of this app's secrets.
- The **Mac pulls** a copy into `~/.secrets/<repo>.env` to run locally.
- **No mesh:** this repo never connects to other repos to read their secrets.

## Required keys

Each required key declared in `.env.example` is listed at the bottom of this file
(auto-generated). For each, add a one-line note on what it unlocks (e.g. "Postgres,
DB-gated app").

## Export layout (one-time, per repo)

Place the mirror at:

```
buttergang-dev:~/<repo>/.env        (decrypt/transfer, then chmod 600)
```

> `.env` is gitignored. This file does NOT belong in the repo. It exists only on
> the hub and (optionally) as a local `~/.secrets/<repo>.env` copy.

## Local sync — one command

```bash
bash ~/.hermes/skills/devops/secure-secret-transfer/scripts/secret-pull.sh <repo>
# or, for every repo at once:
bash ~/.hermes/skills/devops/secure-secret-transfer/scripts/secret-pull.sh
```

This reads `<repo>/.env.example`, fetches each required key from the hub by name,
writes `~/.secrets/<repo>.env` (chmod 600), and verifies presence **without
printing any value**.

## Run the app from the vault

```bash
set -a; source ~/.secrets/<repo>.env; set +a;  # then start the server
```

**Never** `cat ~/.secrets/<repo>.env`, `echo $SECRET`, or print a secret to stdout.

## Security rules (non-negotiable)

- `~/.secrets/` is `chmod 700`; each `<repo>.env` is `chmod 600`.
- A secret's **value never passes through command output/chat/logs**.
- `DASHBOARD_PIN` (and similar) **empty = open**. Set a strong value before public use.
- Replit's public secrets API is retired, and GitHub Actions secrets are write-only —
  neither is a way to read a value back. The hub mirror is the read path.
- Rotate a key the moment it might be exposed in plaintext anywhere.
## Required keys (auto-listed from .env.example)

- APP_DATABASE_URL — *describe*
- APP_DATABASE_DEVELOPMENT — *describe*
- SESSION_SECRET — *describe*
- DATABASE_URL — *describe*
- SEARCH_LAT — *describe*
- SEARCH_LON — *describe*
- SEARCH_RADIUS_MILES — *describe*
- SEARCH_ZIP — *describe*
- GEOCODE_PROVIDER — *describe*
- GOOGLE_MAPS_API_KEY — *describe*
- NOMINATIM_USER_AGENT — *describe*
- HTTP_RATE_LIMIT_SECONDS — *describe*
- PLAYWRIGHT_HEADLESS — *describe*
- ADMIN_USER — *describe*
- ADMIN_PASSWORD — *describe*
- SESSION_SECRET — *describe*
- RUN_SCHEDULER — *describe*
- SMTP_HOST — *describe*
- SMTP_PORT — *describe*
- SMTP_USER — *describe*
- SMTP_PASSWORD — *describe*
- SMTP_TLS — *describe*
- SMTP_FROM — *describe*
- APP_BASE_URL — *describe*
- GROUP_ADMIN_DIGEST_ENABLED — *describe*
- GROUP_ADMIN_DIGEST_RADIUS_MILES — *describe*
- ALERT_WEBHOOK_URL — *describe*
- LOG_LEVEL — *describe*
- LOG_FORMAT — *describe*
