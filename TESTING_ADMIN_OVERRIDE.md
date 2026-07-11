# Admin Override Pattern Testing Guide

This document provides step-by-step testing procedures to verify that all admin/employee separation features work correctly.

## Prerequisites

1. Start the backend: `uvicorn main:app --reload`
2. Start the frontend: `npm run dev`
3. Have at least 2 test accounts:
   - **Admin Account**: role=admin
   - **Employee Account**: role=employee

---

## Test Suite 1: Authentication & Token Verification

### Test 1.1: JWT Token Contains employeeId for Employees
**Steps:**
1. Login as employee
2. Open browser DevTools → Application → Local Storage
3. Copy the `access_token` value
4. Decode at [jwt.io](https://jwt.io)

**Expected Result:**
```json
{
  "sub": "user_id",
  "role": "employee",
  "employee_id": "emp_123",  // ← Should be present
  "type": "access",
  ...
}
```

**Expected Result (Admin):**
```json
{
  "sub": "user_id",
  "role": "admin",
  // ← employee_id should NOT be present
  "type": "access",
  ...
}
```

### Test 1.2: AuthContext Stores employeeId
**Steps:**
1. Login as employee
2. Open browser DevTools → Console
3. Run: `console.log(JSON.parse(localStorage.getItem('user')))`

**Expected Result:**
```json
{
  "userId": "user_id",
  "role": "employee",
  "employeeId": "emp_123",  // ← Should be present
  "name": "John Doe",
  "email": "john@example.com",
  ...
}
```

---

## Test Suite 2: Dropdown Options Endpoints

### Test 2.1: Get Employees Options (Admin Only)
**Request:**
```bash
curl -H "Authorization: Bearer ADMIN_TOKEN" \
  http://localhost:8000/options/employees
```

**Expected Result:**
```json
{
  "success": true,
  "message": "Employees fetched",
  "data": [
    { "id": "emp_1", "name": "Alice", "email": "alice@example.com", "branch": "US" },
    { "id": "emp_2", "name": "Bob", "email": "bob@example.com", "branch": "EU" }
  ]
}
```

### Test 2.2: Get Profiles Options (Employee)
**Request:**
```bash
curl -H "Authorization: Bearer EMPLOYEE_TOKEN" \
  http://localhost:8000/options/profiles
```

**Expected Result:**
```json
{
  "success": true,
  "message": "Profiles fetched",
  "data": [
    { "id": "prof_1", "profileName": "Sales", "gmailAccount": "sales@company.com" },
    { "id": "prof_2", "profileName": "Support", "gmailAccount": "support@company.com" }
  ]
}
```

### Test 2.3: Get Profiles Options (Admin Acting As Employee)
**Request:**
```bash
curl -H "Authorization: Bearer ADMIN_TOKEN" \
  "http://localhost:8000/options/profiles?employeeId=emp_1"
```

**Expected Result:** Same as above for that employee

### Test 2.4: Get Campaigns Options (Admin Without employeeId)
**Request:**
```bash
curl -H "Authorization: Bearer ADMIN_TOKEN" \
  http://localhost:8000/options/campaigns
```

**Expected Result:**
```json
{
  "success": true,
  "message": "Admins must specify employeeId",
  "data": []
}
```

---

## Test Suite 3: Campaigns Management

### Test 3.1: Employee Creates & Runs Campaign
**Steps:**
1. Login as employee
2. Go to Campaigns page
3. Click "Start Campaign"
4. Select profile and daily limit
5. Check campaign appears with status "PENDING" → "RUNNING"

**Expected:**
- Campaign created with employeeId = current employee
- Campaign starts automatically
- Status transitions work: PENDING → RUNNING

### Test 3.2: Admin Can't Start Campaign Without employeeId
**Request:**
```bash
curl -X POST -H "Authorization: Bearer ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"profileId": "prof_1", "campaignName": "Test"}' \
  http://localhost:8000/campaigns/start
```

**Expected Error:**
```json
{
  "success": false,
  "message": "Admins must specify employeeId"
}
```

### Test 3.3: Admin Starts Campaign For Employee
**Request:**
```bash
curl -X POST -H "Authorization: Bearer ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"profileId": "prof_1", "campaignName": "Test"}' \
  "http://localhost:8000/campaigns/start?employeeId=emp_1"
```

**Expected:**
- Campaign created with employeeId = emp_1
- Status = PENDING
- Audit log entry created

### Test 3.4: Admin Pauses Employee's Campaign
**Request:**
```bash
curl -X POST -H "Authorization: Bearer ADMIN_TOKEN" \
  "http://localhost:8000/campaigns/CAMPAIGN_ID/pause?employeeId=emp_1"
```

**Expected:**
- Same campaign document
- Status changes to PAUSED
- Audit log: admin_user_id logged, action=pause, target=emp_1

### Test 3.5: Admin Resumes Campaign
**Request:**
```bash
curl -X POST -H "Authorization: Bearer ADMIN_TOKEN" \
  "http://localhost:8000/campaigns/CAMPAIGN_ID/resume?employeeId=emp_1"
```

**Expected:**
- Same campaign (no duplicate created)
- Status changes back to RUNNING
- Send loop resumes

### Test 3.6: Campaign Duplication Detection
**Request:**
```bash
curl -H "Authorization: Bearer ADMIN_TOKEN" \
  http://localhost:8000/campaigns/admin/duplicates/prof_1
```

**Expected:**
- Shows all campaigns for profile
- If multiple exist with different statuses, they're candidates for consolidation

### Test 3.7: Campaign Consolidation
**Request:**
```bash
curl -X POST -H "Authorization: Bearer ADMIN_TOKEN" \
  "http://localhost:8000/campaigns/admin/consolidate?profileId=prof_1&keepCampaignId=CAMPAIGN_ID"
```

**Expected:**
- Other campaigns deleted
- Counters merged into kept campaign
- All profile_emails retagged to kept campaign

---

## Test Suite 4: Profiles Management

### Test 4.1: Employee Creates Profile
**Steps:**
1. Login as employee
2. Create profile with filters and filterLimit
3. Verify profile has employeeId = current employee

**Expected:**
- Profile created
- filterLimit stored correctly

### Test 4.2: Admin Updates Employee's Profile
**Request:**
```bash
curl -X PATCH -H "Authorization: Bearer ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"profileName": "Updated Name"}' \
  "http://localhost:8000/profiles/PROFILE_ID?employeeId=emp_1"
```

**Expected:**
- Same profile updated
- Audit log entry created

### Test 4.3: Employee Can't Access Other Employee's Profile
**Setup:**
- Create profile A as employee1
- Login as employee2

**Request:**
```bash
curl -H "Authorization: Bearer EMPLOYEE2_TOKEN" \
  http://localhost:8000/profiles/PROFILE_A_ID
```

**Expected Error:**
```json
{
  "success": false,
  "message": "You do not have access to this profile"
}
```

### Test 4.4: Admin Can Access Any Profile
**Request:**
```bash
curl -H "Authorization: Bearer ADMIN_TOKEN" \
  "http://localhost:8000/profiles/PROFILE_A_ID?employeeId=emp_1"
```

**Expected:**
- Profile returned
- No access error

---

## Test Suite 5: Email Master & Filtering

### Test 5.1: Employee Uploads Emails
**Steps:**
1. Login as employee
2. Upload CSV with emails
3. Verify emails have employeeId = current employee

**Expected:**
- Emails uploaded
- employeeId set correctly

### Test 5.2: Admin Uploads Emails For Employee
**Request:**
```bash
curl -X POST -H "Authorization: Bearer ADMIN_TOKEN" \
  -F "file=@emails.csv" \
  "http://localhost:8000/email-master/upload?employeeId=emp_1"
```

**Expected:**
- Emails uploaded with employeeId=emp_1
- Audit log created

### Test 5.3: Filter Limit Enforced Per Profile
**Steps:**
1. Create profile with filterLimit=50
2. Generate list from email_master
3. Verify returned emails ≤ 50

**Expected:**
- Returns at most 50 emails (not 500, not global limit)
- Even if 500 match filters, only 50 returned

---

## Test Suite 6: Frontend Admin Components

### Test 6.1: EmployeeSelector Dropdown Loads
**Steps:**
1. Go to `/admin/campaigns` or any admin page
2. Check employee dropdown appears
3. Select an employee

**Expected:**
- Dropdown loads all employees
- Shows "Acting as [Name]" status
- Form updates with selected employee

### Test 6.2: Admin Campaigns Page Shows Correct Campaigns
**Steps:**
1. Login as admin
2. Go to Admin Campaigns page
3. Select employee1
4. Verify campaigns shown belong to employee1
5. Switch to employee2
6. Verify campaigns change

**Expected:**
- Campaigns filter by selected employee
- employeeId added to all requests
- Pause/resume work for selected employee

---

## Test Suite 7: Audit Logging

### Test 7.1: Verify Audit Log Created
**Steps:**
1. Login as admin
2. Act on employee's campaign (pause/resume/create)
3. Check MongoDB `audit_logs` collection

**Expected:**
```json
{
  "admin_user_id": "admin_id",
  "target_employee_id": "emp_1",
  "method": "POST",
  "path": "/campaigns/CAMPAIGN_ID/pause",
  "status_code": 200,
  "action": "updated",
  "success": true,
  "timestamp": "2024-01-01T12:00:00Z"
}
```

### Test 7.2: Audit Log Not Created For Employee Actions
**Steps:**
1. Login as employee
2. Act on own campaign
3. Check audit_logs

**Expected:**
- No audit entry (only admin actions logged)

---

## Manual Testing Checklist

- [ ] Employee JWT contains `employee_id`
- [ ] Admin JWT does NOT contain `employee_id`
- [ ] Frontend AuthContext stores `employeeId`
- [ ] `/options/employees` requires admin role
- [ ] `/options/profiles` works for both employees and admins (with employeeId)
- [ ] `/options/campaigns` requires `employeeId` param for admins
- [ ] Admin can't create campaign without `employeeId`
- [ ] Admin can create campaign with `employeeId`
- [ ] Admin pause/resume uses SAME campaign document (no duplicates)
- [ ] Campaign consolidation merges counters correctly
- [ ] Profile `filterLimit` limits emails returned
- [ ] Employee can't access other employee's data
- [ ] Admin can access any employee's data with `employeeId` param
- [ ] Audit logs created for admin actions only
- [ ] EmployeeSelector component loads and works
- [ ] Admin Campaigns page filters by selected employee
- [ ] Admin can pause/resume from UI
- [ ] All services support optional `employeeId` parameter

---

## Debugging Common Issues

### Issue: Admin gets 400 "employeeId required"
**Solution:** Check that request includes `?employeeId=emp_id` query param

### Issue: Campaign duplicates appearing
**Solution:** Use `/campaigns/admin/duplicates/{profileId}` to detect, then consolidate

### Issue: Filter limit not working
**Solution:** Verify profile has `filterLimit` > 0 set, check email_master service uses it

### Issue: Audit logs not appearing
**Solution:** Verify middleware is registered in `main.py`, check MongoDB connection

### Issue: Frontend can't find employeeId
**Solution:** Check JWT token is decoded correctly, AuthContext stores it, services pass it

---

## Success Criteria

✅ All 7 test suites pass
✅ No duplicate campaigns created
✅ Audit logs track all admin actions
✅ Filter limits enforced per-profile
✅ Admin can override for any employee
✅ Employees isolated from each other
✅ Frontend components work correctly
