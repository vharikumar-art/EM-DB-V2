# API Endpoints — Complete Postman Testing Guide

**Base URL:** `http://localhost:8000`

**Headers (most requests):**
```json
{
  "Content-Type": "application/json",
  "Authorization": "Bearer <access_token>"
}
```

---

## 1. Authentication Endpoints

### 1.1 Login
**POST** `/auth/login`

**Request Body:**
```json
{
  "email": "admin@example.com",
  "password": "admin123"
}
```

**Response (200):**
```json
{
  "success": true,
  "message": "OK",
  "data": {
    "accessToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "refreshToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
  }
}
```

---

### 1.2 Refresh Access Token
**POST** `/auth/refresh`

**Headers:**
```json
{
  "Content-Type": "application/json"
}
```

**Request Body:**
```json
{
  "refreshToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Response (200):**
```json
{
  "success": true,
  "message": "OK",
  "data": {
    "accessToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "refreshToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
  }
}
```

---

### 1.3 Logout
**POST** `/auth/logout`

**Request Body:**
```json
{
  "refreshToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Response (200):**
```json
{
  "success": true,
  "message": "OK"
}
```

---

## 2. Users Endpoints (Admin Only)

### 2.1 Create User
**POST** `/users`

**Request Body:**
```json
{
  "name": "John Doe",
  "email": "john@example.com",
  "password": "SecurePass123",
  "role": "employee",
  "status": "active"
}
```

**Response (201):**
```json
{
  "success": true,
  "message": "User created",
  "data": {
    "id": "507f1f77bcf86cd799439011",
    "name": "John Doe",
    "email": "john@example.com",
    "role": "employee",
    "status": "active",
    "createdAt": "2026-07-08T10:30:00Z"
  }
}
```

---

### 2.2 List Users
**GET** `/users?page=1&pageSize=25`

**Response (200):**
```json
{
  "success": true,
  "message": "Users fetched",
  "data": {
    "success": true,
    "message": "OK",
    "data": [
      {
        "id": "507f1f77bcf86cd799439011",
        "name": "John Doe",
        "email": "john@example.com",
        "role": "employee",
        "status": "active",
        "createdAt": "2026-07-08T10:30:00Z"
      }
    ],
    "total": 10,
    "page": 1,
    "pageSize": 25,
    "totalPages": 1
  }
}
```

---

### 2.3 Get User by ID
**GET** `/users/{userId}`

**Response (200):**
```json
{
  "success": true,
  "message": "User fetched",
  "data": {
    "id": "507f1f77bcf86cd799439011",
    "name": "John Doe",
    "email": "john@example.com",
    "role": "employee",
    "status": "active",
    "createdAt": "2026-07-08T10:30:00Z"
  }
}
```

---

### 2.4 Update User
**PATCH** `/users/{userId}`

**Request Body (partial update):**
```json
{
  "name": "Jane Doe",
  "status": "active"
}
```

**Response (200):**
```json
{
  "success": true,
  "message": "User updated",
  "data": {
    "id": "507f1f77bcf86cd799439011",
    "name": "Jane Doe",
    "email": "john@example.com",
    "role": "employee",
    "status": "active",
    "updatedAt": "2026-07-08T10:35:00Z"
  }
}
```

---

## 3. Employees Endpoints

### 3.1 Create Employee
**POST** `/employees`

**Request Body:**
```json
{
  "userId": "507f1f77bcf86cd799439011",
  "branch": "New York",
  "department": "Sales"
}
```

**Response (201):**
```json
{
  "success": true,
  "message": "Employee created",
  "data": {
    "id": "507f1f77bcf86cd799439012",
    "userId": "507f1f77bcf86cd799439011",
    "branch": "New York",
    "department": "Sales",
    "status": "active",
    "createdAt": "2026-07-08T10:30:00Z"
  }
}
```

---

### 3.2 List Employees
**GET** `/employees?page=1&pageSize=25`

**Response (200):**
```json
{
  "success": true,
  "message": "Employees fetched",
  "data": {
    "data": [
      {
        "id": "507f1f77bcf86cd799439012",
        "userId": "507f1f77bcf86cd799439011",
        "branch": "New York",
        "department": "Sales",
        "status": "active"
      }
    ],
    "total": 5,
    "page": 1,
    "pageSize": 25,
    "totalPages": 1
  }
}
```

---

### 3.3 Get Current Employee (Me)
**GET** `/employees/me`

**Response (200):**
```json
{
  "success": true,
  "message": "Employee fetched",
  "data": {
    "id": "507f1f77bcf86cd799439012",
    "userId": "507f1f77bcf86cd799439011",
    "branch": "New York",
    "department": "Sales",
    "status": "active"
  }
}
```

---

### 3.4 Get Employee by ID
**GET** `/employees/{employeeId}`

**Response (200):**
```json
{
  "success": true,
  "message": "Employee fetched",
  "data": {
    "id": "507f1f77bcf86cd799439012",
    "userId": "507f1f77bcf86cd799439011",
    "branch": "New York",
    "department": "Sales"
  }
}
```

---

### 3.5 Update Employee
**PATCH** `/employees/{employeeId}`

**Request Body:**
```json
{
  "branch": "Los Angeles",
  "department": "Marketing"
}
```

**Response (200):**
```json
{
  "success": true,
  "message": "Employee updated",
  "data": {
    "id": "507f1f77bcf86cd799439012",
    "branch": "Los Angeles",
    "department": "Marketing",
    "updatedAt": "2026-07-08T10:35:00Z"
  }
}
```

---

## 4. Email Accounts Endpoints

### 4.1 Add Email Account
**POST** `/email-accounts`

**Request Body:**
```json
{
  "email": "sales@gmail.com",
  "appPassword": "xyzq-qwer-asdf-zxcv",
  "displayName": "Sales Team",
  "accountType": "gmail_smtp",
  "smtpHost": "smtp.gmail.com",
  "smtpPort": 587,
  "useTls": true
}
```

**Response (201):**
```json
{
  "success": true,
  "message": "Email account added",
  "data": {
    "id": "507f1f77bcf86cd799439013",
    "employeeId": "507f1f77bcf86cd799439012",
    "email": "sales@gmail.com",
    "displayName": "Sales Team",
    "accountType": "gmail_smtp",
    "smtpHost": "smtp.gmail.com",
    "smtpPort": 587,
    "useTls": true,
    "isActive": true,
    "sendCount": 0,
    "createdAt": "2026-07-08T10:30:00Z"
  }
}
```

**Note:** `appPassword` is NOT returned. Only encrypted version is stored.

---

### 4.2 List Email Accounts
**GET** `/email-accounts?employeeId=507f1f77bcf86cd799439012`

**Response (200):**
```json
{
  "success": true,
  "message": "Email accounts fetched",
  "data": [
    {
      "id": "507f1f77bcf86cd799439013",
      "employeeId": "507f1f77bcf86cd799439012",
      "email": "sales@gmail.com",
      "displayName": "Sales Team",
      "accountType": "gmail_smtp",
      "smtpHost": "smtp.gmail.com",
      "smtpPort": 587,
      "useTls": true,
      "isActive": true,
      "lastUsedAt": "2026-07-08T09:00:00Z",
      "sendCount": 145
    }
  ]
}
```

---

### 4.3 Get Email Account
**GET** `/email-accounts/{accountId}`

**Response (200):**
```json
{
  "success": true,
  "message": "Account fetched",
  "data": {
    "id": "507f1f77bcf86cd799439013",
    "email": "sales@gmail.com",
    "displayName": "Sales Team",
    "isActive": true,
    "sendCount": 145,
    "lastError": null
  }
}
```

---

### 4.4 Update Email Account
**PATCH** `/email-accounts/{accountId}`

**Request Body:**
```json
{
  "displayName": "Updated Sales Team",
  "useTls": false,
  "appPassword": "new-app-password-here"
}
```

**Response (200):**
```json
{
  "success": true,
  "message": "Account updated",
  "data": {
    "id": "507f1f77bcf86cd799439013",
    "email": "sales@gmail.com",
    "displayName": "Updated Sales Team",
    "useTls": false,
    "updatedAt": "2026-07-08T10:35:00Z"
  }
}
```

---

### 4.5 Test Email Account Connection
**POST** `/email-accounts/{accountId}/test`

**Response (200):**
```json
{
  "success": true,
  "message": "Connection successful",
  "data": {
    "success": true,
    "message": "Connection successful"
  }
}
```

**Response (400) - Failed:**
```json
{
  "success": false,
  "message": "Connection failed",
  "data": {
    "success": false,
    "message": "Authentication failed: Invalid credentials"
  }
}
```

---

### 4.6 Delete Email Account
**DELETE** `/email-accounts/{accountId}`

**Response (200):**
```json
{
  "success": true,
  "message": "Account deleted"
}
```

---

## 5. Email Master Endpoints

### 5.1 Upload Email Database
**POST** `/email-master/upload` (multipart/form-data)

**Form Data:**
- `file`: (binary) CSV or XLSX file
- `insertDuplicates`: (boolean, optional) Default: false

**CSV/XLSX Format Example:**
```
Full Name,Email,Company,Country,Industry,Designation
John Smith,john@acme.com,Acme Corp,USA,Technology,CEO
Jane Doe,jane@beta.com,Beta Inc,Canada,Finance,CFO
```

**Response (200):**
```json
{
  "success": true,
  "message": "File processed",
  "data": {
    "totalUploaded": 2,
    "unique": 2,
    "duplicate": 0,
    "failed": 0,
    "uploadBatch": "batch_a1b2c3d4e5f6",
    "sample": [
      {
        "id": "507f1f77bcf86cd799439014",
        "email": "john@acme.com",
        "fullName": "John Smith",
        "company": "Acme Corp",
        "country": "USA",
        "industry": "Technology",
        "designation": "CEO",
        "isDuplicate": false,
        "createdAt": "2026-07-08T10:30:00Z"
      }
    ]
  }
}
```

---

### 5.2 List Email Master Records
**GET** `/email-master?page=1&pageSize=25&country=USA&domain=gmail.com&search=john`

**Query Parameters:**
- `page` (optional, default=1)
- `pageSize` (optional, default=25)
- `country` (optional) Filter by country
- `domain` (optional) Filter by domain
- `industry` (optional) Filter by industry
- `company` (optional) Filter by company
- `includeDuplicates` (optional, default=true)
- `search` (optional) Search in email/name/company
- `employeeId` (admin only)

**Response (200):**
```json
{
  "success": true,
  "message": "Emails fetched",
  "data": {
    "data": [
      {
        "id": "507f1f77bcf86cd799439014",
        "employeeId": "507f1f77bcf86cd799439012",
        "uploadBatch": "batch_a1b2c3d4e5f6",
        "isDuplicate": false,
        "fullName": "John Smith",
        "email": "john@acme.com",
        "company": "Acme Corp",
        "country": "USA",
        "industry": "Technology",
        "designation": "CEO",
        "assignedProfiles": [
          {
            "profileId": "507f1f77bcf86cd799439020",
            "employeeId": "507f1f77bcf86cd799439012",
            "assignedDate": "2026-07-08T10:35:00Z"
          }
        ],
        "createdAt": "2026-07-08T10:30:00Z"
      }
    ],
    "total": 45,
    "page": 1,
    "pageSize": 25,
    "totalPages": 2
  }
}
```

---

### 5.3 Get Single Email Record
**GET** `/email-master/{emailId}`

**Response (200):**
```json
{
  "success": true,
  "message": "Email record fetched",
  "data": {
    "id": "507f1f77bcf86cd799439014",
    "email": "john@acme.com",
    "fullName": "John Smith",
    "company": "Acme Corp",
    "website": "https://acme.com",
    "country": "USA",
    "state": "California",
    "city": "San Francisco",
    "domain": "acme.com",
    "industry": "Technology",
    "designation": "CEO",
    "phone": "+1-555-0100",
    "linkedin": "https://linkedin.com/in/jsmith"
  }
}
```

---

### 5.4 Get Dropdown Options
**GET** `/email-master/dropdown-options?employeeId=507f1f77bcf86cd799439012`

**Response (200):**
```json
{
  "success": true,
  "message": "Dropdown options fetched",
  "data": {
    "profiles": [
      {
        "id": "507f1f77bcf86cd799439020",
        "name": "USA SaaS CEOs"
      }
    ],
    "domains": ["acme.com", "beta.com", "gamma.org"],
    "countries": ["Canada", "USA", "UK"],
    "states": ["California", "New York", "Ontario"],
    "industries": ["Finance", "Healthcare", "Technology"]
  }
}
```

---

## 6. Profiles Endpoints

### 6.1 Create Profile
**POST** `/profiles`

**Request Body:**
```json
{
  "profileName": "USA SaaS CEOs",
  "gmailAccount": "sales@gmail.com",
  "subject": "Quick idea for [company]",
  "body": "Hi [name],\n\nI noticed [company] operates in [industry].\n\nWould love to discuss how we help similar companies.",
  "signature": "<br><br>Best regards,<br>Sales Team",
  "filters": {
    "country": ["USA"],
    "domain": ["gmail.com", "outlook.com"],
    "industry": ["Technology", "Finance"],
    "company": [],
    "type": []
  },
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
}
```

**Response (201):**
```json
{
  "success": true,
  "message": "Profile created",
  "data": {
    "id": "507f1f77bcf86cd799439020",
    "employeeId": "507f1f77bcf86cd799439012",
    "profileName": "USA SaaS CEOs",
    "gmailAccount": "sales@gmail.com",
    "subject": "Quick idea for [company]",
    "body": "Hi [name],\n\nI noticed [company] operates in [industry]...",
    "signature": "<br><br>Best regards,<br>Sales Team",
    "isActive": true,
    "filters": {
      "country": ["USA"],
      "domain": ["gmail.com", "outlook.com"],
      "industry": ["Technology", "Finance"],
      "company": [],
      "type": []
    },
    "sendingOptions": {
      "dailyLimit": 100,
      "delayMin": 30,
      "delayMax": 90
    },
    "createdAt": "2026-07-08T10:30:00Z"
  }
}
```

---

### 6.2 List Profiles
**GET** `/profiles?page=1&pageSize=25`

**Response (200):**
```json
{
  "success": true,
  "message": "Profiles fetched",
  "data": [
    {
      "id": "507f1f77bcf86cd799439020",
      "employeeId": "507f1f77bcf86cd799439012",
      "profileName": "USA SaaS CEOs",
      "gmailAccount": "sales@gmail.com",
      "isActive": true,
      "createdAt": "2026-07-08T10:30:00Z"
    }
  ]
}
```

---

### 6.3 Get Profile
**GET** `/profiles/{profileId}`

**Response (200):**
```json
{
  "success": true,
  "message": "Profile fetched",
  "data": {
    "id": "507f1f77bcf86cd799439020",
    "employeeId": "507f1f77bcf86cd799439012",
    "profileName": "USA SaaS CEOs",
    "gmailAccount": "sales@gmail.com",
    "subject": "Quick idea for [company]",
    "body": "Hi [name],\n\nI noticed [company]...",
    "signature": "<br><br>Best regards",
    "isActive": true,
    "filters": {
      "country": ["USA"],
      "domain": ["gmail.com", "outlook.com"],
      "industry": ["Technology", "Finance"],
      "company": [],
      "type": []
    },
    "sendingOptions": {
      "dailyLimit": 100,
      "delayMin": 30,
      "delayMax": 90
    },
    "promptSettings": {
      "personalizeGreeting": true,
      "improveGrammar": false,
      "improveProfessionalism": false,
      "aiRewrite": false
    },
    "createdAt": "2026-07-08T10:30:00Z"
  }
}
```

---

### 6.4 Update Profile
**PATCH** `/profiles/{profileId}`

**Request Body (partial update):**
```json
{
  "subject": "Updated subject for [company]",
  "body": "Updated body here...",
  "sendingOptions": {
    "dailyLimit": 150,
    "delayMin": 45,
    "delayMax": 120
  }
}
```

**Response (200):**
```json
{
  "success": true,
  "message": "Profile updated",
  "data": {
    "id": "507f1f77bcf86cd799439020",
    "subject": "Updated subject for [company]",
    "sendingOptions": {
      "dailyLimit": 150,
      "delayMin": 45,
      "delayMax": 120
    },
    "updatedAt": "2026-07-08T10:35:00Z"
  }
}
```

---

### 6.5 Activate Profile
**POST** `/profiles/{profileId}/activate`

**Response (200):**
```json
{
  "success": true,
  "message": "Profile activated",
  "data": {
    "id": "507f1f77bcf86cd799439020",
    "isActive": true
  }
}
```

---

### 6.6 Deactivate Profile
**POST** `/profiles/{profileId}/deactivate`

**Response (200):**
```json
{
  "success": true,
  "message": "Profile deactivated",
  "data": {
    "id": "507f1f77bcf86cd799439020",
    "isActive": false
  }
}
```

---

### 6.7 Delete Profile
**DELETE** `/profiles/{profileId}`

**Response (200):**
```json
{
  "success": true,
  "message": "Profile deleted"
}
```

---


## 7. Profile Emails Endpoints

### 7.1 Generate Email List for Profile
**POST** `/profile-emails/{profileId}/generate`

**Request Body (optional):**
```json
{
  "overrideFilters": {
    "country": ["USA", "Canada"],
    "industry": ["Technology"]
  },
  "limitOverride": 500
}
```

**Response (200):**
```json
{
  "success": true,
  "message": "Profile email list generated",
  "data": {
    "profileId": "507f1f77bcf86cd799439020",
    "added": 234,
    "skipped": 0,
    "totalPending": 234
  }
}
```

---

### 7.2 List Profile Emails
**GET** `/profile-emails/{profileId}?page=1&pageSize=25&sendStatus=pending&search=john&country=USA`

**Query Parameters:**
- `page` (optional, default=1)
- `pageSize` (optional, default=25)
- `sendStatus` (optional) Filter: pending, sent, failed, sending, skipped
- `search` (optional) Search in email/name/company
- `country` (optional) Filter by country
- `domain` (optional) Filter by domain

**Response (200):**
```json
{
  "success": true,
  "message": "Profile emails fetched",
  "data": {
    "data": [
      {
        "id": "507f1f77bcf86cd799439030",
        "profileId": "507f1f77bcf86cd799439020",
        "campaignId": null,
        "masterEmailId": "507f1f77bcf86cd799439014",
        "fullName": "John Smith",
        "email": "john@acme.com",
        "company": "Acme Corp",
        "country": "USA",
        "domain": "acme.com",
        "industry": "Technology",
        "designation": "CEO",
        "sendStatus": "pending",
        "threadId": null,
        "messageId": null,
        "sentDate": null,
        "errorMessage": null,
        "notes": "",
        "retryCount": 0,
        "createdAt": "2026-07-08T10:30:00Z"
      }
    ],
    "total": 234,
    "page": 1,
    "pageSize": 25,
    "totalPages": 10
  }
}
```

---

### 7.3 Get Profile Email Stats
**GET** `/profile-emails/{profileId}/stats`

**Response (200):**
```json
{
  "success": true,
  "message": "Stats fetched",
  "data": {
    "total": 234,
    "pending": 150,
    "sending": 2,
    "sent": 80,
    "failed": 2,
    "skipped": 0
  }
}
```

---

### 7.4 Get Single Profile Email Record
**GET** `/profile-emails/record/{profileEmailId}`

**Response (200):**
```json
{
  "success": true,
  "message": "Record fetched",
  "data": {
    "id": "507f1f77bcf86cd799439030",
    "profileId": "507f1f77bcf86cd799439020",
    "fullName": "John Smith",
    "email": "john@acme.com",
    "company": "Acme Corp",
    "country": "USA",
    "sendStatus": "pending",
    "notes": "Follow up next week"
  }
}
```

---

### 7.5 Update Profile Email Record
**PATCH** `/profile-emails/record/{profileEmailId}`

**Request Body:**
```json
{
  "fullName": "Mr. John Smith",
  "company": "Acme Corporation",
  "notes": "Updated contact info"
}
```

**Response (200):**
```json
{
  "success": true,
  "message": "Record updated",
  "data": {
    "id": "507f1f77bcf86cd799439030",
    "fullName": "Mr. John Smith",
    "company": "Acme Corporation",
    "notes": "Updated contact info",
    "updatedAt": "2026-07-08T10:35:00Z"
  }
}
```

---

### 7.6 Delete Single Profile Email Record
**DELETE** `/profile-emails/record/{profileEmailId}`

**Response (200):**
```json
{
  "success": true,
  "message": "Record deleted"
}
```

---

### 7.7 Retry Failed Emails
**POST** `/profile-emails/{profileId}/retry-failed`

**Response (200):**
```json
{
  "success": true,
  "message": "Failed emails reset to pending",
  "data": {
    "resetCount": 5
  }
}
```

---

### 7.8 Clear Entire Profile List
**DELETE** `/profile-emails/{profileId}/clear`

**Response (200):**
```json
{
  "success": true,
  "message": "Profile list cleared",
  "data": {
    "deletedCount": 234
  }
}
```

---

### 7.9 Bulk Delete Profile Emails
**POST** `/profile-emails/bulk-delete`

**Request Body:**
```json
{
  "ids": [
    "507f1f77bcf86cd799439030",
    "507f1f77bcf86cd799439031",
    "507f1f77bcf86cd799439032"
  ]
}
```

**Response (200):**
```json
{
  "success": true,
  "message": "Records deleted",
  "data": {
    "deletedCount": 3
  }
}
```

---

## 8. Templates Endpoints

### 8.1 Create Template
**POST** `/templates`

**Request Body:**
```json
{
  "name": "Quick Intro - Tech",
  "subject": "Quick idea for [company]",
  "body": "Hi [name],\n\nI noticed [company] is in [industry].\n\n[domain] caught my eye.\n\nWould love to connect!",
  "signature": "<br><br>Best,<br>Sales Team",
  "tags": ["tech", "saas", "quick-intro"],
  "isGlobal": false
}
```

**Response (201):**
```json
{
  "success": true,
  "message": "Template created",
  "data": {
    "id": "507f1f77bcf86cd799439040",
    "employeeId": "507f1f77bcf86cd799439012",
    "name": "Quick Intro - Tech",
    "subject": "Quick idea for [company]",
    "body": "Hi [name],\n\nI noticed [company]...",
    "tags": ["tech", "saas", "quick-intro"],
    "isGlobal": false,
    "usageCount": 0,
    "createdAt": "2026-07-08T10:30:00Z"
  }
}
```

---

### 8.2 List Templates
**GET** `/templates?page=1&pageSize=25&tag=tech&search=intro`

**Query Parameters:**
- `page` (optional)
- `pageSize` (optional)
- `tag` (optional) Filter by tag
- `search` (optional) Search in name/subject

**Response (200):**
```json
{
  "success": true,
  "message": "Templates fetched",
  "data": {
    "data": [
      {
        "id": "507f1f77bcf86cd799439040",
        "employeeId": "507f1f77bcf86cd799439012",
        "name": "Quick Intro - Tech",
        "subject": "Quick idea for [company]",
        "tags": ["tech", "saas"],
        "isGlobal": false,
        "usageCount": 15
      }
    ],
    "total": 5,
    "page": 1,
    "pageSize": 25,
    "totalPages": 1
  }
}
```

---

### 8.3 Get Template
**GET** `/templates/{templateId}`

**Response (200):**
```json
{
  "success": true,
  "message": "Template fetched",
  "data": {
    "id": "507f1f77bcf86cd799439040",
    "employeeId": "507f1f77bcf86cd799439012",
    "name": "Quick Intro - Tech",
    "subject": "Quick idea for [company]",
    "body": "Hi [name],\n\nI noticed [company]...",
    "signature": "<br><br>Best,<br>Sales Team",
    "tags": ["tech", "saas"],
    "isGlobal": false,
    "usageCount": 15,
    "createdAt": "2026-07-08T10:30:00Z"
  }
}
```

---

### 8.4 Update Template
**PATCH** `/templates/{templateId}`

**Request Body:**
```json
{
  "name": "Updated Quick Intro - Tech",
  "body": "Updated body content...",
  "tags": ["tech", "saas", "updated"]
}
```

**Response (200):**
```json
{
  "success": true,
  "message": "Template updated",
  "data": {
    "id": "507f1f77bcf86cd799439040",
    "name": "Updated Quick Intro - Tech",
    "tags": ["tech", "saas", "updated"],
    "updatedAt": "2026-07-08T10:35:00Z"
  }
}
```

---

### 8.5 Delete Template
**DELETE** `/templates/{templateId}`

**Response (200):**
```json
{
  "success": true,
  "message": "Template deleted"
}
```

---

### 8.6 Preview Template
**POST** `/templates/preview`

**Request Body:**
```json
{
  "templateId": "507f1f77bcf86cd799439040",
  "sampleLead": {
    "fullName": "John Smith",
    "company": "Acme Corp",
    "industry": "Technology",
    "designation": "CEO",
    "country": "USA",
    "domain": "acme.com"
  }
}
```

**Response (200):**
```json
{
  "success": true,
  "message": "Preview generated",
  "data": {
    "subject": "Quick idea for Acme Corp",
    "body": "Hi John,\n\nI noticed Acme Corp is in Technology.\n\nacme.com caught my eye.\n\nWould love to connect!",
    "signature": "<br><br>Best,<br>Sales Team"
  }
}
```

---

## 9. Campaigns Endpoints

### 9.1 Start Campaign
**POST** `/campaigns/start`

**Request Body:**
```json
{
  "profileId": "507f1f77bcf86cd799439020",
  "campaignName": "July 2026 - USA Tech CEOs"
}
```

**Response (200):**
```json
{
  "success": true,
  "message": "Campaign started",
  "data": {
    "id": "507f1f77bcf86cd799439050",
    "campaignName": "July 2026 - USA Tech CEOs",
    "profileId": "507f1f77bcf86cd799439020",
    "employeeId": "507f1f77bcf86cd799439012",
    "status": "pending",
    "totalEmails": 150,
    "pending": 150,
    "sent": 0,
    "failed": 0,
    "skipped": 0,
    "startedAt": null,
    "createdAt": "2026-07-08T10:30:00Z"
  }
}
```

---

### 9.2 List Campaigns
**GET** `/campaigns?page=1&pageSize=25&status=running&profileId=507f1f77bcf86cd799439020&employeeId=507f1f77bcf86cd799439012`

**Query Parameters:**
- `page` (optional)
- `pageSize` (optional)
- `status` (optional) Filter: pending, running, paused, completed, failed
- `profileId` (optional)
- `employeeId` (optional, admin only)

**Response (200):**
```json
{
  "success": true,
  "message": "Campaigns fetched",
  "data": {
    "data": [
      {
        "id": "507f1f77bcf86cd799439050",
        "campaignName": "July 2026 - USA Tech CEOs",
        "profileId": "507f1f77bcf86cd799439020",
        "employeeId": "507f1f77bcf86cd799439012",
        "status": "running",
        "totalEmails": 150,
        "pending": 45,
        "sent": 100,
        "failed": 5,
        "replies": 2,
        "startedAt": "2026-07-08T10:31:00Z",
        "createdAt": "2026-07-08T10:30:00Z"
      }
    ],
    "total": 12,
    "page": 1,
    "pageSize": 25,
    "totalPages": 1
  }
}
```

---

### 9.3 Get Campaign
**GET** `/campaigns/{campaignId}`

**Response (200):**
```json
{
  "success": true,
  "message": "Campaign fetched",
  "data": {
    "id": "507f1f77bcf86cd799439050",
    "campaignName": "July 2026 - USA Tech CEOs",
    "profileId": "507f1f77bcf86cd799439020",
    "employeeId": "507f1f77bcf86cd799439012",
    "status": "running",
    "totalEmails": 150,
    "pending": 45,
    "sent": 100,
    "failed": 5,
    "skipped": 0,
    "replies": 2,
    "startedAt": "2026-07-08T10:31:00Z",
    "completedAt": null,
    "pausedAt": null,
    "createdAt": "2026-07-08T10:30:00Z",
    "updatedAt": "2026-07-08T10:40:00Z"
  }
}
```

---

### 9.4 Pause Campaign
**POST** `/campaigns/{campaignId}/pause`

**Response (200):**
```json
{
  "success": true,
  "message": "Campaign paused",
  "data": {
    "id": "507f1f77bcf86cd799439050",
    "status": "paused",
    "pausedAt": "2026-07-08T10:45:00Z"
  }
}
```

---

### 9.5 Resume Campaign
**POST** `/campaigns/{campaignId}/resume`

**Response (200):**
```json
{
  "success": true,
  "message": "Campaign resumed",
  "data": {
    "id": "507f1f77bcf86cd799439050",
    "status": "running",
    "resumedAt": "2026-07-08T10:50:00Z"
  }
}
```

---

## 10. Dashboard Endpoints

### 10.1 Get Employee Dashboard
**GET** `/dashboard/employee?dateRange=7`

**Query Parameters:**
- `dateRange` (optional) 7, 30, 90 days (default: 30)

**Response (200):**
```json
{
  "success": true,
  "message": "Dashboard fetched",
  "data": {
    "todayUploadCount": 3,
    "last7DaysUploadCount": 15,
    "totalUploadCount": 45,
    "uniqueEmailCount": 250,
    "activeProfiles": 3,
    "totalCampaigns": 12,
    "runningCampaigns": 1,
    "sentToday": 45,
    "sentEmailCount": 350,
    "pendingCount": 120,
    "failedCount": 8,
    "successRate": 97.7,
    "dailyLimit": 100,
    "profileStatistics": [
      {
        "profileId": "507f1f77bcf86cd799439020",
        "profileName": "USA SaaS CEOs",
        "pendingCount": 50,
        "sentCount": 200,
        "failedCount": 2
      }
    ],
    "recentCampaigns": [
      {
        "id": "507f1f77bcf86cd799439050",
        "campaignName": "July 2026 - USA Tech CEOs",
        "status": "running",
        "sent": 100,
        "failed": 5
      }
    ],
    "recentUploadHistory": [
      {
        "id": "507f1f77bcf86cd799439060",
        "action": "UPLOAD",
        "uploadedCount": 50,
        "uniqueCount": 45,
        "duplicateCount": 5
      }
    ]
  }
}
```

---

### 10.2 Get Admin Dashboard
**GET** `/dashboard/admin?dateRange=30`

**Response (200):**
```json
{
  "success": true,
  "message": "Dashboard fetched",
  "data": {
    "totalEmployees": 5,
    "totalUploads": 120,
    "totalUniqueEmails": 2500,
    "totalSentEmails": 1200,
    "totalCampaigns": 25,
    "runningCampaigns": 3,
    "activeEmailAccounts": 8,
    "totalPending": 450,
    "totalFailed": 25,
    "employeeRanking": [
      {
        "employeeId": "507f1f77bcf86cd799439012",
        "employeeName": "John Doe",
        "uploadedCount": 45,
        "sentCount": 350
      }
    ],
    "top7DaysUploadRanking": [
      {
        "employeeId": "507f1f77bcf86cd799439012",
        "employeeName": "John Doe",
        "uploadedCount": 25
      }
    ],
    "campaignPerformance": [
      {
        "employeeId": "507f1f77bcf86cd799439012",
        "employeeName": "John Doe",
        "totalCampaigns": 5,
        "totalSent": 350,
        "totalFailed": 5
      }
    ],
    "recentActivities": [
      {
        "id": "507f1f77bcf86cd799439070",
        "action": "UPLOAD",
        "uploadedCount": 50,
        "uniqueCount": 45
      }
    ]
  }
}
```

---

## 11. Logs Endpoints

### 11.1 List Logs
**GET** `/logs?page=1&pageSize=25&action=UPLOAD&employeeId=507f1f77bcf86cd799439012`

**Query Parameters:**
- `page` (optional)
- `pageSize` (optional)
- `action` (optional) UPLOAD, CAMPAIGN_STARTED, CAMPAIGN_COMPLETED
- `employeeId` (optional, admin only)

**Response (200):**
```json
{
  "success": true,
  "message": "Logs fetched",
  "data": {
    "data": [
      {
        "id": "507f1f77bcf86cd799439070",
        "employeeId": "507f1f77bcf86cd799439012",
        "profileId": null,
        "action": "UPLOAD",
        "uploadedCount": 50,
        "uniqueCount": 45,
        "duplicateCount": 5,
        "sentCount": 0,
        "runDate": "2026-07-08T10:30:00Z",
        "createdAt": "2026-07-08T10:30:00Z"
      }
    ],
    "total": 25,
    "page": 1,
    "pageSize": 25,
    "totalPages": 1
  }
}
```

---

## 12. Notifications Endpoints

### 12.1 List Notifications
**GET** `/notifications?page=1&pageSize=50&unreadOnly=false`

**Query Parameters:**
- `page` (optional)
- `pageSize` (optional)
- `unreadOnly` (optional, default=false)

**Response (200):**
```json
{
  "success": true,
  "message": "Notifications fetched",
  "data": [
    {
      "id": "507f1f77bcf86cd799439080",
      "employeeId": "507f1f77bcf86cd799439012",
      "message": "Campaign 'July 2026 - USA Tech CEOs' completed. Sent: 100, Failed: 5.",
      "type": "success",
      "isRead": false,
      "createdAt": "2026-07-08T10:50:00Z"
    }
  ]
}
```

---

### 12.2 Mark Notification as Read
**PATCH** `/notifications/{notificationId}/read`

**Response (200):**
```json
{
  "success": true,
  "message": "Marked as read",
  "data": {
    "id": "507f1f77bcf86cd799439080",
    "isRead": true
  }
}
```

---

### 12.3 Mark All Notifications as Read
**PATCH** `/notifications/read-all`

**Response (200):**
```json
{
  "success": true,
  "message": "All marked as read",
  "data": {
    "modifiedCount": 5
  }
}
```

---

### 12.4 WebSocket — Real-time Notifications
**WebSocket** `/notifications/ws?token=<access_token>`

**Connection:**
```javascript
const ws = new WebSocket('ws://localhost:8000/notifications/ws?token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...');

ws.onmessage = (event) => {
  const message = JSON.parse(event.data);
  console.log(message);
};
```

**Example message received:**
```json
{
  "id": "507f1f77bcf86cd799439080",
  "employeeId": "507f1f77bcf86cd799439012",
  "message": "Campaign 'July 2026 - USA Tech CEOs' completed.",
  "type": "success",
  "isRead": false,
  "createdAt": "2026-07-08T10:50:00Z"
}
```

**Campaign Progress event:**
```json
{
  "type": "campaign_progress",
  "campaignId": "507f1f77bcf86cd799439050",
  "event": "sent",
  "email": "john@acme.com",
  "totalSent": 100,
  "totalFailed": 5
}
```

---

## 13. Reports Endpoints

### 13.1 Export Email Master as CSV
**GET** `/reports/email-master/export?employeeId=507f1f77bcf86cd799439012`

**Response (200):** CSV file download

```csv
fullName,email,company,website,country,state,city,domain,industry,designation,phone,linkedin,uploadBatch,isDuplicate,createdAt
John Smith,john@acme.com,Acme Corp,https://acme.com,USA,California,San Francisco,acme.com,Technology,CEO,+1-555-0100,https://linkedin.com/in/jsmith,batch_a1b2c3d4e5f6,false,2026-07-08T10:30:00Z
```

---

### 13.2 Export Profile Emails as CSV
**GET** `/reports/profile-emails/export?profileId=507f1f77bcf86cd799439020&sendStatus=sent`

**Query Parameters:**
- `profileId` (required)
- `sendStatus` (optional) Filter: pending, sent, failed, all

**Response (200):** CSV file download

```csv
fullName,email,company,country,state,city,domain,industry,designation,sendStatus,threadId,messageId,sentDate,errorMessage,notes,retryCount,createdAt
John Smith,john@acme.com,Acme Corp,USA,California,San Francisco,acme.com,Technology,CEO,sent,<abc123@gmail.com>,<def456@gmail.com>,2026-07-08T10:35:00Z,,Follow up next week,0,2026-07-08T10:30:00Z
```

---

### 13.3 Export Campaigns as CSV
**GET** `/reports/campaigns/export?employeeId=507f1f77bcf86cd799439012`

**Response (200):** CSV file download

```csv
campaignName,profileId,employeeId,status,totalEmails,pending,sent,failed,skipped,replies,startedAt,completedAt,createdAt
July 2026 - USA Tech CEOs,507f1f77bcf86cd799439020,507f1f77bcf86cd799439012,completed,150,0,145,5,0,2,2026-07-08T10:31:00Z,2026-07-08T11:45:00Z,2026-07-08T10:30:00Z
```

---

## 14. Health Check

### 14.1 Health Status
**GET** `/health`

**Response (200):**
```json
{
  "success": true,
  "message": "Service is healthy",
  "version": "2.0.0"
}
```

---

## Postman Collection Quick Setup

### Import Variables
Set these in your Postman environment:

```json
{
  "base_url": "http://localhost:8000",
  "access_token": "",
  "refresh_token": "",
  "user_id": "",
  "employee_id": "",
  "profile_id": "",
  "campaign_id": "",
  "email_account_id": ""
}
```

### Test Workflow Order
1. **Login** → Get tokens → Save to variables
2. **Create/List Users** (admin)
3. **Create/List Employees**
4. **Add Email Account** → Test connection
5. **Upload Email Master**
6. **Create Profile**
7. **Generate Profile Emails**
8. **List Profile Emails**
9. **Start Campaign** → Monitor via WebSocket
10. **Get Dashboard**
11. **Export Reports**

---

## Status Codes Reference

| Code | Meaning |
|---|---|
| 200 | Success |
| 201 | Created |
| 400 | Bad request (validation error) |
| 401 | Unauthorized (missing/invalid token) |
| 403 | Forbidden (insufficient permissions) |
| 404 | Not found |
| 409 | Conflict (e.g., duplicate email) |
| 429 | Rate limited (too many requests) |
| 500 | Internal server error |

---
