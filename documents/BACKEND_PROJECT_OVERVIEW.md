# Email Marketing Backend — Project Overview

This document describes the backend as it is implemented in this repository. It is intended for backend developers, frontend integrators, operations staff, and maintainers who need a single place to understand the system, its architecture, its data flow, and its operational boundaries.

> **Source-of-truth note:** This overview follows the modules currently wired by [`main.py`](../main.py). Some older project notes and the root README describe an n8n-based delivery flow. The current campaign worker in this repository sends email directly through SMTP; n8n is not part of the active application wiring described below.

## Contents

1. [Project purpose and scope](#1-project-purpose-and-scope)
2. [Technology stack](#2-technology-stack)
3. [Architecture](#3-architecture)
4. [Application startup and request lifecycle](#4-application-startup-and-request-lifecycle)
5. [Source tree and module responsibilities](#5-source-tree-and-module-responsibilities)
6. [Identity, roles, and authorization](#6-identity-roles-and-authorization)
7. [Data model and MongoDB collections](#7-data-model-and-mongodb-collections)
8. [Lead and campaign workflows](#8-lead-and-campaign-workflows)
9. [API surface](#9-api-surface)
10. [Configuration and secrets](#10-configuration-and-secrets)
11. [Errors, logging, notifications, and observability](#11-errors-logging-notifications-and-observability)
12. [Local development and operations](#12-local-development-and-operations)
13. [Testing and maintenance notes](#13-testing-and-maintenance-notes)
14. [Related documentation](#14-related-documentation)

## 1. Project purpose and scope

The backend provides APIs for an internal email marketing platform. It manages users and employees, sender accounts, a lead database, profile-based audience lists, email templates, campaign execution and scheduling, notifications, dashboards, settings, and exports.

The main product workflow is:

1. An administrator provisions user and employee records.
2. An employee or administrator configures an SMTP sender account.
3. Leads are uploaded to the email master database.
4. A profile defines sender, message content, audience filters, and sending options.
5. Matching master records are copied to the profile's working email list.
6. A campaign sends eligible records and records per-recipient results.
7. Campaign progress is persisted and made available through API responses, dashboards, logs, and WebSocket notifications.

### In scope

- FastAPI HTTP API and notification WebSocket
- MongoDB persistence through Motor
- JWT-based authentication and role/access-level checks
- CSV/lead handling, filtering, and export
- Profile and campaign management
- Direct SMTP email delivery from the backend campaign worker
- Recurring and one-time campaign scheduling

### Not the active delivery design

- The active worker does not call an n8n webhook. It loads sender credentials from MongoDB and uses the SMTP sender in `app/campaign_engine/sender.py`.
- Message personalization is local placeholder replacement; it does not call LangChain or an LLM.
- Campaign execution uses in-process FastAPI background tasks and an in-process scheduler loop. There is no external durable task queue in the wired application.

## 2. Technology stack

| Concern | Implementation |
|---|---|
| Language | Python |
| HTTP / WebSocket application | FastAPI and Starlette |
| ASGI server | Uvicorn |
| Database | MongoDB |
| Async database driver | Motor, with PyMongo types |
| Data validation and settings | Pydantic v2 and `pydantic-settings` |
| Authentication tokens | JWT via `python-jose` |
| Password hashing | Passlib `pbkdf2_sha256` context |
| SMTP credential encryption | Fernet via `cryptography` |
| Email transport | Python `smtplib`, run in a thread pool from async code |
| Rate limiting | SlowAPI limiter is configured by remote client address; enforcement is not currently wired as global middleware or route decorators |
| Tabular input/output | pandas, `python-multipart`, and openpyxl |
| HTTP client dependency | httpx (present in the pinned requirements; not the direct campaign delivery path) |

Exact pinned dependencies are in [`requirements.txt`](../requirements.txt).

## 3. Architecture

The application follows a feature-module architecture. Each feature generally owns its router, request/response schemas, service logic, and document-building helpers. Routers validate and route HTTP requests; services apply business rules and access MongoDB; shared infrastructure handles authentication, database lifecycle, serialization, errors, and middleware.

```text
Web client / API consumer
          │
          ├── HTTP requests
          └── WebSocket connection
                  │
                  ▼
        FastAPI application (main.py)
          ├── CORS and rate-limit exception handling
          ├── request / audit middleware
          ├── exception handlers
          └── feature routers
                  │
                  ▼
        Router → schema / dependency → service
                  │
          ┌───────┴────────┐
          ▼                ▼
      MongoDB          Campaign worker
    (Motor async)          │
                           ├── SMTP sender
                           ├── send counters / logs
                           └── notification service
                                    │
                                    ▼
                          WebSocket connections
```

### Architectural boundaries

- **Transport layer:** `app/*/router.py` exposes route operations and composes authentication, query/body validation, and response envelopes.
- **Validation layer:** feature schemas in `app/*/schema.py`, plus common schemas in `app/schemas/`, define request and response shapes.
- **Business/data layer:** feature `service.py` modules contain MongoDB queries, authorization-aware ownership checks, document creation, and workflow rules.
- **Persistence layer:** `app/database/mongodb.py` owns the Motor client/database lifecycle; `indexes.py` creates indexes; `migrations.py` currently performs the admin access-level backfill.
- **Background execution:** campaign requests enqueue work using FastAPI `BackgroundTasks`. Scheduled work is discovered by the scheduler loop in `main.py` and `app/campaigns/scheduler.py`.
- **External delivery:** `app/campaign_engine/sender.py` delivers mail through SMTP. SMTP I/O runs in an executor so blocking socket operations do not block the event loop.
- **Real-time updates:** `app/notifications/websocket.py` maintains process-local WebSocket connection channels.

## 4. Application startup and request lifecycle

### Startup and shutdown

The application is created in [`main.py`](../main.py). Its FastAPI lifespan handler:

1. Creates the MongoDB client and selects `MONGO_DB_NAME`.
2. Creates configured indexes.
3. Runs `migrate_admin_access_levels()` to backfill missing admin `accessLevel` fields with `full`.
4. Starts an asyncio scheduler task that waits 60 seconds between calls to `process_scheduled_campaigns()`.
5. On shutdown, cancels the scheduler task and closes the MongoDB client.

The root health check is `GET /health`; it returns a service-health response and version string. It does not perform an explicit MongoDB ping.

### HTTP request lifecycle

1. CORS and request handling middleware receive the request.
2. Request logging assigns an `X-Request-ID` response header and logs method, path, status, and duration.
3. Admin audit middleware records modifying requests made by admins when it can decode an admin JWT.
4. FastAPI resolves route dependencies, including bearer authentication and authorization.
5. The router validates input and calls the feature service.
6. The service reads or writes MongoDB collections.
7. The router returns a common `ApiResponse` envelope where defined.
8. Exception handlers convert HTTP, validation, and unhandled errors into JSON responses.

### Campaign execution lifecycle

- Immediate campaign start creates a campaign record, then schedules `run_campaign(campaign_id)` as a FastAPI background task.
- The worker claims a campaign with a worker token before processing to prevent concurrent workers from handling the same campaign.
- Email records are processed in batches, personalized, sent, and updated with outcome/counter information.
- Pause and resume operations update campaign state; resume queues the worker again.
- Scheduled campaigns are queried by due time and transitioned atomically before execution.

FastAPI background tasks run inside the API process. They are not persisted independently from that process; a process restart can interrupt in-flight work. For multi-instance production deployment, review scheduling and worker coordination before scaling horizontally.

## 5. Source tree and module responsibilities

```text
backend/
├── main.py
├── requirements.txt
├── .env.example
├── app/
│   ├── auth/                 # login, refresh, logout
│   ├── users/                # user accounts and roles
│   ├── employees/            # employee records and ownership context
│   ├── email_accounts/       # sender account configuration and encrypted credentials
│   ├── email_master/         # lead upload, search, filters, and master records
│   ├── emails/               # separate /emails feature module; not included by main.py
│   ├── profiles/             # sender, content, filtering, and profile configuration
│   ├── profile_emails/       # working email rows associated with profiles
│   ├── templates/            # reusable message templates
│   ├── campaigns/            # campaign lifecycle, scheduling, and cleanup
│   ├── campaign_engine/      # campaign worker and SMTP sender
│   ├── send_stats/           # send-statistics document helpers
│   ├── dashboard/            # employee/admin analytics
│   ├── logs/                  # activity and campaign logs
│   ├── reports/               # CSV exports
│   ├── notifications/        # persisted notifications and WebSocket delivery
│   ├── settings/              # application-level configurable records
│   ├── options/               # option-list endpoints
│   ├── core/                  # configuration, security, dependencies, exceptions, rate limit
│   ├── database/              # MongoDB lifecycle, indexes, migrations
│   ├── middleware/            # request logging, admin audit, exception handlers
│   ├── schemas/               # shared response and pagination schemas
│   └── utils/                 # CSV handling, email validation, pagination, serialization, personalization
├── documents/                 # project and supporting documentation
└── tests/                     # backend regression tests
```

The `app/emails` package is present in the source tree, but `main.py` does not include its router. The active lead upload and query API is `app/email_master` under `/email-master`.

### Feature module pattern

Most feature packages use the following files:

- `router.py`: endpoint paths, HTTP methods, dependencies, and response construction.
- `schema.py`: Pydantic input/output models.
- `service.py`: domain behavior and MongoDB operations.
- `model.py`: enum values and document-construction helpers where applicable.

This is a common pattern rather than a mandatory rule; some packages, such as `reports`, `options`, and `campaign_engine`, have a different shape.

## 6. Identity, roles, and authorization

### User roles

User records support:

- `super_admin`
- `admin`
- `employee`

Users also have an `active` or `inactive` status. Admin records have an access level:

- `full`: broad administrative access, subject to the branch/employee scoping rules implemented by the dependencies.
- `partial`: restricted administrative access, typically scoped to assigned employees.

Role and access-level decisions are centralized in `app/core/dependencies.py`. The `resolve_employee_context` and `resolve_write_employee_context` helpers are used to determine which employee's data a request may read or mutate. Some routes accept an `employeeId` query parameter for an authorized administrator to select a target employee.

### Authentication flow

1. `POST /auth/login` looks up the user by email, verifies the stored password hash, and rejects inactive accounts.
2. A successful login returns an access token and refresh token, plus identity metadata.
3. Protected HTTP routes use `Authorization: Bearer <access-token>`.
4. `POST /auth/refresh` validates the refresh token and checks whether it is stored as revoked before issuing a new token pair.
5. `POST /auth/logout` stores the supplied refresh token in `revoked_tokens`.

JWT claims include subject, role, access level, token type, issue time, and expiry. Employee tokens may also carry `employee_id`. Access-token validity is checked by the bearer dependency; refresh tokens are not accepted as access tokens.

### Passwords and SMTP credentials

- User login passwords are stored using the configured Passlib password hash.
- SMTP passwords are encrypted/decrypted with Fernet using a key derived from `PASSWORD_ENCRYPTION_KEY`.
- The JWT signing key and SMTP encryption key are different settings and should both be replaced with strong, deployment-specific secrets.

## 7. Data model and MongoDB collections

MongoDB documents use application-defined field names, generally camelCase, and MongoDB `_id` values. The following collection responsibilities are visible in the model, service, and index code:

| Collection | Purpose and representative relationships |
|---|---|
| `users` | Login identity, email, password hash, role, status, access level, and branch information. |
| `employees` | Employee-specific record linked to a user through `userId`; carries employee code and administrative assignment/scope data. |
| `email_accounts` | Per-employee SMTP sender accounts, connection settings, encrypted credentials, and send-account metadata. |
| `email_master` | Uploaded lead/contact records, upload attribution, duplicate and usage tracking, reply metadata, and contact attributes. |
| `profiles` | Employee-owned sending setup: sender account, message content/templates, signature, attachments, filters, limits, and sending settings. |
| `profile_emails` | Working copy of a master lead for a profile, including send state, campaign association, retry/error information, and message/thread IDs. |
| `campaigns` | Campaign ownership, profile link, state, totals/counters, timestamps, scheduling/recurrence fields, and errors/retries. |
| `templates` | Reusable email templates, including employee ownership, global visibility, and tags. |
| `notifications` | Employee/admin notifications, read status, and timestamps. |
| `logs` | Application activity and campaign-related event records used by logs and analytics. |
| `revoked_tokens` | Refresh tokens invalidated on logout. |
| `audit_logs` | Admin mutation audit records written by audit middleware. |
| `settings` | Configurable settings/options managed through the settings feature. |
| `daily_send_stats` | Daily send-statistics support used by dashboard/statistics features and migration tooling. |

### Relationships

```text
users ──1:1-ish── employees
employees ──1:N── email_accounts
employees ──1:N── profiles ──1:N── profile_emails
profiles ──1:N── campaigns
email_master ──source/reference── profile_emails
profiles ──contain/reference── templates
employees ──1:N── notifications / logs
```

The application uses MongoDB references represented by string IDs and ObjectIds rather than relational foreign keys. Services are responsible for validating ownership and keeping related records consistent.

### Indexing and retention

`app/database/indexes.py` creates indexes at application startup. Notable indexed access patterns include unique user email, employee-to-user association, profile ownership/name, employee/email account uniqueness, profile email status and campaign association, campaign status/scheduled time, and employee notification lookup.

Read notifications have a TTL index configured for deletion eight hours after `readAt`; unread records without a `readAt` value are not covered by that sparse TTL index. Index creation is part of startup, so a database permission or index conflict can prevent successful startup.

## 8. Lead and campaign workflows

### Lead upload and profile-list generation

1. A client uploads lead data through the `/email-master` API.
2. The email-master service parses supported tabular input, validates email data, normalizes fields, and records upload attribution/batch information.
3. Profiles store filter definitions and sending configuration.
4. Profile email generation selects matching master records and creates denormalized working rows in `profile_emails`.
5. Campaign execution mutates the working rows' send state; the master collection contains the reference/source record and usage/reply tracking.

The profile email model defines send states `pending`, `sending`, `sent`, `failed`, and `skipped`. Each row stores the profile, employee, source master record, recipient details, status, message/thread IDs, sent timestamp, error message, and retry count.

### Personalization and sending

The worker constructs an email payload with `app/utils/personalizer.py`. It replaces supported bracketed placeholders from lead data, including `[name]`, `[first_name]`, `[full_name]`, `[university]`, `[industry]`, `[designation]`, `[country]`, `[domain]`, `[city]`, `[state]`, `[website]`, `[linkedin]`, `[phone]`, and `[email]`. It appends the configured signature and produces a basic HTML variant by converting newlines to `<br>`.

Templates can be selected with weighted random selection when more than one eligible template is available. The worker obtains the sender account's credentials, sends via SMTP, and records per-recipient outcomes. SMTP errors are surfaced as failed send results; campaign-level failures are handled by the worker and campaign service.

The worker loads recipients in bounded batches (50 rows per batch in the current implementation) and applies a per-message delay from profile sending settings, with a minimum effective delay of five seconds. This is sequential in-process processing, not a distributed queue.

### Campaign states and scheduling

Campaign status values defined by the campaign model include:

- `pending`
- `running`
- `paused`
- `completed`
- `failed`
- `waiting_for_mails`
- `scheduled`
- `processing`

Immediate campaigns are created and queued to the worker from `/campaigns/start`. Campaigns can be paused and resumed; deleting a running campaign is disallowed by the route's documented behavior. Scheduled campaign requests support one-time and recurring schedule information. The scheduler looks for records with `status = scheduled` and a due `scheduledFor`, and uses an atomic transition to avoid multiple processes claiming the same record simultaneously.

There are two scheduler entry points in the current code:

- The application lifespan starts an internal scheduler loop that checks every 60 seconds.
- `POST /campaigns/process-scheduled` invokes scheduled processing directly. Its current route has no authentication dependency, despite comments that describe automated/cron usage; protect or restrict it at the application or network layer before exposing it publicly.

## 9. API surface

The routers currently included by `main.py` are:

| Route prefix | Main responsibility |
|---|---|
| `/auth` | Login, refresh, logout |
| `/users` | User provisioning and user management |
| `/employees` | Employee records |
| `/email-accounts` | SMTP account configuration, testing, and maintenance |
| `/email-master` | Lead upload, search/filter, dropdown data, and record operations |
| `/profiles` | Profile configuration and activation |
| `/profile-emails` | Generate and manage profile lead working lists |
| `/templates` | Reusable template CRUD and preview |
| `/campaigns` | Campaign start, list/detail, pause/resume, schedule, and scheduler operations |
| `/dashboard` | Employee/admin dashboard and related analytics |
| `/logs` | Activity log retrieval |
| `/reports` | CSV export endpoints |
| `/settings` | Administrative configuration/settings |
| `/notifications` | Notification listing/read actions and WebSocket |
| `/options` | UI option-list endpoints |

`GET /health` is registered directly in `main.py`. Exact request schemas, query parameters, permissions, response fields, and status codes should be read from [`API_REFERENCE.md`](../API_REFERENCE.md) and the relevant router/schema implementation. OpenAPI is available from FastAPI at `/docs` and `/openapi.json` when the application is running.

## 10. Configuration and secrets

Settings are loaded by `app/core/config.py` from environment variables and the backend `.env` file. The `.env` file path is resolved relative to the application source, so startup does not depend on the current working directory.

Important settings defined by the current `Settings` class:

| Setting | Purpose |
|---|---|
| `APP_NAME` | FastAPI title and application name |
| `ENV` | Environment label |
| `MONGO_URI` | MongoDB connection URI |
| `MONGO_DB_NAME` | MongoDB database name |
| `JWT_SECRET_KEY` | JWT signing key |
| `JWT_ALGORITHM` | JWT algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access-token lifetime |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Refresh-token lifetime |
| `PASSWORD_ENCRYPTION_KEY` | Source material for the Fernet SMTP-password key |
| `CORS_ORIGINS` | Parsed CORS origin setting exposed by settings |
| `RATE_LIMIT_PER_MINUTE` | Default per-IP request limit |
| `GMAIL_SMTP_HOST`, `GMAIL_SMTP_PORT` | SMTP fallback defaults |

### Configuration cautions

- Replace development defaults and secrets before deployment. Never commit a populated `.env`.
- Although `CORS_ORIGINS` is defined and parsed, `main.py` currently passes a literal origin allowlist to `CORSMiddleware`; changing only `CORS_ORIGINS` does not update that active allowlist. Keep this implementation and deployment configuration in sync.
- SlowAPI is configured with `RATE_LIMIT_PER_MINUTE` and its exception handler is registered, but the current application does not add SlowAPI middleware or decorate routes with a limit. Do not assume the configured default is an enforced global limit.
- The current Settings class notes that LLM settings were removed. `N8N_*` and `LANGCHAIN_*`/OpenAI entries found in the sample environment file are not active application settings in this configuration.
- CORS and database access should be configured for the actual deployed frontend and trusted network only.

## 11. Errors, logging, notifications, and observability

### API error responses

The global exception handlers return a common JSON shape:

```json
{
  "success": false,
  "message": "Error description",
  "data": null
}
```

Request validation failures use HTTP 422 and include validation details in `data`. Unhandled exceptions are logged server-side and return a generic HTTP 500 response. Normal feature responses use the shared `ApiResponse` schema.

### Logs and request IDs

- Request middleware logs the request method, path, response status, elapsed milliseconds, and generated request ID.
- The request ID is returned in the `X-Request-ID` header.
- Admin audit middleware records modifying HTTP methods (`POST`, `PATCH`, `PUT`, `DELETE`) for requests with a decodable admin JWT, including method, path, query parameters, status, and timestamp.
- Feature-level `logs` records are separate from request logs and audit records.

### Notifications

Notifications are stored in MongoDB and can be listed or marked read through `/notifications`. The WebSocket endpoint is `/notifications/ws`. Connection tracking is held in memory by the current process and is organized into employee/admin channels; it is not shared across multiple application processes.

## 12. Local development and operations

### Prerequisites

- A supported Python runtime compatible with the pinned dependencies.
- Access to a MongoDB deployment.
- SMTP account credentials for testing actual delivery.

### Windows setup

Run the following commands from the backend directory in PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` with the MongoDB URI/database name and strong JWT/encryption secrets. Then start the API:

```powershell
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Useful local URLs:

- API health: `http://127.0.0.1:8000/health`
- Interactive OpenAPI: `http://127.0.0.1:8000/docs`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`

The application creates indexes and applies the admin access-level migration during startup. A MongoDB server reachable with the configured credentials is required.

### Production operational considerations

- Use a production ASGI process manager and explicit worker/process sizing appropriate to the deployment.
- Do not assume in-process background campaign work survives a restart or deploy.
- The scheduler loop starts in every application process. If running multiple API processes, validate scheduler behavior and campaign claiming under that topology.
- The WebSocket manager is process-local; use sticky routing or a shared pub/sub mechanism if connections must span multiple instances.
- Restrict access to scheduler control routes, especially `/campaigns/process-scheduled`.
- Use TLS for API traffic and SMTP where configured; protect database and environment secrets; set backups and retention policies for lead, campaign, and audit data.
- Monitor startup logs, request logs, worker errors, database connectivity, and SMTP failures.

## 13. Testing and maintenance notes

Regression tests are located in `tests/`. They cover campaign completion and SMTP limits, dashboard scoping/history, data normalization, notifications, settings, user/employee access behavior, email-master behavior, and related workflows.

Run the test suite from the backend directory in a development environment with pytest installed:

```powershell
pytest
```

`pytest` is not currently listed in `requirements.txt`, so install/use the repository's development test environment if the command is unavailable.

### Change checklist

When adding or changing a feature:

1. Update the feature router and schema, then implement behavior in its service module.
2. Apply ownership and role checks using shared dependency/context helpers.
3. Add or update MongoDB indexes if query shape or uniqueness requirements change.
4. Add tests for business behavior, authorization scope, and error cases.
5. Update `API_REFERENCE.md` for externally visible API changes.
6. Review the production settings and ensure the OpenAPI contract matches implementation.


