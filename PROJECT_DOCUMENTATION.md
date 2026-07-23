# Cold Email Marketing Management System — Complete Project Documentation

---

## 1. Project Overview

This is a **multi-tenant internal cold email marketing platform** built for an organization where multiple employees independently manage their own email outreach campaigns. An admin oversees all employees and their activity.

The system handles the **entire campaign lifecycle**:
1. Uploading a master database of leads (CSV/Excel)
2. Creating "Profiles" that define who to email and how
3. Generating a filtered working list from the master database
4. Sending emails automatically (with personalization, attachments, and rate limiting)
5. Scheduling campaigns to run in the future (daily, weekly, or once)
6. Reporting on performance through dashboards and CSV exports

---

## 2. Technology Stack

| Layer | Technology | Purpose |
|---|---|---|
| **Runtime** | Python 3.11 | Core language |
| **Web Framework** | FastAPI 0.115 | HTTP + WebSocket server |
| **ASGI Server** | Uvicorn (with `standard` extras) | Runs the FastAPI app with async support |
| **Database** | MongoDB (standalone) | Primary data store for all collections |
| **DB Driver** | Motor 3.5 (async) | Asynchronous MongoDB driver (never blocks event loop) |
| **Schema Validation** | Pydantic v2 | Request/response validation and serialization |
| **Auth** | python-jose (JWT, HS256) | Stateless access tokens |
| **Password Hashing** | Passlib (pbkdf2_sha256) | Hashes user login passwords |
| **Email Encryption** | Cryptography (Fernet) | AES-256 symmetric encryption of SMTP app passwords |
| **Email Sending** | smtplib (stdlib) | Direct SMTP connection to Gmail or any SMTP server |
| **Rate Limiting** | slowapi 0.1.9 | Per-IP request rate limiting |
| **Data Processing** | pandas 2.2, openpyxl 3.1 | CSV/Excel parsing on upload |
| **HTTP Client** | httpx 0.27 | Async HTTP requests |
| **Environment** | pydantic-settings | Loads `.env` file into `Settings` class |

---

## 3. Project Directory Layout

```
backend/
├── main.py                     # App entrypoint: middleware, routers, lifespan
├── requirements.txt            # Python dependencies
├── .env                        # Environment variables (secrets)
└── app/
    ├── auth/                   # Login, refresh token, logout
    ├── users/                  # User account CRUD (admin managed)
    ├── employees/              # Employee profiles (linked to users)
    ├── email_accounts/         # SMTP credentials store per employee
    ├── email_master/           # Global permanent lead database
    ├── profiles/               # Sending profiles (templates + filters)
    ├── profile_emails/         # Working email list per profile (campaign fuel)
    ├── campaigns/              # Campaign lifecycle + scheduler
    ├── campaign_engine/        # Email sending loop (worker + SMTP sender)
    ├── templates/              # Reusable email templates
    ├── dashboard/              # Analytics & aggregations
    ├── logs/                   # Activity logs viewer
    ├── notifications/          # In-app notifications + WebSocket live push
    ├── reports/                # CSV export endpoints
    ├── options/                # Dropdown data for frontend (employees/profiles/campaigns)
    ├── core/                   # Config, security, dependencies, exceptions, rate limit
    ├── database/               # MongoDB connection + index creation on startup
    ├── middleware/             # Request logging, audit logging, error handlers
    ├── schemas/                # Shared response envelopes (ApiResponse)
    └── utils/                  # CSV parser, personalizer, pagination, serializer
```

---

## 4. Authentication & Authorization

### How It Works
The system uses **stateless JWT authentication** with two tokens:
- **Access Token** (short-lived, 30 minutes by default): Used on every API request as `Authorization: Bearer <token>`
- **Refresh Token** (long-lived, 7 days by default): Used only to get a new access token pair from `POST /auth/refresh`

When a user logs out, the refresh token is stored in a `revoked_tokens` MongoDB collection so it cannot be reused.

### Token Payload (JWT Claims)
```json
{
  "sub": "<userId>",
  "role": "admin | employee",
  "employee_id": "<employeeId>",
  "type": "access | refresh",
  "iat": 1234567890,
  "exp": 1234567890
}
```

### Roles and Access
| Role | Access |
|---|---|
| `admin` | Can see and manage all employees, all profiles, all campaigns, all data. Must always pass `?employeeId=` to act on behalf of an employee. |
| `employee` | Scoped to their own data only. Cannot access other employees' data. |

### The `employeeId` Query Parameter
A unique admin feature — almost every endpoint accepts `?employeeId=<id>`. This allows an admin to view or modify data on behalf of a specific employee without needing to log in as that employee.

### SMTP Password Security
Employee Gmail app passwords are **never stored in plaintext**. When an email account is added:
1. The password is encrypted using `Fernet` (AES-256-CBC) with a key derived from `PASSWORD_ENCRYPTION_KEY` in `.env`
2. The encrypted blob is stored in MongoDB
3. Only at send time is the password decrypted, used, and immediately discarded from memory

---

## 5. Module Deep-Dive

### 5.1 Auth Module (`app/auth/`)
**Flow**:
1. `POST /auth/login`: Takes `{email, password}`. Verifies password using `passlib.verify_password()`. If valid, creates an access token and refresh token using `python-jose`. Returns both.
2. `POST /auth/refresh`: Verifies the refresh token is not in `revoked_tokens` and not expired. Issues a new token pair.
3. `POST /auth/logout`: Adds the refresh token to `revoked_tokens` collection, making it permanently invalid.

---

### 5.2 Employees Module (`app/employees/`)
- Only admins can create, update, or delete employees (enforced via `require_admin` dependency).
- When an employee is created, **two records are created**: a `users` record (for login/auth) and an `employees` record (for linking to profiles, campaigns, etc.). These are linked by `userId`.
- There is a best-effort rollback: if the `employees` insert fails after the `users` insert succeeds, the `users` record is deleted to avoid orphaned accounts.
- `GET /employees/me`: Any logged-in employee can get their own employee record.

---

### 5.3 Email Accounts Module (`app/email_accounts/`)
- SMTP password is immediately encrypted with Fernet (AES-256) before being written to MongoDB.
- `POST /email-accounts/{id}/test`: Opens a real SMTP connection, attempts login, then closes without sending. Lets employees verify their app password.
- A rate counter (`dailySentCount`, `lastResetDate`) tracks how many emails this account has sent today. The campaign worker calls `record_send()` to increment this on every successful send.

---

### 5.4 Email Master Module (`app/email_master/`)
**Purpose**: The **permanent global lead database**. Shared across all employees.

**Upload flow**:
1. Accept `.csv`, `.xlsx`, or `.xls` file via multipart form
2. Use `pandas` to parse into rows
3. Validate emails with `email-validator`
4. Generate a unique `upload_batch` UUID to group this upload
5. Query MongoDB for all emails in batch that already exist
6. Build a Python `set` of existing emails for O(1) lookup speed
7. Skip or flag duplicates based on `insertDuplicates` parameter
8. Tag each row with optional `mailSource` (Google Scholar / University / Other)
9. Bulk insert with `insert_many()` in a single MongoDB operation

**Deduplication**: Globally scoped — the same email can only exist once in the entire collection.

**Columns stored per lead**: `email`, `fullName`, `company`, `website`, `country`, `state`, `city`, `domain`, `industry`, `designation`, `phone`, `linkedin`, `uploadBatch`, `isDuplicate`, `employeeId`, `uploadedBy`, `uploadedByName`, `mailSource`, `inProfileEmails`, `usedByEmployeeId`, `createdAt`

---

### 5.5 Profiles Module (`app/profiles/`)
**Purpose**: A "Profile" is a reusable sending configuration. It defines who to send to (filters), what to say (templates), from which Gmail account, and how fast to send.

- Maximum **5 profiles per employee** (enforced in service)
- Profile names must be unique per employee
- Must be **activated** before a campaign can start

**Profile fields**:
- `gmailAccount`: Which email account to send from
- `signature`: Appended to every email
- `filters`: `{country, domain, industry, company, type, mailSource}` — filter leads from Email Master
- `filterLimit`: Maximum leads to pull
- `templates`: Array with `{subject, body, weight}` — weight enables A/B testing via `random.choices()`
- `sendingOptions`: `{dailyLimit, delayMin, delayMax}` — rate limits and random delays in seconds
- `attachments`: Files attached to every email in the campaign

---

### 5.6 Profile Emails Module (`app/profile_emails/`)
**Purpose**: The **working email list** for a specific profile. Populated by filtering Email Master. This is the campaign's fuel.

**Generate List** (`POST /profile-emails/{id}/generate`):
1. Load profile's filters
2. Query `email_master` with `$in` operators
3. Exclude already-sent or already-failed emails for this profile
4. Apply `filterLimit`
5. Bulk insert as `pending` rows

**Send Status Lifecycle**: `pending` → `sending` → `sent` / `failed` / `skipped`

---

### 5.7 Campaigns Module (`app/campaigns/`)

**Campaign Statuses**: `pending`, `scheduled`, `processing`, `running`, `paused`, `completed`, `failed`, `aborted`

**Immediate Campaign** (`POST /campaigns/start`):
1. Validate profile is active and has pending emails
2. Create campaign document with `status: running`
3. Tag all pending profile_emails with this campaign's ID
4. Add `run_campaign()` to FastAPI `BackgroundTasks` — runs immediately in background

**Scheduled Campaign** (`POST /campaigns/schedule`):
- Accepts `recurrenceType` (once/daily/weekly), `scheduledTimeLocal` (HH:MM), `timezoneOffsetMinutes`, `recurrenceDays`, `scheduledDateLocal`
- `calculate_next_run()` computes exact UTC time from local time + offset
- Saves with `status: scheduled` and `scheduledFor: <utc_datetime>`
- `timezoneOffsetMinutes` is saved to the document so recurring campaigns always reschedule in the correct local timezone

**The Scheduler** (`scheduler.py`):
- Called by Linux cron every minute via `POST /campaigns/process-scheduled`
- Finds campaigns where `status == "scheduled"` AND `scheduledFor <= now(UTC)`
- Uses **atomic `find_one_and_update`** to transition `scheduled → processing` (prevents duplicate execution)
- Dispatches each campaign with `asyncio.create_task()` — **all 20 campaigns run in parallel**, not sequentially
- After completion: `once` → `completed`; `daily`/`weekly` → recalculates next run and resets to `scheduled`

---

### 5.8 Campaign Engine (`app/campaign_engine/`)

**Worker loop** (`run_campaign` in `worker.py`):
1. Load campaign + profile from MongoDB
2. Decrypt SMTP credentials via Fernet
3. Enter `while True` loop:
   - Check if paused → exit
   - Fetch next batch of 50 `pending` profile_emails
   - For each lead:
     - Mark as `sending`
     - Replace placeholders (`[name]`, `[company]`, etc.) with lead data
     - Select template using A/B weighted `random.choices()`
     - Build MIME email (plain text + HTML + attachments)
     - Call `send_email()` → wraps `smtplib` in `asyncio.run_in_executor()` (thread pool) so the event loop is never blocked
     - On success: mark `sent`, increment counter, push WebSocket progress event
     - On failure: mark `failed`. If auth fails 3× → abort entire campaign
     - `await asyncio.sleep(random.randint(delay_min, delay_max))` between sends
4. Finalize campaign when done

**SMTP Sender** (`sender.py`):
- Builds `MIMEMultipart` with `text/plain` + `text/html` parts
- Attachment missing from disk → raises `FileNotFoundError` (email fails, not sent silently)
- Supports STARTTLS (port 587) and SSL (port 465)

---

### 5.9 Notifications Module (`app/notifications/`)

**WebSocket flow**:
1. Frontend connects: `WS /notifications/ws?token=<access_token>`
2. Server validates JWT, identifies user/role
3. Connection registered in in-memory `ConnectionManager`
4. Campaign worker pushes live events: `{type: "campaign_progress", campaignId, event: "sent", totalSent, totalFailed}`
5. Admins automatically receive all employee campaign events

**REST notifications**: List, mark-as-read, mark-all-as-read.

**Types**: `info`, `success`, `warning`, `error`

---

### 5.10 Personalizer (`app/utils/personalizer.py`)

Pure-Python placeholder replacement. No AI. Supported placeholders (use `[placeholder]` in templates):

`[name]`, `[full_name]`, `[company]`, `[industry]`, `[designation]`, `[country]`, `[domain]`, `[city]`, `[state]`, `[website]`, `[linkedin]`, `[phone]`, `[email]`

`[name]` → first word of `fullName`, capitalized. Defaults to `"there"` if empty.

---

## 6. MongoDB Collections Summary

| Collection | Description | Key Indexes |
|---|---|---|
| `users` | Login accounts | `email` (unique) |
| `employees` | Employee profiles | `userId` (unique) |
| `email_master` | Global lead database | `(employeeId, email)` unique, `mailSource`, `country`, `domain` |
| `profiles` | Sending profiles | `(employeeId, profileName)` unique |
| `profile_emails` | Working list per profile | `(profileId, sendStatus, createdAt)` compound |
| `campaigns` | Campaign documents | `(status, scheduledFor)` for scheduler |
| `email_accounts` | SMTP credentials (encrypted) | `(employeeId, email)` unique |
| `templates` | Reusable templates | `employeeId`, `isGlobal` |
| `logs` | Activity logs | `employeeId`, `createdAt`, `action` |
| `notifications` | In-app notifications | `(employeeId, isRead, createdAt)` compound |
| `revoked_tokens` | Invalidated refresh tokens | `token` (unique) |

---

## 7. Cron Job Setup

To trigger the scheduler every minute on Linux:
```bash
* * * * * curl -X POST http://localhost:8000/campaigns/process-scheduled
```

> [!WARNING]
> The `/campaigns/process-scheduled` endpoint currently has no auth guard. In production, firewall it so only the server itself can call it.
