# Security Implementations

## Overview

This document covers the current security measures in K9-Overwatch and identifies areas for improvement as the platform grows.

---

## Current Security Measures

### 1. Admin Authentication

**Implementation:** HTTP Basic Auth on `/admin` routes

```python
# web/routers/admin.py
credentials = HTTPBasicCredentials(...)
if not (secrets.compare_digest(credentials.username, ADMIN_USER) and
        secrets.compare_digest(credentials.password, ADMIN_PASSWORD)):
    raise HTTPException(status_code=401)
```

**Key details:**
- Uses `secrets.compare_digest()` for timing-safe string comparison (prevents timing attacks)
- Credentials stored in environment variables (`ADMIN_USER`, `ADMIN_PASSWORD`)
- Production startup rejects a missing or default `ADMIN_PASSWORD` (`changeme`)
- Applied to admin dashboard, stats endpoint, and stats partial

### 2. User Sessions

- Sessions use HMAC-signed cookies with `SESSION_SECRET`.
- Production startup rejects a missing or default `SESSION_SECRET`.
- Session cookies are `HttpOnly`, `SameSite=Lax`, and `Secure` in production.

### 3. SQL Injection Prevention

- All database queries use SQLAlchemy ORM with parameterized queries
- No raw SQL strings with user input
- Pydantic models validate and type-check all incoming data before it reaches the database

### 4. Input Validation

- **Pydantic models** validate all API request/response data
- **Query parameters** have type constraints (e.g., `int` with `ge`/`le` bounds)
- **GeoJSON bbox** validates that southwest coordinates are less than northeast
- **Enum validation** on record_type, animal_type, gender, size fields

### 4. Image Proxy Security

The `/proxy/image` endpoint prevents open proxy abuse:

**Domain Allowlist:**
- Only 31 known pet listing domains are proxied
- Unknown domains are rejected with 403
- Prevents the server from being used as an open proxy

**File Size Limit:**
- Maximum 5MB per image
- Prevents memory exhaustion attacks

**Content-Type Validation:**
- Only `image/*` content types accepted
- Prevents serving malicious content through the proxy

**In-Process Cache:**
- SHA1 hash key, 1-hour TTL, max 500 entries
- LRU eviction (removes oldest 10% when full)
- Prevents repeated fetches from consuming bandwidth

### 5. Rate Limiting (Scraper Level)

- `HTTP_RATE_LIMIT_SECONDS` (default 1.5s) between scraper requests
- Prevents overwhelming external sources
- Browser scrapers are inherently rate-limited by page load times

### 6. CSRF Protection

- Middleware issues signed, user-bound CSRF tokens to templates.
- Cookie-authenticated `POST`, `PUT`, `PATCH`, and `DELETE` requests must
  provide the matching form token or `X-CSRF-Token` header.
- Anonymous login, registration, and password-recovery endpoints are exempt
  because they do not have a prior authenticated session.

### 7. Upload Validation

- Owner report uploads are limited to three files and 5 MiB per file.
- Extensions are restricted to JPEG, PNG, and WebP.
- JPEG, PNG, and WebP container signatures are checked; filenames and MIME
  types are not trusted.
- Files are stored under generated UUID names in `data/uploads/`.

### 8. Same-Origin Policy

- No CORS headers configured (requests limited to same origin)
- API endpoints only accessible from the same domain

### 9. Async Database Safety

- SQLAlchemy async sessions with automatic commit/rollback
- Context manager pattern ensures sessions are always closed
- No connection leaks even on exceptions

---

## Current Security Gaps

### High Priority

| Gap | Risk | Status |
|-----|------|--------|
| ~~Match review has no auth~~ | ~~Anyone can confirm/reject matches~~ | ✅ Fixed — `verify_admin` on `POST /api/matches/{id}/review`. Non-admin HTMX requests receive a 401 with a toast warning. |
| ~~No security headers~~ | ~~Missing X-Frame-Options, CSP, HSTS~~ | ✅ Fixed — `SecurityHeadersMiddleware` sets X-Frame-Options, X-Content-Type-Options, X-XSS-Protection, Referrer-Policy, Permissions-Policy, and a full CSP on every response. |
| ~~No CSRF protection~~ | ~~Form submissions vulnerable to cross-site forgery~~ | ✅ Fixed — signed user-bound tokens are enforced on cookie-authenticated state-changing requests; anonymous auth/recovery endpoints are intentionally exempt. |
| Admin over HTTP | Credentials sent in cleartext | Enforce HTTPS in production; deployment validation is deferred |

### Medium Priority

| Gap | Risk | Recommendation |
|-----|------|----------------|
| ~~No rate limiting on auth/report endpoints~~ | ~~Credential-stuffing / spam DoS on login, register, password reset, report~~ | ✅ Fixed — in-process per-IP fixed-window limiter (`web/rate_limit.py`) on login/register/forgot-password/reset-password/report. Read endpoints (map/pets/matches) remain unguarded; the limiter is in-process only, so a multi-worker deployment needs a shared store (e.g. Redis) instead. |
| ~~No password hashing~~ | ~~User passwords stored as plaintext~~ | ✅ Fixed — user passwords use stdlib scrypt hashes; admin HTTP Basic credentials remain environment-configured and deployment hardening is deferred. |
| ~~No session management~~ | ~~HTTP Basic sends credentials every request~~ | ✅ Fixed — signed user sessions use hardened cookies; production secrets are fail-closed. |
| No audit logging | No record of admin actions | **Deferred** — log all state-changing operations |

### Low Priority

| Gap | Risk | Recommendation |
|-----|------|----------------|
| ~~No content security policy~~ | ~~XSS risk from injected content~~ | ✅ Fixed — `SecurityHeadersMiddleware` sends a CSP; deployment/live-browser validation remains deferred. |
| Tailwind via CDN | CDN compromise could inject malicious CSS | Self-host Tailwind build |
| No request logging | Limited visibility into traffic patterns | Add structured access logs |

---

## Remaining Security Recommendations

The account flow is implemented with scrypt password hashing, signed sessions,
email verification, single-use password-reset tokens, CSRF middleware, and
bounded image upload validation. Remaining hardening is intentionally deferred:

- Extend per-IP rate limiting beyond auth/report to read endpoints, and back it
  with a shared store if the app ever runs multi-worker.
- Add audit logging for state-changing operations.
- Evaluate MFA, RBAC expansion, PII-at-rest encryption, and data export/deletion.
- Validate production HTTPS, deployment, migrations, and external providers in a
  controlled environment; no live deployment is claimed by this document.

---

## Environment Variables (Security-Related)

```env
ADMIN_USER=admin              # Admin username
ADMIN_PASSWORD=changeme       # Admin password (change in production!)
DATABASE_URL=...              # Database connection string
GOOGLE_MAPS_API_KEY=          # API key (if using Google geocoding)
ALERT_WEBHOOK_URL=            # Discord/Slack webhook for alerts
```

All secrets should be managed through environment variables, never committed to source control. The `.env` file is git-ignored.
