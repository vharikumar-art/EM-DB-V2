# Cold Email Marketing Management System — Detailed Project Documentation

---

## 1. Project Purpose

This project is a backend system for an internal cold email marketing platform. It allows multiple employees to manage their own outreach campaigns, while admins can oversee employee activity, manage accounts, review results, and control campaign execution.

The system covers the full workflow:
1. User and employee account creation
2. SMTP email account setup
3. Uploading a master lead database
4. Creating reusable outreach profiles
5. Generating a filtered list of leads for each profile
6. Running and scheduling campaigns
7. Viewing analytics, logs, notifications, and exports

---

## 2. Architecture Overview

The backend is built with:
- Python 3.11
- FastAPI for API endpoints and WebSocket support
- Uvicorn as the ASGI server
- Motor with MongoDB for async data access
- Pydantic for request/response validation
- JWT for authentication
- Fernet encryption for SMTP credentials
- smtplib for email sending

The codebase is modular. Each business area lives in its own package under the app directory.

---

## 3. Simple Summary in One Line

This system is an internal email marketing backend where users log in, upload leads, create profiles, run or schedule campaigns, and monitor results through dashboards, notifications, and logs.

In simple terms, the app works like this:
- Users authenticate and gain access based on their role
- Employees manage their own email accounts, profiles, and campaigns
- Leads are uploaded into a master database and filtered into profile-specific lists
- Campaigns send emails using SMTP accounts and track progress in real time
- Admins and super-admins can view higher-level analytics and control scope across the system

---

## 4. High-Level Architecture

The system follows a layered architecture:

```text
Client / Frontend
    │
    ▼
FastAPI Routers
    │
    ▼
Service Layer
    │
    ├── Authentication & Authorization
    ├── Business Rules
    ├── Campaign Execution Logic
    └── Notification / Dashboard Logic
    │
    ▼
MongoDB Database
    │
    ├── users
    ├── employees
    ├── email_master
    ├── profiles
    ├── profile_emails
    ├── campaigns
    ├── email_accounts
    └── notifications / logs / templates
```

### Main Architectural Flow
1. The frontend sends HTTP requests to the FastAPI routers
2. Each router calls a service function
3. The service performs validation and MongoDB operations
4. Long-running operations such as campaign sending are handled by the worker/scheduler layer
5. Notifications and dashboard data are pushed or queried as needed

---

## 5. Entity Relationship Diagram (ER Diagram)

```text
Users
  ├── one-to-one with Employees
  └── one-to-many with Roles / Access

Employees
  ├── one-to-many with EmailAccounts
  ├── one-to-many with Profiles
  ├── one-to-many with Campaigns
  └── one-to-many with Notifications

EmailMaster
  ├── one-to-many with ProfileEmails
  └── many-to-many through profile filtering logic

Profiles
  ├── one-to-many with ProfileEmails
  ├── one-to-many with Templates
  └── one-to-many with Campaigns

ProfileEmails
  ├── many-to-one with Profiles
  └── many-to-one with EmailMaster

Campaigns
  ├── many-to-one with Profiles
  └── one-to-many with Notifications / Logs

Templates
  └── many-to-one with Profiles
```

### ER Relationship Summary
- A user can become an employee
- An employee owns email accounts, profiles, campaigns, and notifications
- A profile pulls leads from the email master database and generates profile email rows
- A campaign sends from those generated profile email rows
- Templates are attached to profiles and used during sending

---

## 6. Application Entry Point

Main entry point: [main.py](main.py)

Main responsibilities:
- Create the FastAPI application
- Register middleware such as logging, audit logging, CORS, and error handling
- Include all router modules
- Start the MongoDB connection lifecycle
- Register startup and shutdown behavior
- Expose health/ready endpoints if applicable

Important runtime sections:
- app startup initializes database access
- routers are mounted so all endpoints become available
- background scheduler/campaign execution is wired from the app lifecycle

---

## 4. Request Flow in the System

A typical campaign request flows like this:
1. Client sends an authenticated request to a router endpoint
2. Router receives the request and calls a service function
3. Service uses MongoDB collection access through the database layer
4. Business rules are enforced (permissions, validation, role checks)
5. Data is serialized into the response shape
6. If the action triggers campaign sending, the worker or scheduler handles the long-running process

This structure keeps route handlers thin and business logic centralized in service modules.

---

## 5. Core Infrastructure Modules

### 5.1 app/core/config.py
Purpose:
- Centralizes configuration values
- Loads environment values for secrets, app URL, database settings, and token settings

Main methods / behavior:
- Defines configuration fields for environment-based setup
- Exposes helpers for CORS origins and app-level settings

Why it matters:
- This is the first place the app reads runtime values from the environment
- It controls many security and deployment settings

### 5.2 app/core/dependencies.py
Purpose:
- Provides authentication and authorization dependencies

Main methods / behavior:
- get_current_user(): validates a JWT access token and loads the current user context
- require_roles(*allowed_roles): wraps access control for role-based endpoints

Why it matters:
- Almost every protected endpoint depends on this layer
- It ensures only authenticated users can access private data

### 5.3 app/core/security.py
Purpose:
- Handles password hashing, token generation, token validation, and encryption/decryption

Main methods / behavior:
- hash_password(): hashes a plain password
- verify_password(): compares a supplied password with a stored hash
- encrypt_password(): encrypts sensitive SMTP credentials
- decrypt_password(): decrypts stored SMTP credentials
- _create_token(): creates JWT access or refresh tokens

Why it matters:
- This is the security backbone of the application

### 5.4 app/core/exceptions.py
Purpose:
- Defines custom exception classes for clean API error handling

Main methods / behavior:
- BadRequestException
- NotFoundException
- UnauthorizedException
- ForbiddenException
- ConflictException

Why it matters:
- Route handlers and services use these to return predictable API errors

### 5.5 app/core/rate_limit.py
Purpose:
- Limits repeated request behavior to avoid abuse or overload

Main methods / behavior:
- Configures and applies request rate limits to selected endpoints

Why it matters:
- Helps protect authentication and public endpoints from excessive traffic

---

## 6. Authentication and User Management

### 6.1 app/auth/
Purpose:
- Handles authentication and token management

Router entry points:
- POST /auth/login
- POST /auth/refresh
- POST /auth/logout

Service methods:
- login(payload): validates user login, verifies password, creates access and refresh tokens
- refresh_access_token(refresh_token): validates refresh token, rotates or refreshes the token pair
- logout(refresh_token): marks the token as invalid in the revoked_tokens collection

Key behavior:
- Access tokens are short-lived
- Refresh tokens are used to obtain fresh access tokens
- Revoked tokens are persisted so a logged-out session cannot be reused

### 6.2 app/users/
Purpose:
- Manages users and user-role creation

Router entry points:
- POST /users/initial-super-admin
- POST /users/initial-admin
- POST /users
- GET /users
- GET /users/{id}
- PUT /users/{id}
- DELETE /users/{id}

Service methods:
- create_user(payload): creates a normal user account
- create_initial_super_admin(payload): creates the first super-admin user
- create_initial_admin(payload): creates the first admin user
- get_user_by_email(email): fetches a user by email
- get_user_by_id(user_id): fetches a user by ID
- list_users(current_user): lists users according to role and permissions
- update_user(user_id, payload): updates metadata or access-related fields

Key behavior:
- The app supports super-admin, admin, and employee-level access
- Initial admin/super-admin creation is handled separately to bootstrap the system

---

## 7. Employee Module

### app/employees/
Purpose:
- Represents an employee profile linked to a user account

Router entry points:
- POST /employees
- GET /employees
- GET /employees/me
- GET /employees/{id}
- PUT /employees/{id}
- DELETE /employees/{id}

Service methods:
- create_employee(payload): creates both a user account and an employee profile when needed
- list_employees(current_user): returns employee records visible to the current user
- get_employee(employee_id, current_user): fetches one employee record
- get_employee_by_user_id(user_id): fetches the employee linked to a user account
- _attach_user_info(employee_doc, include_password): enriches employee data with user-linked details

Key behavior:
- Employees are separate from users in the data model
- Admins can manage employee records on behalf of an organization
- Each employee usually owns their own campaigns, profiles, and email accounts

---

## 8. Email Accounts Module

### app/email_accounts/
Purpose:
- Stores SMTP credentials and account settings for sending emails

Router entry points:
- POST /email-accounts
- GET /email-accounts
- GET /email-accounts/{id}
- PUT /email-accounts/{id}
- DELETE /email-accounts/{id}
- POST /email-accounts/{id}/test
- POST /email-accounts/test-direct

Service methods:
- create_account(employee_id, payload): creates a new email account and encrypts the password
- list_accounts(employee_id, is_admin): lists accounts according to ownership or admin scope
- get_account(account_id, employee_id, is_admin): fetches one account with access checks
- update_account(account_id, employee_id, is_admin, payload): updates account fields and re-encrypts password if changed
- delete_account(account_id, employee_id, is_admin): removes an account
- test_connection(account_id, employee_id, is_admin): verifies SMTP credentials by attempting a live login
- test_credentials_directly(payload): verifies SMTP access before the account is saved
- get_credentials_for_send(gmail_account): decrypts and returns credentials when the campaign engine needs to send mail
- record_send(account_id): increments the send counter after a successful send

Key behavior:
- Passwords are never stored in plaintext
- Each account is bound to an employee owner
- The campaign engine fetches credentials dynamically before sending

---

## 9. Email Master Module

### app/email_master/
Purpose:
- Stores the permanent global lead database
- This is the master list from which profiles pull email data

Router entry points:
- POST /email-master/upload
- GET /email-master
- GET /email-master/{id}
- DELETE /email-master/{id}
- GET /email-master/dropdown-options
- GET /email-master/uploader-stats
- GET /email-master/count-filtered

Service methods:
- upload_file(employee_id, file, payload): parses CSV/Excel data, validates emails, removes duplicates, and stores leads in MongoDB
- list_emails(filters, pagination, employee_id): returns leads with filtering and pagination support
- get_email(email_id): returns one lead document
- delete_email(email_id): removes one lead from the master list
- get_dropdown_options(): returns country/domain/industry values used in the UI
- get_uploader_stats(): returns upload activity and summary statistics
- count_filtered_emails(filters): counts how many leads match the provided filters

Key behavior:
- Uploads are treated as grouped batch operations
- Duplicate detection is applied during import
- Leads are tagged with metadata such as country, company, domain, and upload batch

---

## 10. Profiles and Template Configuration

### 10.1 app/profiles/
Purpose:
- Defines reusable email campaigns by profile
- A profile contains the filters, sending rules, Gmail account, attachments, and templates used for outreach

Router entry points:
- POST /profiles
- GET /profiles
- GET /profiles/{id}
- PUT /profiles/{id}
- POST /profiles/{id}/activate
- POST /profiles/{id}/deactivate
- DELETE /profiles/{id}
- POST /profiles/{id}/templates
- PUT /profiles/{id}/templates/{template_id}
- DELETE /profiles/{id}/templates/{template_id}

Service methods:
- create_profile(employee_id, payload): creates a new profile with default filters and sending options
- list_profiles(employee_id): returns all profiles visible to the employee or admin
- get_profile(profile_id, employee_id, is_admin): fetches one profile with access validation
- update_profile(profile_id, employee_id, payload): updates profile settings
- set_active_status(profile_id, employee_id, is_admin, active): activates or deactivates the profile
- delete_profile(profile_id, employee_id, is_admin): removes the profile
- add_template(profile_id, employee_id, payload): adds a new template to the profile
- update_template(profile_id, employee_id, template_id, payload): updates template content or weighting
- delete_template(profile_id, employee_id, template_id): removes a template

Key behavior:
- Profiles are per employee and can be activated before campaign use
- Each profile contains its own rules and templates

### 10.2 app/templates/
Purpose:
- Provides reusable templates that can be associated with profiles

Router entry points:
- POST /templates
- GET /templates
- GET /templates/{id}
- PUT /templates/{id}
- DELETE /templates/{id}

Service methods:
- create_template(employee_id, is_admin, payload): creates a new template
- list_templates(employee_id, is_admin): lists templates visible to the current user
- get_template(template_id, employee_id, is_admin): fetches one template
- update_template(template_id, employee_id, is_admin, payload): updates template fields
- delete_template(template_id, employee_id, is_admin): removes a template

---

## 11. Profile Emails Module

### app/profile_emails/
Purpose:
- Holds the generated working list of emails for a specific profile
- These records are what the campaign engine sends from

Router entry points:
- POST /profile-emails/{profile_id}/generate
- GET /profile-emails/{profile_id}
- GET /profile-emails/{profile_id}/stats
- GET /profile-emails/{profile_id}/{email_id}
- PUT /profile-emails/{profile_id}/{email_id}
- DELETE /profile-emails/{profile_id}/{email_id}
- POST /profile-emails/{profile_id}/retry-failed
- POST /profile-emails/{profile_id}/clear
- POST /profile-emails/bulk-delete

Service methods:
- generate_list(profile_id, employee_id, is_admin, override_filters, limit_override, allow_used): pulls matching leads from email_master and creates pending records for this profile
- list_profile_emails(profile_id, employee_id, is_admin, params, send_status, search, country, domain): lists profile email rows with pagination and filtering
- get_stats(profile_id, employee_id, is_admin): returns pending/sending/sent/failed/skipped counts
- get_profile_email(profile_email_id, employee_id, is_admin): fetches one generated record
- update_profile_email(profile_email_id, employee_id, is_admin, payload): updates one generated row
- delete_profile_email(profile_email_id, employee_id, is_admin): removes one generated row
- retry_failed(profile_id, employee_id, is_admin): resets failed rows back to pending
- clear_profile_list(profile_id, employee_id, is_admin): deletes all rows for a profile
- bulk_delete(profile_email_ids, employee_id, is_admin): removes multiple rows in bulk

Key behavior:
- This module is the bridge between static lead data and active mail sending
- It tracks the lifecycle of each email: pending, sending, sent, failed, skipped

---

## 12. Campaign Management Module

### app/campaigns/
Purpose:
- Creates, schedules, controls, and tracks marketing campaigns

Router entry points:
- POST /campaigns/start
- POST /campaigns/pause
- POST /campaigns/resume
- GET /campaigns
- GET /campaigns/{id}
- DELETE /campaigns/{id}
- POST /campaigns/schedule
- POST /campaigns/process-scheduled

Service methods:
- create_campaign(profile_id, employee_id, payload): starts a new immediate campaign
- create_scheduled_campaign(profile_id, employee_id, payload): creates a scheduled campaign document
- _get_campaign_owned(campaign_id, employee_id): fetches a campaign with ownership validation
- set_status(campaign_id, status): updates campaign state
- increment_counters(campaign_id, sent_count, failed_count): updates counts after send progress
- finalize_campaign(campaign_id): marks the campaign completed or failed based on its final state
- abort_campaign(campaign_id, reason): aborts the running campaign early
- is_paused(campaign_id): checks whether the campaign has been paused

Key behavior:
- Campaigns can be started immediately or scheduled in advance
- Scheduling supports once, daily, and weekly recurrence
- Campaign status transitions control the send workflow

### app/campaigns/scheduler.py
Purpose:
- Finds due scheduled campaigns and dispatches them for execution

Main methods:
- calculate_next_run(...): computes the next UTC time for a recurring campaign based on local time and timezone offset
- find_due_campaigns(): finds campaigns that are due now
- transition_to_processing(campaign_id): atomically changes status from scheduled to processing to avoid duplicate execution
- execute_campaign(campaign_id): runs the campaign execution path
- finalize_campaign_execution(...): updates campaign status after execution completes
- process_scheduled_campaigns(): loops through due campaigns and dispatches them
- get_scheduler_status(): returns scheduler health and queue counts

Key behavior:
- Scheduler logic is designed to prevent duplicate runs
- It is the coordination layer between scheduled campaigns and the actual send worker

---

## 13. Campaign Engine

### app/campaign_engine/worker.py
Purpose:
- Performs the actual email sending loop for each campaign

Main methods:
- select_template_weighted(templates): selects a template based on weights
- run_campaign(campaign_id): starts the main campaign execution process
- _run(campaign_id): processes the sending loop for that campaign

Key behavior:
- The worker loads the campaign, profile, and available profile email records
- It sends emails one by one with delays and per-account rate control
- It updates the database with send progress and status changes
- It emits progress events for notifications and frontends

### app/campaign_engine/sender.py
Purpose:
- Builds MIME email messages and sends them with SMTP

Main methods:
- _build_mime_message(...): constructs the email body and headers
- _attach_file(...): attaches files to the email message
- _send_sync(...): sends the message via SMTP

Key behavior:
- Supports plain text, HTML, attachments, and SMTP login
- Errors are surfaced so failed sends are properly tracked

---

## 14. Notifications and WebSocket Layer

### app/notifications/
Purpose:
- Delivers in-app notifications and live campaign progress updates

Router entry points:
- GET /notifications
- POST /notifications/mark-read
- POST /notifications/mark-all-read
- WS /notifications/ws

Service methods:
- create_notification(employee_id, message, type): saves a notification and notifies connected clients
- list_notifications(employee_id, unread_only, limit): returns notification history

WebSocket components:
- ConnectionManager manages active user connections
- The campaign engine pushes events to connected clients during sends

Key behavior:
- Admins and employees can receive real-time campaign updates without refreshing the UI

---

## 15. Dashboard and Analytics

### app/dashboard/
Purpose:
- Builds summaries for the employee dashboard and admin/super-admin views

Router entry points:
- GET /dashboard/employee
- GET /dashboard/admin
- GET /dashboard/super-admin
- GET /dashboard/upload-history
- GET /dashboard/dropdown-options

Service methods:
- get_employee_dashboard(employee_id, query): returns an employee’s own dashboard summary
- get_admin_scoped_dashboard(admin_user_id, query): returns a role-scoped dashboard for admins and super-admins
- _resolve_dashboard_scope(role, user_id): determines which scope of records the current user should see
- _build_admin_scope(...): filters data according to admin visibility rules

Key behavior:
- The dashboard aggregates campaign, profile, lead, and activity metrics
- Scope resolution ensures admins only see their own allowed data unless they are a super-admin

---

## 16. Logs and Reporting

### app/logs/
Purpose:
- Stores and lists activity logs for audits and inspection

Service methods:
- list_logs(...): returns system activity records for the current scope

### app/reports/
Purpose:
- Exports data to CSV for lead lists and profile email lists

Router entry points:
- GET /reports/email-master-csv
- GET /reports/profile-emails-csv

Key behavior:
- Useful for offline analytics and external review

### app/options/
Purpose:
- Returns dropdown values and option data for UI forms

Router entry points:
- GET /options/employees
- GET /options/profiles
- GET /options/campaigns

Key behavior:
- Helps the frontend load lists without additional complex queries

---

## 17. Database Layer

### app/database/mongodb.py
Purpose:
- Connects the application to MongoDB

Main methods:
- connect_to_mongo(): opens the MongoDB connection
- close_mongo_connection(): tears down the connection on shutdown
- get_collection(name): returns a MongoDB collection handle

### app/database/indexes.py
Purpose:
- Creates or ensures important MongoDB indexes

Key behavior:
- Improves lookup performance for campaigns, profiles, email master data, notifications, and logs

---

## 18. Middleware and Cross-Cutting Concerns

### app/middleware/logging_middleware.py
Purpose:
- Logs incoming requests and request timing

### app/middleware/audit_middleware.py
Purpose:
- Captures audit information for admin-level visibility and change tracking

### app/middleware/error_handler.py
Purpose:
- Registers centralized exception handling for FastAPI

Key behavior:
- The app produces consistent error responses and logs failures centrally

---

## 19. Utility Helpers

### app/utils/csv_utils.py
Purpose:
- Parses uploaded CSV and Excel files

### app/utils/email_validator.py
Purpose:
- Validates uploaded lead email addresses

### app/utils/personalizer.py
Purpose:
- Replaces placeholders in email templates with lead-specific values

### app/utils/pagination.py
Purpose:
- Creates shared pagination parameters and response structure

### app/utils/response.py
Purpose:
- Serializes MongoDB documents and normalizes API response shape

---

## 20. Main Data Collections

| Collection | Purpose |
|---|---|
| users | Stores login accounts and identity |
| employees | Stores employee profile records |
| email_master | Stores global lead data |
| profiles | Stores profile definitions and filters |
| profile_emails | Stores generated leads for each profile |
| campaigns | Stores campaign lifecycle state |
| email_accounts | Stores encrypted SMTP credentials |
| templates | Stores reusable templates |
| notifications | Stores in-app notification records |
| logs | Stores audit and action logs |
| revoked_tokens | Stores invalidated refresh tokens |

---

## 21. Typical End-to-End User Flow

### A. User login
1. User calls /auth/login
2. Service verifies credentials
3. JWT tokens are issued

### B. Add email account
1. User calls /email-accounts
2. Password is encrypted and saved
3. Later, campaign sending retrieves it securely

### C. Upload leads
1. User uploads a file through /email-master/upload
2. Leads are parsed and validated
3. Data is inserted into email_master

### D. Create profile
1. User creates a profile with filters, templates, sending limits, and Gmail account
2. Profile is stored in the profiles collection

### E. Generate profile email list
1. User calls /profile-emails/{profile_id}/generate
2. Leads are selected from email_master based on profile filters
3. Generated rows are stored in profile_emails

### F. Start a campaign
1. User starts or schedules a campaign
2. The worker sends each email using the profile rules and SMTP account
3. Progress updates are stored and pushed to the UI

---

## 22. Notes for Production Readiness

The current system is functional, but for production use it should be hardened with:
- stronger environment secret management
- better background worker separation from the web process
- monitoring and alerting for send failures
- more robust scheduler reliability
- stricter role enforcement in every service layer
- stronger validation and recovery logic for long-running campaigns

---

## 23. Summary

This project is a full internal email marketing platform with:
- user and employee management
- encrypted SMTP account handling
- lead upload and deduplication
- reusable profile-based campaign setup
- generated email lists for sending
- campaign execution and scheduling
- dashboards, logs, notifications, and exports

The main architectural design is modular and service-oriented, with FastAPI routers delegating business logic to service modules that perform MongoDB operations and enforce business rules.
