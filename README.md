# Email Marketing Management System — Backend

FastAPI + MongoDB backend for an internal email marketing management system.
Handles auth, employees, sending profiles, lead uploads, dashboards, logs, and
n8n campaign integration. **Does not send emails itself** — n8n owns delivery
via Gmail SMTP; this backend just supplies data and receives status callbacks.

## Stack

FastAPI · Motor (async MongoDB) · Pydantic v2 · JWT (python-jose) · Passlib (bcrypt)
· pandas (CSV processing) · httpx (n8n webhook calls) · slowapi (rate limiting)

## Project layout

```
backend/
  main.py                  # app entrypoint, router + middleware wiring
  requirements.txt
  .env.example
  app/
    core/                  # config, security (JWT/hashing), dependencies, exceptions, rate limiting
    database/               # Mongo connection + index creation
    middleware/             # request logging, global error handlers
    utils/                  # CSV parsing, email validation, pagination, doc serialization
    schemas/                # shared response envelopes
    auth/                   # login / refresh / logout
    users/                  # base user accounts (admin creates via employees module)
    employees/               # employee CRUD (admin-only), links to a user account
    profiles/                # sending profiles (max 5 per employee), filter options
    emails/                  # CSV lead upload, duplicate detection, filtered lookups
    dashboard/               # employee + admin analytics (aggregation pipelines)
    logs/                    # activity logs + n8n campaign-completion webhook
    n8n/                     # n8n-facing endpoints (shared-secret auth, not JWT)
    reports/                 # CSV export of a lead list
```

## Setup

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then edit JWT_SECRET_KEY, MONGO_URI, N8N_API_KEY, etc.
uvicorn main:app --reload
```

Requires a running MongoDB instance reachable at `MONGO_URI`. On startup the
app creates all required indexes automatically (see `app/database/indexes.py`).

API docs: `http://localhost:8000/docs`

## Creating the first admin

There's no public signup endpoint by design (internal tool). Seed the first
admin directly, e.g. via a one-off script or the Mongo shell, hashing the
password with `passlib`'s bcrypt scheme so it matches what `/auth/login`
expects — or temporarily call `app.users.service.create_user` with
`role="admin"` from a Python shell against your running app's DB.

## Auth model

- `POST /auth/login` → `{ accessToken, refreshToken }`
- Access token: short-lived (`ACCESS_TOKEN_EXPIRE_MINUTES`), sent as
  `Authorization: Bearer <token>` on every protected request.
- Refresh token: longer-lived (`REFRESH_TOKEN_EXPIRE_DAYS`); `POST /auth/refresh`
  issues a new pair. `POST /auth/logout` revokes a refresh token
  (stored in a `revoked_tokens` collection).
- Roles: `admin` (manages employees/profiles/sees everything) and `employee`
  (scoped to their own employee record, profiles, and leads).

## n8n integration

n8n does **not** use JWTs. Every `/n8n/*` route and the `/logs/campaign`
callback are guarded by a shared secret sent as the `X-API-KEY` header,
matched against `N8N_API_KEY` in `.env`. Configure n8n's HTTP Request nodes
to send that header.

Flow:
1. Employee/admin (or an automation) calls `POST /n8n/start-campaign` with a
   `profileId`. The backend validates the profile is active, logs
   `CAMPAIGN_STARTED`, and posts the profile's Gmail account + filter options
   to `N8N_WEBHOOK_URL`.
2. n8n reads `GET /n8n/profiles/{profileId}` and
   `GET /n8n/profiles/{profileId}/emails` to get the sending config and the
   matching, non-duplicate lead list (capped at the profile's `dailyLimit`).
3. After sending, n8n calls back `POST /logs/campaign` with
   `{ profileId, sentCount, runDate }`, which the backend records as a
   `CAMPAIGN_COMPLETED` log entry used by the dashboards.

## Duplicate detection

Scoped **per employee** (not globally) — the same email address can exist for
two different employees, but a single employee's list is deduplicated on
upload. Duplicates are skipped by default; pass
`?insertDuplicates=true` on `POST /emails/upload` to insert them anyway,
flagged `isDuplicate: true`.

## Dashboard date ranges

`GET /dashboard/employee` and `GET /dashboard/admin` accept:
`?preset=today|yesterday|last_7_days|last_month|custom` and, for `custom`,
`&startDate=YYYY-MM-DD&endDate=YYYY-MM-DD`. `todayUploadCount` and
`last7DaysUploadCount` on the employee dashboard are always fixed windows
regardless of the chosen preset; every other stat respects the selected range.

## Known simplifications (call these out to your team before production)

- No multi-document transactions on employee creation (Mongo standalone
  doesn't support them without a replica set) — best-effort rollback is used
  instead if the employee doc insert fails after the user doc is created.
- Rate limiting is a single global per-IP limit (`RATE_LIMIT_PER_MINUTE`);
  no per-route tuning yet.
- No CSV virus/malware scanning — add one at the infra layer if leads come
  from untrusted sources.
