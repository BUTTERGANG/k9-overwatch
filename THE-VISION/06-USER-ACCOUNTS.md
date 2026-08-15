# User Accounts & Self-Service Listings

## Overview

This document outlines the design for adding user accounts to K9-Overwatch, enabling pet owners to directly post lost/found pet listings alongside the automated scraper data. This transforms the platform from a read-only aggregator into a community-driven hub for pet reunification.

---

## Goals

1. Allow users to create accounts and post lost/found pet listings
2. Give users ownership of their listings (edit, update status, mark resolved)
3. Enable direct communication between users with matching pets
4. Maintain data quality while supporting user-generated content
5. Keep the existing scraper pipeline running alongside user submissions

---

## Database Schema Changes

### New Tables

#### `users`

```sql
CREATE TABLE users (
    id              TEXT PRIMARY KEY,           -- UUID
    email           TEXT NOT NULL UNIQUE,
    email_verified  BOOLEAN DEFAULT FALSE,
    password_hash   TEXT,                       -- argon2/bcrypt hash (NULL for OAuth-only)
    display_name    TEXT NOT NULL,
    phone           TEXT,
    phone_verified  BOOLEAN DEFAULT FALSE,

    -- OAuth connections
    oauth_provider  TEXT,                       -- "google", "facebook", "apple"
    oauth_id        TEXT,                       -- provider's user ID

    -- Profile
    city            TEXT,
    state           TEXT,
    zip             TEXT,
    avatar_url      TEXT,
    bio             TEXT,

    -- Status
    role            TEXT DEFAULT 'user',        -- "user", "moderator", "admin"
    active          BOOLEAN DEFAULT TRUE,
    banned          BOOLEAN DEFAULT FALSE,
    ban_reason      TEXT,

    -- Timestamps
    created_at      DATETIME NOT NULL,
    last_login_at   DATETIME,
    updated_at      DATETIME,

    UNIQUE (oauth_provider, oauth_id)
);
```

#### `user_sessions`

```sql
CREATE TABLE user_sessions (
    id              TEXT PRIMARY KEY,           -- UUID (session token)
    user_id         TEXT NOT NULL REFERENCES users(id),
    ip_address      TEXT,
    user_agent      TEXT,
    created_at      DATETIME NOT NULL,
    expires_at      DATETIME NOT NULL,
    revoked         BOOLEAN DEFAULT FALSE
);
```

#### `user_listings` (extends pet_rows)

```sql
-- Option A: Add user columns to existing pet_rows table
ALTER TABLE pet_rows ADD COLUMN user_id TEXT REFERENCES users(id);
ALTER TABLE pet_rows ADD COLUMN user_submitted BOOLEAN DEFAULT FALSE;
ALTER TABLE pet_rows ADD COLUMN moderation_status TEXT DEFAULT 'pending';
    -- "pending", "approved", "rejected", "flagged"
ALTER TABLE pet_rows ADD COLUMN moderation_note TEXT;
ALTER TABLE pet_rows ADD COLUMN resolved BOOLEAN DEFAULT FALSE;
ALTER TABLE pet_rows ADD COLUMN resolved_at DATETIME;
ALTER TABLE pet_rows ADD COLUMN resolved_reason TEXT;
    -- "reunited", "found_deceased", "other", "cancelled"
```

This approach (adding columns to `pet_rows`) is preferred over a separate table because:
- User listings participate in the same matching engine
- Same GeoJSON API serves both scraped and user listings
- No complex JOIN logic needed for unified views
- Source field distinguishes origin: `source = "user_submission"`

#### `user_notifications`

```sql
CREATE TABLE user_notifications (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id),
    type            TEXT NOT NULL,              -- "match_found", "message", "listing_approved", etc.
    title           TEXT NOT NULL,
    body            TEXT,
    link            TEXT,                       -- URL to relevant page
    read            BOOLEAN DEFAULT FALSE,
    created_at      DATETIME NOT NULL
);
```

#### `user_messages`

```sql
CREATE TABLE user_messages (
    id              TEXT PRIMARY KEY,
    thread_id       TEXT NOT NULL,              -- groups messages in a conversation
    sender_id       TEXT NOT NULL REFERENCES users(id),
    recipient_id    TEXT NOT NULL REFERENCES users(id),
    pet_id          TEXT REFERENCES pet_rows(id),  -- context pet
    body            TEXT NOT NULL,
    read            BOOLEAN DEFAULT FALSE,
    created_at      DATETIME NOT NULL
);
```

#### `listing_photos`

```sql
CREATE TABLE listing_photos (
    id              TEXT PRIMARY KEY,
    pet_id          TEXT NOT NULL REFERENCES pet_rows(id),
    user_id         TEXT NOT NULL REFERENCES users(id),
    file_path       TEXT NOT NULL,              -- storage path (local or S3)
    file_size       INTEGER,
    mime_type       TEXT,
    width           INTEGER,
    height          INTEGER,
    position        INTEGER DEFAULT 0,          -- display order
    created_at      DATETIME NOT NULL
);
```

---

## Authentication System

### Registration Options

1. **Email + Password**
   - Email verification required before posting
   - Password requirements: 8+ chars, no common passwords
   - Hash with `argon2id` (preferred) or `bcrypt`

2. **OAuth2 Social Login**
   - Google Sign-In
   - Facebook Login
   - Apple Sign-In
   - Auto-create account on first OAuth login
   - Link multiple OAuth providers to one account

### Session Management

```
POST /auth/register          # Email + password signup
POST /auth/login             # Email + password login
POST /auth/logout            # Invalidate session
GET  /auth/verify/{token}    # Email verification
POST /auth/forgot-password   # Password reset request
POST /auth/reset-password    # Password reset with token

GET  /auth/oauth/{provider}  # OAuth redirect (Google, Facebook, Apple)
GET  /auth/callback/{provider} # OAuth callback
```

**Session tokens:**
- Stored in secure httponly cookies (`SameSite=Strict`)
- 30-day expiry with sliding window
- Stored in `user_sessions` table for server-side revocation
- IP and user-agent tracked for suspicious login detection

### JWT for API Access (Optional)

For mobile apps or third-party integrations:
```
POST /api/auth/token         # Exchange credentials for JWT
```
- Short-lived access tokens (15 min)
- Long-lived refresh tokens (30 days)
- Refresh token rotation on use

---

## User Listing Flow

### Creating a Listing

```
1. User logs in
2. Clicks "Report Lost Pet" or "Report Found Pet"
3. Fills out form:
   - Pet type (dog, cat, etc.) [required]
   - Record type (lost, found, sighting) [required]
   - Name, breed, color, gender, size [as available]
   - Location (address or map pin) [required]
   - Date lost/found [required]
   - Description [required]
   - Photos (up to 5, max 5MB each) [recommended]
   - Contact preference (email, phone, in-app messages)
   - Microchip number [optional]
   - Distinctive features [optional]
4. Listing enters moderation queue (status: "pending")
5. Auto-approved if user has 3+ approved listings, otherwise manual review
6. On approval:
   - Listing goes live (visible on map and listings)
   - Matching engine runs against existing records
   - User notified of any matches
```

### Managing Listings

```
GET  /my/listings                    # User's listings
GET  /my/listings/{id}/edit          # Edit form
POST /my/listings/{id}/edit          # Update listing
POST /my/listings/{id}/resolve       # Mark as resolved
POST /my/listings/{id}/photos       # Upload photos
DELETE /my/listings/{id}/photos/{photo_id}  # Remove photo
```

### Moderation

```
GET  /admin/moderation               # Moderation queue
POST /admin/moderation/{id}/approve  # Approve listing
POST /admin/moderation/{id}/reject   # Reject with reason
POST /admin/moderation/{id}/flag     # Flag for review
```

**Auto-moderation rules:**
- Reject listings with no description or location
- Flag listings with phone numbers in description (spam indicator)
- Flag duplicate submissions (same user, similar content within 24h)
- Auto-approve trusted users (3+ previously approved listings)

---

## Photo Upload System

### Upload Flow

```
1. User selects photos (max 5 per listing)
2. Client-side: validate type (JPEG/PNG/WebP), resize if > 2000px
3. Upload to server via multipart form
4. Server-side:
   a. Validate file type (magic bytes, not just extension)
   b. Strip EXIF metadata (privacy: remove GPS, camera info)
   c. Resize to standard dimensions (800px max width)
   d. Generate thumbnail (200x200)
   e. Store in designated directory or S3 bucket
   f. Create listing_photos record
```

### Storage Options

| Option | Dev | Prod | Notes |
|--------|-----|------|-------|
| Local filesystem | `data/uploads/` | No | Simple, not scalable |
| S3-compatible | MinIO | AWS S3 / Cloudflare R2 | Scalable, CDN-ready |
| Database BLOB | SQLite | No | Not recommended |

Recommended: Local for dev, S3-compatible for prod with CloudFront/R2 CDN.

---

## Notification System

### Notification Types

| Type | Trigger | Channel |
|------|---------|---------|
| `match_found` | Matching engine finds a potential match | Email + in-app |
| `listing_approved` | Moderator approves listing | In-app |
| `listing_rejected` | Moderator rejects listing | Email + in-app |
| `new_message` | Another user sends a message | Email + in-app |
| `listing_expiring` | Listing approaching 90-day auto-archive | Email |

### Email Delivery

Options for transactional email:
- **SendGrid** - Reliable, good free tier
- **AWS SES** - Cheap at scale
- **Resend** - Developer-friendly API

---

## Roles & Permissions

| Action | User | Moderator | Admin |
|--------|------|-----------|-------|
| Create listing | Yes | Yes | Yes |
| Edit own listing | Yes | Yes | Yes |
| Edit any listing | No | Yes | Yes |
| Delete own listing | Yes | Yes | Yes |
| Delete any listing | No | Yes | Yes |
| Review moderation queue | No | Yes | Yes |
| Confirm/reject matches | No | Yes | Yes |
| View admin dashboard | No | No | Yes |
| Manage users | No | No | Yes |
| Ban users | No | No | Yes |

---

## API Extensions

### New Endpoints

```
# Authentication
POST /auth/register
POST /auth/login
POST /auth/logout
GET  /auth/verify/{token}
POST /auth/forgot-password
POST /auth/reset-password
GET  /auth/oauth/{provider}
GET  /auth/callback/{provider}

# User Profile
GET  /my/profile
POST /my/profile
GET  /my/notifications
POST /my/notifications/{id}/read

# User Listings
GET  /my/listings
POST /my/listings/new
GET  /my/listings/{id}/edit
POST /my/listings/{id}/edit
POST /my/listings/{id}/resolve
POST /my/listings/{id}/photos
DELETE /my/listings/{id}/photos/{photo_id}

# Messaging
GET  /my/messages
GET  /my/messages/{thread_id}
POST /my/messages/{thread_id}/reply
POST /pets/{pet_id}/contact            # Start conversation about a pet

# Moderation (admin/moderator)
GET  /admin/moderation
POST /admin/moderation/{id}/approve
POST /admin/moderation/{id}/reject
```

---

## Implementation Phases

### Phase 1: Foundation
- [ ] Add user table and session management
- [ ] Implement email + password registration/login
- [ ] Add user_id column to pet_rows
- [ ] Create listing submission form
- [ ] Basic moderation queue

### Phase 2: Social & Communication
- [ ] OAuth2 social login (Google, Facebook)
- [ ] In-app messaging between users
- [ ] Email notifications for matches
- [ ] User profile pages

### Phase 3: Polish & Scale
- [ ] Photo upload with S3 storage
- [ ] Auto-moderation rules
- [ ] Trusted user auto-approval
- [ ] Mobile-responsive listing form
- [ ] Listing expiry and auto-archive

### Phase 4: Community
- [ ] Public user profiles with listing history
- [ ] "Reunited" success stories page
- [ ] Share to social media buttons
- [ ] Community stats (pets reunited counter)
- [ ] Volunteer moderator program

---

## Technical Considerations

### Password Security
```python
# Use argon2id for password hashing
from argon2 import PasswordHasher
ph = PasswordHasher(
    time_cost=3,
    memory_cost=65536,    # 64MB
    parallelism=4,
    hash_len=32,
    salt_len=16
)
hash = ph.hash(password)
ph.verify(hash, password)  # raises on mismatch
```

### Session Cookie Security
```python
response.set_cookie(
    key="session",
    value=session_token,
    httponly=True,          # not accessible via JavaScript
    secure=True,            # HTTPS only
    samesite="strict",      # no cross-site requests
    max_age=30*24*3600,     # 30 days
    path="/"
)
```

### Rate Limiting for User Actions
```
Registration: 3 per hour per IP
Login attempts: 5 per 15 min per IP (then lockout)
Listing creation: 5 per day per user
Photo upload: 25 per day per user
Messages: 50 per day per user
```

### Data Integrity
- User listings use `source = "user_submission"` and `source_id = listing UUID`
- This allows them to flow through the existing matching pipeline unchanged
- User listings are geocoded the same way as scraped listings
- Staleness checks skip user-submitted listings (users manage their own)
