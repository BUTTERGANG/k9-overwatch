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

### 6. Same-Origin Policy

- No CORS headers configured (requests limited to same origin)
- API endpoints only accessible from the same domain

### 7. Async Database Safety

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
| No CSRF protection | Form submissions vulnerable to cross-site forgery | Add CSRF tokens to all forms |
| Admin over HTTP | Credentials sent in cleartext | Enforce HTTPS in production |

### Medium Priority

| Gap | Risk | Recommendation |
|-----|------|----------------|
| No rate limiting on web endpoints | DoS vulnerability | Add per-IP rate limiting middleware |
| No password hashing | Admin password stored as plaintext in env | Hash with bcrypt/argon2 |
| ~~No session management~~ | ~~HTTP Basic sends credentials every request~~ | ✅ Fixed — signed user sessions use hardened cookies; production secrets are fail-closed. |
| No audit logging | No record of admin actions | Log all state-changing operations |

### Low Priority

| Gap | Risk | Recommendation |
|-----|------|----------------|
| No content security policy | XSS risk from injected content | Add CSP headers |
| Tailwind via CDN | CDN compromise could inject malicious CSS | Self-host Tailwind build |
| No request logging | Limited visibility into traffic patterns | Add structured access logs |

---

## Security Recommendations for User Accounts

When user accounts are added (see `06-USER-ACCOUNTS.md`), the following security measures should be implemented:

### Authentication
- **Password hashing:** Use `argon2` or `bcrypt` (never store plaintext)
- **OAuth2 support:** Google, Facebook, Apple sign-in for convenience
- **JWT tokens:** Stateless auth for API endpoints
- **Session management:** Secure httponly cookies with SameSite=Strict
- **MFA option:** TOTP-based two-factor authentication

### Authorization
- **Role-based access control (RBAC):** User, Moderator, Admin roles
- **Resource ownership:** Users can only edit/delete their own listings
- **Rate limiting:** Per-user rate limits on posting and API access

### Data Protection
- **PII encryption:** Encrypt contact info at rest
- **Data minimization:** Only collect necessary personal information
- **GDPR compliance:** Data export and deletion capabilities
- **Email verification:** Verify email before activating accounts

### API Security
- **CORS configuration:** Whitelist specific frontend origins
- **CSRF tokens:** On all state-changing endpoints
- **Request signing:** For sensitive API operations
- **Input sanitization:** Strip HTML from user-submitted text
- **File upload validation:** Image type, size, and content verification

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
