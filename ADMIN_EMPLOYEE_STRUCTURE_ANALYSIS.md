# Admin/Employee Separation Structure Analysis

## Executive Summary

The project has **inconsistent role separation** between admin and employee contexts. While basic access control exists, there are **critical gaps in data isolation, inconsistent patterns, and security blind spots** that need restructuring.

---

## Critical Issues Found

### 1. **Inconsistent Admin Override Pattern** 🔴 HIGH PRIORITY

**Problem:** Different routers handle admin override differently
- Some routers require `employeeId` query param for admins (campaigns, email-master)
- Some routers have separate endpoints (dashboard/employee vs dashboard/admin)
- Some routers don't support admin override at all (profiles, email-accounts)

**Impact:** Admins cannot consistently manage employee data across modules

**Files Affected:**
- `app/campaigns/router.py` - Uses `employeeId` query param
- `app/email_master/router.py` - Uses `employeeId` query param
- `app/profiles/router.py` - NO admin override capability
- `app/email_accounts/router.py` - NO admin override capability
- `app/dashboard/router.py` - Separate endpoints approach

---

### 2. **Inconsistent Data Ownership Validation** 🔴 HIGH PRIORITY

**Problem:** Ownership checks are implemented inconsistently
- Some endpoints validate ownership: `_assert_owns_profile_or_admin()` in profiles
- Some endpoints skip ownership checks entirely
- No standardized pattern across all modules

**Example Issues:**
```python
# ✅ GOOD - Has ownership check
async def get_email(email_id: str, current_user: ...):
    record = await service.get_email(email_id)  # No employee check!
    
# ✅ GOOD - Has ownership check
async def get_profile(profile_id: str, ..., is_admin: bool):
    await _assert_owns_profile_or_admin(doc, employee_id, is_admin)
```

**Impact:** Potential data leakage - employees might access data from other employees

**Files Affected:**
- `app/email_master/router.py` - Missing ownership check on GET /{email_id}
- `app/campaigns/service.py` - Proper check via `_get_campaign_owned()`
- `app/profiles/service.py` - Proper check via `_assert_owns_profile_or_admin()`

---

### 3. **No Admin Audit Trail** 🔴 MEDIUM PRIORITY

**Problem:** When admins override and act on behalf of employees, there's NO logging
- No way to know which admin performed which action
- No timestamps for admin overrides
- No distinction between employee action vs admin action

**Impact:** Accountability gap - cannot audit who did what

**Affected Areas:**
- All endpoints with admin override capability
- User password updates (done by admin but no admin tracking)
- Profile/campaign modifications

---

### 4. **Token Doesn't Embed employeeId** 🟡 MEDIUM PRIORITY

**Problem:** JWT token only contains `user_id` and `role`, not `employee_id`
```python
payload = {
    "sub": subject,        # user_id
    "role": role,          # "admin" or "employee"
    "type": token_type,
    "iat": now,
    "exp": now + expires_delta,
}
# Missing: employee_id
```

**Current Workaround:** Every endpoint must call `get_employee_by_user_id()` again (extra DB query)

**Impact:** 
- Performance: Redundant DB lookups
- Inconsistency: If user has multiple employee records (shouldn't happen but risks exist)
- Security: No scope binding in token itself

---

### 5. **No Branch-Level Data Isolation** 🟡 MEDIUM PRIORITY

**Problem:** `branch` field exists on users/employees but never used in queries
```python
# Branch field exists but is NEVER used to filter data
async def list_campaigns(...):
    query = {"employeeId": employee_id}  # No branch check
    
async def list_profiles(...):
    query = {"employeeId": employee_id}  # No branch check
```

**Use Case:** If employees from different branches shouldn't see each other's data

**Impact:** Cannot enforce organizational data silos

---

### 6. **Inconsistent employeeId Resolution Pattern** 🟡 MEDIUM PRIORITY

**Problem:** Every router re-implements `_resolve_employee()` or similar
- Campaigns: `_resolve_employee()` returns `("", True)` for admins
- Email accounts: `_resolve_employee()` returns `(current_user.user_id, True)` for admins (WRONG!)
- Profiles: `_resolve_employee_id()` requires employeeId param for admins

```python
# ❌ INCONSISTENT - Returns user_id for admin instead of ""
# File: app/email_accounts/router.py
async def _resolve_employee(current_user: CurrentUser) -> tuple[str, bool]:
    is_admin = current_user.role == "admin"
    if is_admin:
        return current_user.user_id, True  # ❌ WRONG!
    employee = await get_employee_by_user_id(current_user.user_id)
    return employee["id"], False
```

**Impact:** Code duplication, maintenance burden, subtle bugs

---

### 7. **Frontend Doesn't Track Employee Context** 🟡 MEDIUM PRIORITY

**Problem:** Frontend doesn't store/use `employeeId` in context
- Auth context only stores: `userId`, `role`, `name`, `email`, `branch`
- Missing: `employeeId`
- Frontend must pass employeeId to every admin request manually

**Files Affected:**
- `frontend/src/context/AuthContext.jsx` - Missing employeeId in user state

---

### 8. **Admin Operations Missing Employee Requirement** 🔴 HIGH PRIORITY

**Problem:** Some admin endpoints don't require/validate employeeId
```python
# ❌ Should require employeeId for admin
@router.patch("/{profile_id}", response_model=ApiResponse)
async def update_profile(...):
    # No employeeId parameter!
    # Admin cannot specify which employee's profile to update
```

**Impact:** Ambiguous behavior when admin acts - whose profile is being updated?

---

## Architectural Patterns Identified

### Current Pattern (Mixed)

```
Request → Dependency (get_current_user) → Role Check (require_admin) → 
    Router Handler → _resolve_employee() → Service Layer → DB Query
```

**Issues:**
- Resolution happens at multiple layers
- No centralized access control
- Inconsistent query building

### Better Pattern (Proposed)

```
Request → TokenValidation → RoleCheck → EmployeeContextResolution → 
    AccessControl → AuthorizedBusinessLogic → DB
```

---

## Recommended Refactoring Checklist

### Phase 1: Foundation (Critical)

- [ ] **Standardize `_resolve_employee()` pattern**
  - Create single source in `app/core/dependencies.py`
  - All routers use this function
  - Admin return: `employee_id=None` (means "all")
  
- [ ] **Add employee_id to JWT token**
  ```python
  payload = {
      "sub": user_id,
      "employee_id": employee_id,
      "role": role,
      ...
  }
  ```

- [ ] **Standardize ownership validation**
  - Create `validate_data_ownership()` utility in core
  - All GET/PATCH/DELETE endpoints use it
  - Pattern: `await validate_data_ownership(resource, current_user, is_admin)`

- [ ] **Add audit logging for admin actions**
  - Middleware to track: admin_id, employee_id, action, timestamp
  - Log to separate collection: `admin_audit_logs`

### Phase 2: Consistency (High)

- [ ] **Fix all routers to support admin override**
  - Profiles: Add `employeeId` query parameter support
  - Email accounts: Add `employeeId` query parameter support
  - Campaigns: Already done ✓
  - Email-master: Already done ✓

- [ ] **Fix email_accounts._resolve_employee() bug**
  ```python
  # Current (WRONG):
  if is_admin:
      return current_user.user_id, True  # ❌
  
  # Should be:
  if is_admin:
      return None, True  # ✓ or require employeeId param
  ```

- [ ] **Add frontend employeeId context**
  ```javascript
  const user = {
      userId, 
      employeeId,  // ← ADD THIS
      role,
      ...
  }
  ```

- [ ] **Update all service layer access checks**
  - Use consistent pattern
  - Always check: `if not is_admin and resource.employeeId != employee_id: raise`

### Phase 3: Security (Medium)

- [ ] **Implement branch-level isolation** (if needed)
  - Add branch to token
  - Filter queries by branch
  - Validate cross-branch access

- [ ] **Add API request logging**
  - Log all admin operations
  - Track who accessed what data
  - Create compliance report endpoint

- [ ] **Validate token scoping**
  - Employee token should not access other employees' data
  - Admin token should have clear scope boundaries

### Phase 4: Frontend (Medium)

- [ ] **Create ProtectedRoute for employee context**
  - Admin routes: Require employeeId in URL
  - Employee routes: Auto-inject employeeId from auth context
  - Example: `/admin/employee/{employeeId}/campaigns` vs `/campaigns`

- [ ] **Standardize admin override pattern in UI**
  - Employee selector dropdown on admin pages
  - Auto-populate from dropdown-options endpoint
  - Show: "Acting as [Employee Name]"

- [ ] **Add breadcrumb showing context**
  - Admin: "Admin > [Employee] > [Profile] > Campaigns"
  - Employee: "[Profile] > Campaigns"

---

## Data Model Review

### Current
```
User ──── Employee ──── Campaigns
              ├── Profiles
              ├── EmailAccounts
              └── Uploaded Emails

Branch is field on User, never used
```

### Proposed (Clearer)
```
User (user_id, role)
  ├── Admin User (can act as any employee)
  ├── Employee User ─── Employee Record (employee_id, branch)
         ├── Campaigns (employeeId, branch reference)
         ├── Profiles (employeeId, branch reference)
         ├── EmailAccounts (employeeId, branch reference)
         └── EmailMaster (employeeId, branch reference)
```

---

## Priority Recommendations

**Must Do (Blocks admin functionality):**
1. Fix email_accounts override pattern
2. Standardize admin override across all routers
3. Add employeeId to JWT token
4. Create centralized ownership validation

**Should Do (Security/UX):**
5. Add audit logging
6. Add employeeId to frontend auth context
7. Fix branch isolation (if multi-branch support needed)

**Nice To Have:**
8. API request logging middleware
9. Compliance reports
10. Frontend context breadcrumbs

---

## Code Examples for Refactoring

### Before (Current - Inconsistent)
```python
# campaigns/router.py
async def _resolve_employee(current_user):
    if current_user.role == "admin":
        return "", True
    employee = await get_employee_by_user_id(current_user.user_id)
    return employee["id"], False

# email_accounts/router.py  
async def _resolve_employee(current_user):
    if current_user.role == "admin":
        return current_user.user_id, True  # ❌ WRONG
    employee = await get_employee_by_user_id(current_user.user_id)
    return employee["id"], False
```

### After (Proposed - Centralized)
```python
# core/dependencies.py
async def resolve_employee_context(
    current_user: CurrentUser,
    employee_id_param: str | None = None
) -> tuple[str, bool]:
    """
    Returns (employee_id, is_admin)
    - Admin: employee_id = param or None (depends on context)
    - Employee: employee_id = their employee record id
    """
    if current_user.role == "admin":
        if not employee_id_param:
            raise BadRequestException("employeeId required for admin")
        return employee_id_param, True
    
    employee = await get_employee_by_user_id(current_user.user_id)
    return employee["id"], False


# Now all routers use same function:
employee_id, is_admin = await resolve_employee_context(current_user, employeeId)
```

---

## Summary

| Issue | Severity | Impact | Effort |
|-------|----------|--------|--------|
| Inconsistent admin override | 🔴 HIGH | Blocks admin functionality | Medium |
| Missing ownership validation | 🔴 HIGH | Data leakage risk | Medium |
| No audit trail | 🔴 HIGH | No accountability | Low |
| employeeId not in token | 🟡 MED | Performance/security | Medium |
| Branch isolation missing | 🟡 MED | Multi-tenancy blocked | High |
| Resolution pattern duplication | 🟡 MED | Maintenance burden | Low |
| Frontend missing employeeId | 🟡 MED | UX inconsistency | Low |
| Admin ops missing employee param | 🔴 HIGH | Ambiguous behavior | Low |

**Total Refactoring Effort:** ~2-3 sprints for full restructuring

