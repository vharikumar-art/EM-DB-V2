# API Endpoints Reference — Cold Email Marketing System

**Base URL**: `http://localhost:8000` (local) or `http://13.206.26.177:5001` (production)  
**Auth**: Add `Authorization: Bearer <access_token>` to every protected request.  
**Interactive Docs**: `http://localhost:8000/docs` (Swagger UI)

---

## Table of Contents
1. [Authentication](#1-authentication)
2. [Employees (Admin Only)](#2-employees-admin-only)
3. [Email Accounts (SMTP)](#3-email-accounts-smtp)
4. [Email Master (Lead Database)](#4-email-master-lead-database)
5. [Profiles](#5-profiles)
6. [Profile Emails (Working List)](#6-profile-emails-working-list)
7. [Campaigns](#7-campaigns)
8. [Dashboard](#8-dashboard)
9. [Reports / CSV Exports](#9-reports--csv-exports)
10. [Notifications](#10-notifications)
11. [Logs](#11-logs)
12. [Options (Dropdowns)](#12-options-dropdowns)
13. [Health Check](#13-health-check)

---

## 1. Authentication

### POST /auth/login
Login with email and password.

**cURL:**
```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@company.com", "password": "yourpassword"}'
```

**Postman Body (raw JSON):**
```json
{
  "email": "admin@company.com",
  "password": "yourpassword"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Login successful",
  "data": {
    "accessToken": "eyJ...",
    "refreshToken": "eyJ..."
  }
}
```

---

### POST /auth/refresh
Get a new token pair using a refresh token.

**cURL:**
```bash
curl -X POST http://localhost:8000/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refreshToken": "eyJ..."}'
```

---

### POST /auth/logout
Invalidate the refresh token.

**cURL:**
```bash
curl -X POST http://localhost:8000/auth/logout \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"refreshToken": "eyJ..."}'
```

---

## 2. Employees (Admin Only)

> All endpoints require `Authorization: Bearer <admin_access_token>`

### POST /employees — Create Employee

**cURL:**
```bash
curl -X POST http://localhost:8000/employees \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "John Smith",
    "email": "john@company.com",
    "password": "SecurePass123",
    "branch": "Chennai",
    "employeeCode": "EMP001",
    "phone": "9876543210"
  }'
```

---

### GET /employees — List All Employees

**cURL:**
```bash
curl http://localhost:8000/employees \
  -H "Authorization: Bearer <admin_token>"
```

---

### GET /employees/me — Get My Employee Record

**cURL (employee):**
```bash
curl http://localhost:8000/employees/me \
  -H "Authorization: Bearer <employee_token>"
```

---

### GET /employees/{employee_id} — Get Single Employee

**cURL:**
```bash
curl http://localhost:8000/employees/64f1a2b3c4d5e6f7a8b9c0d1 \
  -H "Authorization: Bearer <admin_token>"
```

---

### PATCH /employees/{employee_id} — Update Employee

**cURL:**
```bash
curl -X PATCH http://localhost:8000/employees/64f1a2b3c4d5e6f7a8b9c0d1 \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "John Updated", "branch": "Mumbai"}'
```

---

### DELETE /employees/{employee_id} — Delete Employee

**cURL:**
```bash
curl -X DELETE http://localhost:8000/employees/64f1a2b3c4d5e6f7a8b9c0d1 \
  -H "Authorization: Bearer <admin_token>"
```

---

## 3. Email Accounts (SMTP)

> Admin must pass `?employeeId=` on all create requests.

### POST /email-accounts — Add SMTP Account

**cURL (admin adding for an employee):**
```bash
curl -X POST "http://localhost:8000/email-accounts?employeeId=<employee_id>" \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "employee@gmail.com",
    "appPassword": "xxxx xxxx xxxx xxxx",
    "displayName": "John Smith",
    "smtpHost": "smtp.gmail.com",
    "smtpPort": 587,
    "useTls": true
  }'
```

**cURL (employee adding their own):**
```bash
curl -X POST http://localhost:8000/email-accounts \
  -H "Authorization: Bearer <employee_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "myemail@gmail.com",
    "appPassword": "xxxx xxxx xxxx xxxx",
    "displayName": "My Name"
  }'
```

---

### GET /email-accounts — List Accounts

**cURL:**
```bash
curl http://localhost:8000/email-accounts \
  -H "Authorization: Bearer <token>"

# Admin viewing specific employee:
curl "http://localhost:8000/email-accounts?employeeId=<employee_id>" \
  -H "Authorization: Bearer <admin_token>"
```

---

### POST /email-accounts/{account_id}/test — Test SMTP Connection

**cURL:**
```bash
curl -X POST http://localhost:8000/email-accounts/64f1a2b3c4d5e6f7a8b9c0d1/test \
  -H "Authorization: Bearer <token>"
```

---

### DELETE /email-accounts/{account_id} — Delete Account

**cURL:**
```bash
curl -X DELETE http://localhost:8000/email-accounts/64f1a2b3c4d5e6f7a8b9c0d1 \
  -H "Authorization: Bearer <token>"
```

---

## 4. Email Master (Lead Database)

### POST /email-master/upload — Upload Leads CSV/Excel

**cURL:**
```bash
curl -X POST http://localhost:8000/email-master/upload \
  -H "Authorization: Bearer <token>" \
  -F "file=@/path/to/leads.csv" \
  -F "insertDuplicates=false" \
  -F "mailSource=Google Scholar"
```

**Parameters:**
| Param | Type | Default | Description |
|---|---|---|---|
| `file` | File | required | .csv, .xlsx, or .xls |
| `insertDuplicates` | bool | false | Insert duplicate emails (marked as duplicate) |
| `mailSource` | string | null | `"Google Scholar"`, `"University"`, or `"Other"` |

**Response:**
```json
{
  "data": {
    "inserted": 450,
    "duplicates": 50,
    "failed": 5,
    "totalProcessed": 505,
    "uploadBatch": "batch_a1b2c3d4e5f6"
  }
}
```

---

### GET /email-master — List Emails with Filters

**cURL:**
```bash
curl "http://localhost:8000/email-master?country=India&domain=gmail.com&mailSource=University&page=1&pageSize=50" \
  -H "Authorization: Bearer <token>"
```

**Query Parameters:**
| Param | Description |
|---|---|
| `country` | Filter by country name |
| `domain` | Filter by email domain |
| `industry` | Filter by industry |
| `company` | Filter by company name |
| `uploadedBy` | Filter by uploader user ID |
| `usedByEmployee` | Filter by which employee used this email |
| `mailSource` | `Google Scholar`, `University`, `Other` |
| `search` | Full-text search on name/email/company |
| `includeDuplicates` | `true` (default) or `false` |
| `page` | Page number (1-indexed) |
| `pageSize` | Items per page (default 20, max 100) |

---

### POST /email-master/count-filtered — Count Filtered Emails

Used by the profile "Generate List" preview to show how many leads match.

**cURL:**
```bash
curl -X POST http://localhost:8000/email-master/count-filtered \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "country": ["India", "USA"],
    "domain": ["gmail.com"],
    "industry": ["IT"],
    "mailSource": ["Google Scholar"]
  }'
```

---

### GET /email-master/dropdown-options — Get Filter Dropdown Values

Returns distinct values for country, domain, industry, company.

**cURL:**
```bash
curl http://localhost:8000/email-master/dropdown-options \
  -H "Authorization: Bearer <token>"
```

---

### GET /email-master/stats/uploaders — Upload Statistics (Admin)

**cURL:**
```bash
curl http://localhost:8000/email-master/stats/uploaders \
  -H "Authorization: Bearer <admin_token>"
```

---

### DELETE /email-master/{email_id} — Delete Single Lead (Admin)

**cURL:**
```bash
curl -X DELETE http://localhost:8000/email-master/64f1a2b3c4d5e6f7a8b9c0d1 \
  -H "Authorization: Bearer <admin_token>"
```

---

### DELETE /email-master/admin/delete-by-upload-date-range — Delete Leads by Date Range (Super Admin)

The selected start and end dates are both included. Dates accept `DD-MM-YYYY` or `YYYY-MM-DD`.

**cURL:**
```bash
curl -X DELETE "http://localhost:8000/email-master/admin/delete-by-upload-date-range?startDate=01-01-2000&endDate=01-01-2002" \
  -H "Authorization: Bearer <super_admin_token>"
```

---

### POST /email-master/admin/clear-all — Delete ALL Leads (Admin)

> ⚠️ IRREVERSIBLE — Deletes everything from Email Master

**cURL:**
```bash
curl -X POST http://localhost:8000/email-master/admin/clear-all \
  -H "Authorization: Bearer <admin_token>"
```

---

## 5. Profiles

> Admin must pass `?employeeId=` on all requests.

### POST /profiles — Create Profile

**cURL (employee):**
```bash
curl -X POST http://localhost:8000/profiles \
  -H "Authorization: Bearer <employee_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "profileName": "Cold Outreach Q3",
    "gmailAccount": "myemail@gmail.com",
    "signature": "Best regards,\nJohn Smith",
    "templates": [
      {
        "subject": "Collaboration Opportunity with [company]",
        "body": "Hi [name],\n\nI hope this finds you well...",
        "weight": 100
      }
    ],
    "reminderTemplates": [
      {
        "name": "Friendly follow-up",
        "body": "Hello [name], just following up on my previous email.",
        "weight": 2
      },
      {
        "name": "Short follow-up",
        "body": "Hello [name], checking whether you had a chance to review my email.",
        "weight": 1
      }
    ],
    "filters": {
      "country": ["India"],
      "domain": [],
      "industry": ["IT"],
      "company": [],
      "mailSource": ["Google Scholar"]
    },
    "filterLimit": 500,
    "sendingOptions": {
      "dailyLimit": 100,
      "delayMin": 30,
      "delayMax": 90
    },
    "promptSettings": {
      "personalizeGreeting": true,
      "improveGrammar": false,
      "improveProfessionalism": false,
      "aiRewrite": false,
      "customInstruction": ""
    }
  }'
```

---

### GET /profiles — List Profiles

**cURL:**
```bash
# Employee sees own profiles
curl http://localhost:8000/profiles \
  -H "Authorization: Bearer <employee_token>"

# Admin sees employee's profiles
curl "http://localhost:8000/profiles?employeeId=<employee_id>" \
  -H "Authorization: Bearer <admin_token>"
```

---

### PATCH /profiles/{profile_id} — Update Profile

**cURL:**
```bash
curl -X PATCH "http://localhost:8000/profiles/64f1a2b3c4d5e6f7a8b9c0d1" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"sendingOptions": {"dailyLimit": 200, "delayMin": 60, "delayMax": 120}}'
```

To configure reminder bodies, update the profile with a `reminderTemplates`
array. Each reminder template has `name`, `body`, and optional `weight`; it has
no subject field because reminder campaigns use the exact original draft
subject:

```json
{
  "reminderTemplates": [
    {
      "name": "Friendly follow-up",
      "body": "Hello [name], just following up on my previous email.",
      "weight": 2
    },
    {
      "name": "Short follow-up",
      "body": "Hello [name], checking whether you had a chance to review my email.",
      "weight": 1
    }
  ]
}
```

---

### POST /profiles/{profile_id}/test-email — Send a Test Email

Sends a real test email to `toEmail`. Set `mailType` to `draft` or `reminder`;
it defaults to `draft`. `templateId` selects a template from the matching list
(persisted ID or array index). If omitted, a template is selected randomly.
Reminder templates contain only a body, so the test uses the first configured
draft subject (or `Test reminder` if none is set). The profile signature and
attachments are included.

```json
{
  "toEmail": "you@example.com",
  "mailType": "reminder",
  "templateId": "reminder-template-id"
}
```

---

### POST /profiles/{profile_id}/activate — Activate Profile

**cURL:**
```bash
curl -X POST http://localhost:8000/profiles/64f1a2b3c4d5e6f7a8b9c0d1/activate \
  -H "Authorization: Bearer <token>"
```

---

### POST /profiles/{profile_id}/deactivate — Deactivate Profile

**cURL:**
```bash
curl -X POST http://localhost:8000/profiles/64f1a2b3c4d5e6f7a8b9c0d1/deactivate \
  -H "Authorization: Bearer <token>"
```

---

### DELETE /profiles/{profile_id} — Delete Profile

**cURL:**
```bash
curl -X DELETE http://localhost:8000/profiles/64f1a2b3c4d5e6f7a8b9c0d1 \
  -H "Authorization: Bearer <token>"
```

---

### POST /profiles/{profile_id}/attachments/upload — Upload Profile Attachment

**cURL:**
```bash
curl -X POST "http://localhost:8000/profiles/64f1a2b3c4d5e6f7a8b9c0d1/attachments/upload" \
  -H "Authorization: Bearer <token>" \
  -F "file=@/path/to/proposal.pdf"
```

---

## 6. Profile Emails (Working List)

### POST /profile-emails/{profile_id}/generate — Generate Working List

Filters leads from Email Master into the working list.

**cURL:**
```bash
curl -X POST "http://localhost:8000/profile-emails/64f1a2b3c4d5e6f7a8b9c0d1/generate" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{}'
```

**With filter override:**
```bash
curl -X POST "http://localhost:8000/profile-emails/64f1a2b3c4d5e6f7a8b9c0d1/generate" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "overrideFilters": {
      "country": ["USA"],
      "domain": ["edu"]
    },
    "limitOverride": 200
  }'
```

To allow previously used emails, include `"allowUsed": true`. Reused emails
must be outside the configured cooldown period (20 days by default). Super
admins can configure the cooldown with the `used_email_cooldown_days` setting
and optionally limit reuse with `used_email_max_usage_count`. Missing settings
use the defaults and do not prevent connection to an existing database.

**Response:**
```json
{
  "data": {
    "added": 320,
    "skipped": 80,
    "totalPending": 320
  }
}
```

---

### GET /profile-emails/{profile_id} — List Working List

**cURL:**
```bash
curl "http://localhost:8000/profile-emails/64f1a2b3c4d5e6f7a8b9c0d1?sendStatus=pending&page=1&pageSize=20" \
  -H "Authorization: Bearer <token>"
```

**Query Parameters:** `mailType` (draft/reminder), `sendStatus` (pending/sent/failed/skipped), `search`, `country`, `domain`, `page`, `pageSize`

---

### GET /profile-emails/{profile_id}/stats — Get Send Stats

**cURL:**
```bash
curl http://localhost:8000/profile-emails/64f1a2b3c4d5e6f7a8b9c0d1/stats \
  -H "Authorization: Bearer <token>"
```

**Response:**
```json
{
  "data": {
    "total": 500,
    "pending": 300,
    "sending": 0,
    "sent": 150,
    "failed": 50,
    "skipped": 0,
    "byType": {
      "draft": {"total": 320, "pending": 0, "sending": 0, "sent": 300, "failed": 20, "skipped": 0},
      "reminder": {"total": 180, "pending": 100, "sending": 0, "sent": 70, "failed": 10, "skipped": 0}
    }
  }
}
```

---

### POST /profile-emails/{profile_id}/convert-to-reminders — Queue Sent Drafts

Moves successfully sent drafts into the reminder queue. This endpoint does not
send email. Only rows with a saved original subject and Message-ID can be
converted; the response reports rows skipped because those fields are missing.

**cURL:**
```bash
curl -X POST http://localhost:8000/profile-emails/64f1a2b3c4d5e6f7a8b9c0d1/convert-to-reminders \
  -H "Authorization: Bearer <access_token>"
```

**Response:**
```json
{
  "data": {
    "profileId": "64f1a2b3c4d5e6f7a8b9c0d1",
    "convertedCount": 12,
    "skippedMissingThreadData": 2
  }
}
```

---

### POST /profile-emails/{profile_id}/retry-failed — Retry Failed Emails

**cURL:**
```bash
curl -X POST http://localhost:8000/profile-emails/64f1a2b3c4d5e6f7a8b9c0d1/retry-failed \
  -H "Authorization: Bearer <token>"
```

---

### DELETE /profile-emails/{profile_id}/clear — Clear Entire Working List

Deletes draft and reminder rows and releases their email locks. Usage counts
are reversed only for pending, unsent draft rows; sent drafts and pending
reminders keep their usage counts. The response includes `deletedCount` and
`usageCountReversed`.

**cURL:**
```bash
curl -X DELETE http://localhost:8000/profile-emails/64f1a2b3c4d5e6f7a8b9c0d1/clear \
  -H "Authorization: Bearer <token>"
```

---

### DELETE /profile-emails/record/{profile_email_id} — Delete Single Row

**cURL:**
```bash
curl -X DELETE http://localhost:8000/profile-emails/record/64f1a2b3c4d5e6f7a8b9c0d1 \
  -H "Authorization: Bearer <token>"
```

---

## 7. Campaigns

### POST /campaigns/start — Start Campaign Immediately

**cURL:**
```bash
curl -X POST http://localhost:8000/campaigns/start \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "profileId": "64f1a2b3c4d5e6f7a8b9c0d1",
    "campaignName": "Q3 India Outreach",
    "mailType": "draft",
    "dailyLimit": 100
  }'
```

**Body fields:**
| Field | Type | Required | Description |
|---|---|---|---|
| `profileId` | string | ✅ | Profile to run |
| `mailType` | string | ❌ | `draft` (default) or `reminder` |
| `campaignName` | string | ❌ | Auto-generated if empty |
| `dailyLimit` | int | ❌ | Overrides profile default |

Only one active campaign of each type is allowed per profile. A draft and a
reminder campaign can run concurrently. Reminder campaigns use the original
draft's exact subject and SMTP reply headers to keep the message in the thread.
Their body is selected randomly, using template weights, from the profile's
`reminderTemplates` list. Configure body-only reminder templates through
`PATCH /profiles/{profile_id}`; at least one non-empty template is required.

---

### POST /campaigns/schedule — Schedule Campaign

**cURL (run once tomorrow at 10:00 AM IST):**
```bash
curl -X POST http://localhost:8000/campaigns/schedule \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "profileId": "64f1a2b3c4d5e6f7a8b9c0d1",
    "campaignName": "Scheduled Outreach",
    "mailType": "draft",
    "recurrenceType": "once",
    "scheduledTimeLocal": "10:00",
    "scheduledDateLocal": "2026-08-01",
    "timezoneOffsetMinutes": -330,
    "dailyLimit": 100
  }'
```

> Note: `timezoneOffsetMinutes` is the offset from UTC. For IST (UTC+5:30), use `-330`. For UTC-5, use `300`.

**cURL (run daily at 09:00 AM IST):**
```bash
curl -X POST http://localhost:8000/campaigns/schedule \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "profileId": "64f1a2b3c4d5e6f7a8b9c0d1",
    "campaignName": "Daily Drip",
    "recurrenceType": "daily",
    "scheduledTimeLocal": "09:00",
    "timezoneOffsetMinutes": -330,
    "dailyLimit": 50
  }'
```

**cURL (run every Monday and Wednesday at 11:00 AM IST):**
```bash
curl -X POST http://localhost:8000/campaigns/schedule \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "profileId": "64f1a2b3c4d5e6f7a8b9c0d1",
    "campaignName": "Weekly Outreach",
    "recurrenceType": "weekly",
    "scheduledTimeLocal": "11:00",
    "timezoneOffsetMinutes": -330,
    "recurrenceDays": [0, 2],
    "dailyLimit": 100
  }'
```

> `recurrenceDays`: 0=Monday, 1=Tuesday, 2=Wednesday, 3=Thursday, 4=Friday, 5=Saturday, 6=Sunday

---

### POST /campaigns/{campaign_id}/pause — Pause Campaign

Pausing stops the worker before it starts another email; an email already handed to the SMTP server may still complete. Daily campaign, SMTP-provider, and recipient-domain limit errors mark the campaign as `failed` and save the reason in `errorMessage`. Failed scheduled runs are not automatically retried.

**cURL:**
```bash
curl -X POST http://localhost:8000/campaigns/64f1a2b3c4d5e6f7a8b9c0d1/pause \
  -H "Authorization: Bearer <token>"
```

---

### POST /campaigns/{campaign_id}/resume — Resume Campaign

Resuming an active scheduled execution continues the same run with its existing progress and per-run send count, then uses the existing scheduler logic to complete or schedule the next occurrence.

**cURL:**
```bash
curl -X POST http://localhost:8000/campaigns/64f1a2b3c4d5e6f7a8b9c0d1/resume \
  -H "Authorization: Bearer <token>"
```

---

### GET /campaigns — List Campaigns

**cURL:**
```bash
curl "http://localhost:8000/campaigns?status=running&page=1&pageSize=20" \
  -H "Authorization: Bearer <token>"
```

**Query Parameters:** `status` (`all` or one of `pending`, `running`, `paused`, `completed`, `failed`, `waiting_for_mails`, `scheduled`, `processing`), `profileId`, `employeeId` (admin only), `page`, `pageSize`. The frontend's `status=1` value is also treated as `all`.

---

### GET /campaigns/{campaign_id} — Get Campaign Details

**cURL:**
```bash
curl http://localhost:8000/campaigns/64f1a2b3c4d5e6f7a8b9c0d1 \
  -H "Authorization: Bearer <token>"
```

---

### DELETE /campaigns/{campaign_id} — Delete Campaign

> Cannot delete running campaigns.

**cURL:**
```bash
curl -X DELETE http://localhost:8000/campaigns/64f1a2b3c4d5e6f7a8b9c0d1 \
  -H "Authorization: Bearer <token>"
```

---

### POST /campaigns/process-scheduled — Trigger Scheduler (Cron)

Finds all campaigns due for execution and dispatches them in parallel.

**cURL:**
```bash
curl -X POST http://localhost:8000/campaigns/process-scheduled
```

> Called by cron every minute. Manual call allowed for testing.

---

### GET /campaigns/scheduler/status — Scheduler Health

**cURL:**
```bash
curl http://localhost:8000/campaigns/scheduler/status \
  -H "Authorization: Bearer <token>"
```

---

### GET /campaigns/admin/duplicates/{profile_id} — Detect Duplicate Campaigns (Admin)

**cURL:**
```bash
curl http://localhost:8000/campaigns/admin/duplicates/64f1a2b3c4d5e6f7a8b9c0d1 \
  -H "Authorization: Bearer <admin_token>"
```

---

### POST /campaigns/admin/consolidate — Consolidate Duplicate Campaigns (Admin)

**cURL:**
```bash
curl -X POST "http://localhost:8000/campaigns/admin/consolidate?profileId=<profile_id>&keepCampaignId=<campaign_id>" \
  -H "Authorization: Bearer <admin_token>"
```

---

## 8. Dashboard

### GET /dashboard/employee — Employee Dashboard

**cURL (employee):**
```bash
curl "http://localhost:8000/dashboard/employee?preset=last_7_days" \
  -H "Authorization: Bearer <employee_token>"
```

**cURL (admin viewing employee's dashboard):**
```bash
curl "http://localhost:8000/dashboard/employee?employeeId=<employee_id>&preset=last_month" \
  -H "Authorization: Bearer <admin_token>"
```

**Date presets:** `today`, `yesterday`, `last_7_days`, `last_month`, `custom`

**For custom date range:**
```bash
curl "http://localhost:8000/dashboard/employee?preset=custom&startDate=2026-07-01&endDate=2026-07-23" \
  -H "Authorization: Bearer <token>"
```

---

### GET /dashboard/admin — Admin Dashboard (Admin Only)

**cURL:**
```bash
curl "http://localhost:8000/dashboard/admin?preset=last_7_days" \
  -H "Authorization: Bearer <admin_token>"
```

---

### GET /dashboard/dropdown-options — Admin Dropdown Options (Admin Only)

**cURL:**
```bash
curl http://localhost:8000/dashboard/dropdown-options \
  -H "Authorization: Bearer <admin_token>"
```

---

## 9. Reports / CSV Exports

These endpoints return a CSV file download, not JSON.

### GET /reports/email-master/export — Export Email Master CSV

**cURL:**
```bash
curl "http://localhost:8000/reports/email-master/export" \
  -H "Authorization: Bearer <token>" \
  -o email_master_export.csv
```

---

### GET /reports/profile-emails/export — Export Profile Emails CSV

**cURL:**
```bash
curl "http://localhost:8000/reports/profile-emails/export?profileId=64f1a2b3c4d5e6f7a8b9c0d1&sendStatus=sent" \
  -H "Authorization: Bearer <token>" \
  -o profile_emails_sent.csv
```

**Query Parameters:** `profileId` (required), `sendStatus` (optional: pending/sent/failed/skipped)

---

### GET /reports/campaigns/export — Export Campaigns CSV

**cURL:**
```bash
curl "http://localhost:8000/reports/campaigns/export" \
  -H "Authorization: Bearer <token>" \
  -o campaigns_export.csv
```

---

## 10. Notifications

### WebSocket — Live Notifications

Connect in JavaScript:
```javascript
const ws = new WebSocket('ws://localhost:8000/notifications/ws?token=<access_token>');
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(data);
  // data.type = "campaign_progress" | "notification"
  // data.campaignId, data.event, data.totalSent, data.totalFailed
};
```

---

### GET /notifications — List Notifications

**cURL:**
```bash
curl "http://localhost:8000/notifications?unreadOnly=true&limit=20" \
  -H "Authorization: Bearer <token>"
```

---

### PATCH /notifications/read-all — Mark All As Read

**cURL:**
```bash
curl -X PATCH http://localhost:8000/notifications/read-all \
  -H "Authorization: Bearer <token>"
```

---

### PATCH /notifications/{notification_id}/read — Mark Single As Read

**cURL:**
```bash
curl -X PATCH http://localhost:8000/notifications/64f1a2b3c4d5e6f7a8b9c0d1/read \
  -H "Authorization: Bearer <token>"
```

---

## 11. Logs

### GET /logs — List Activity Logs

**cURL:**
```bash
curl "http://localhost:8000/logs?action=UPLOAD&page=1&pageSize=50" \
  -H "Authorization: Bearer <token>"
```

**Query Parameters:** `action` (e.g., UPLOAD, CAMPAIGN_STARTED, CAMPAIGN_COMPLETED), `employeeId` (admin only), `page`, `pageSize`

---

## 12. Options (Dropdowns)

Used by the frontend to populate dropdown selects.

### GET /options/employees — Employee List for Dropdown (Admin)

Returns employee and admin options visible to the caller. Super admins also
receive super-admin user options. Since super-admin accounts normally have no
employee record, their `id` falls back to their user ID; `userId` is also
included. Partial admins see employees assigned to them; full admins see
employees in their branch; super admins see all employees and super-admin
accounts. Regular admins do not receive super-admin options.

**cURL:**
```bash
curl http://localhost:8000/options/employees \
  -H "Authorization: Bearer <admin_token>"
```

---

### GET /options/profiles — Profile List for Dropdown

**cURL (employee sees own profiles):**
```bash
curl http://localhost:8000/options/profiles \
  -H "Authorization: Bearer <employee_token>"
```

**cURL (admin sees specific employee's profiles):**
```bash
curl "http://localhost:8000/options/profiles?employeeId=<employee_id>" \
  -H "Authorization: Bearer <admin_token>"
```

---

### GET /options/campaigns — Campaign List for Dropdown

**cURL:**
```bash
curl "http://localhost:8000/options/campaigns?employeeId=<employee_id>" \
  -H "Authorization: Bearer <admin_token>"
```

---

## 13. Health Check

### GET /health — Health Check (No Auth)

**cURL:**
```bash
curl http://localhost:8000/health
```

**Response:**
```json
{
  "success": true,
  "message": "Service is healthy",
  "version": "2.0.0"
}
```

---

## Standard Response Format

All JSON endpoints return this envelope:

```json
{
  "success": true | false,
  "message": "Human readable message",
  "data": { ... },
  "meta": {
    "total": 100,
    "page": 1,
    "pageSize": 20,
    "totalPages": 5
  }
}
```

## Common HTTP Error Codes

| Code | Meaning |
|---|---|
| 400 | Bad Request — invalid input, business rule violation |
| 401 | Unauthorized — missing or expired token |
| 403 | Forbidden — authenticated but insufficient role |
| 404 | Not Found — resource doesn't exist |
| 409 | Conflict — duplicate record (e.g., employee email already exists) |
| 422 | Unprocessable Entity — Pydantic validation failed |
| 429 | Too Many Requests — rate limit exceeded (100 req/min per IP) |
| 500 | Internal Server Error |
