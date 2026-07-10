# Testing New Upload & Campaign Limits

## **FEATURE 1: Upload Limit (maxLimit)**

### **Test 1: Upload with maxLimit = 100**

```
POST http://localhost:8000/email-master/upload?maxLimit=100

Headers:
- Authorization: Bearer {access_token}

Body: form-data
- file: select your CSV file
- insertDuplicates: false
- maxLimit: 100
```

**Expected Response:**
```json
{
  "success": true,
  "data": {
    "totalUploaded": 100,
    "unique": 100,
    "duplicate": 0,
    "failed": 0,
    "uploadBatch": "batch_..."
  }
}
```

**What happens:**
- If file has 1000 rows, only first 100 are uploaded
- Rest are ignored
- Notification shows: "Upload complete: 100 records processed (limited to 100)"

---

### **Test 2: Upload with maxLimit = 300**

```
POST http://localhost:8000/email-master/upload?maxLimit=300
```

**Expected:** Only 300 emails uploaded (not all)

---

### **Test 3: Upload without maxLimit (upload all)**

```
POST http://localhost:8000/email-master/upload
```

**Expected:** All emails from file uploaded (no limit)

---

## **FEATURE 2: Campaign Daily Limit (dailyLimit)**

### **Test 1: Start Campaign with dailyLimit = 50**

```
POST http://localhost:8000/campaigns/start

Headers:
- Authorization: Bearer {access_token}
- Content-Type: application/json

Body (JSON):
{
  "profileId": "{profile_id}",
  "campaignName": "Test Campaign - 50/day",
  "dailyLimit": 50
}
```

**Expected Response:**
```json
{
  "success": true,
  "data": {
    "id": "...",
    "campaignName": "Test Campaign - 50/day",
    "status": "pending",
    "totalEmails": 178,
    "dailyLimit": 50,
    "pending": 178,
    "sent": 0
  }
}
```

**What happens:**
- Campaign will send MAXIMUM 50 emails per day
- Even if profile has dailyLimit: 100, this campaign uses 50
- Notification shows: "Daily limit: 50"

---

### **Test 2: Start Campaign with dailyLimit = 200**

```
POST http://localhost:8000/campaigns/start

Body:
{
  "profileId": "{profile_id}",
  "campaignName": "Test Campaign - 200/day",
  "dailyLimit": 200
}
```

**Expected:**
- Campaign sends max 200 emails/day
- Response shows: `"dailyLimit": 200`

---

### **Test 3: Start Campaign WITHOUT dailyLimit (use profile default)**

```
POST http://localhost:8000/campaigns/start

Body:
{
  "profileId": "{profile_id}",
  "campaignName": "Test Campaign - Profile Default",
  "dailyLimit": null
}
```

**Expected:**
- Campaign uses profile's sendingOptions.dailyLimit (usually 100)
- Response shows: `"dailyLimit": 100` (or whatever profile has)

---

## **COMPLETE TEST WORKFLOW**

### **Step 1: Upload with Limit**
```
POST /email-master/upload?maxLimit=200
```
✓ Only 200 emails uploaded

### **Step 2: Create Profile**
```
POST /profiles
```
✓ Profile created with default sendingOptions.dailyLimit: 100

### **Step 3: Activate Profile**
```
POST /profiles/{profile_id}/activate
```
✓ Profile activated

### **Step 4: Generate Email List**
```
POST /profile-emails/{profile_id}/generate
```
✓ Email list generated (up to 200 from Step 1)

### **Step 5: Start Campaign with Custom Limit**
```
POST /campaigns/start
Body: { "profileId": "...", "dailyLimit": 75 }
```
✓ Campaign starts with dailyLimit: 75 (not 100 from profile)

### **Step 6: Monitor**
```
GET /campaigns/{campaign_id}
```
✓ Check that dailyLimit is 75, emails sending at that rate

---

## **VERIFICATION CHECKLIST**

### **Upload Limit Works:**
- [ ] Test with maxLimit=100 → only 100 uploaded
- [ ] Test with maxLimit=500 → only 500 uploaded
- [ ] Test without maxLimit → all uploaded
- [ ] Check notification mentions limit

### **Campaign Limit Works:**
- [ ] Test with dailyLimit=50 → response shows dailyLimit: 50
- [ ] Test with dailyLimit=200 → response shows dailyLimit: 200
- [ ] Test with dailyLimit=null → uses profile default
- [ ] Check notification includes "Daily limit: X"

### **Campaign Execution:**
- [ ] Monitor campaign sending rate respects dailyLimit
- [ ] Check delays between emails (30-90 sec)
- [ ] Verify pending count decreases correctly

---

## **EXPECTED BEHAVIOR**

| Scenario | Upload | Campaign Result |
|----------|--------|-----------------|
| maxLimit=100, dailyLimit=50 | 100 emails | Sends 50/day |
| maxLimit=200, dailyLimit=150 | 200 emails | Sends 150/day |
| maxLimit=null, dailyLimit=75 | All emails | Sends 75/day |
| maxLimit=300, dailyLimit=null | 300 emails | Uses profile limit (usually 100) |

---

## **POSTMAN TEST SEQUENCE**

1. Login → Save token
2. Add Gmail Account
3. Upload with maxLimit=100
4. Create Profile
5. Activate Profile
6. Generate Email List
7. Start Campaign with dailyLimit=50
8. Get Campaign Status
9. Verify dailyLimit in response
10. Monitor campaign progress

---

Done! All features tested! ✅
