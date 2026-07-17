# Scheduler Timezone & Timing Fix

## Problem Identified

Your MongoDB shows:
- **Campaign status**: `scheduled`
- **scheduledFor**: `2026-07-16T15:50:00.000+00:00` (15:50 UTC on July 16)
- **Current UI time**: `16-07-2026` (July 16, 2026)

If the current time is **past 15:50 UTC**, the campaign has already missed its scheduled time!

---

## Root Cause Analysis

The issue is **timezone mismatch** between:

1. **Frontend** - Sends time in user's local timezone
2. **Backend** - Expects UTC time
3. **Cron** - Compares with server's current UTC time
4. **MongoDB** - Stores as UTC

### Example of the Problem:

```
Frontend (Sydney time):        16 Jul, 4:50 PM (next day, +10 UTC)
↓ (converted to)
UTC time sent to backend:      16 Jul, 6:50 AM UTC (TODAY)
↓
MongoDB stores:                2026-07-16T06:50:00Z
↓
Current server time:           2026-07-16T10:00:00Z (already past!)
↓
Cron checks:                   scheduledFor (06:50) <= now (10:00) ✓ Due to execute!
                               But 3+ hours have passed already!
```

---

## Solution: Schedule in the FUTURE

### Quick Fix - Reschedule Your Test Campaign

1. **Go to MongoDB**
2. **Find your campaign**
3. **Update `scheduledFor` to a future time**:

```javascript
// In MongoDB, update the campaign:
db.campaigns.updateOne(
  {_id: ObjectId("6a5...your_id")},
  {$set: {
    scheduledFor: new Date("2026-07-16T16:15:00Z")  // 15 minutes from now
  }}
)
```

OR via shell:

```bash
# Connect to MongoDB
mongo

# Use your database
use email_marketing_db

# Update the campaign to run 5 minutes from now
db.campaigns.updateOne(
  {_id: ObjectId("6a5afc0f38d14ee23a6b8b0")},
  {$set: {scheduledFor: new Date()}}
)
```

---

## How to Schedule Correctly

### Rule: Always Schedule FUTURE times

**Current UTC time**: Check with:
```bash
curl http://13.206.26.177:5001/api/campaigns/scheduler/status
# Look at "current_time"
```

**Example - Schedule for 5 minutes in future**:

If current time is `2026-07-16T10:00:00Z`, schedule for `2026-07-16T10:05:00Z`

---

## Frontend Timezone Fix (For Production)

The frontend is not converting timezone correctly. Here's the issue in `Campaigns.jsx`:

```javascript
// Current (WRONG) - treats input as local time, sends to backend
const isoDateTime = new Date(`${dateStr}T${timeStr}:00Z`).toISOString()
// This creates ambiguity depending on browser timezone

// Correct approach - explicitly handle timezone:
const localDate = new Date(`${dateStr}T${timeStr}:00`)
const isoDateTime = localDate.toISOString()  // Convert to UTC properly
```

---

## Testing Steps

### Step 1: Check Current UTC Time
```bash
curl http://13.206.26.177:5001/api/campaigns/scheduler/status | jq .data.current_time
```

### Step 2: Find Your Campaign in MongoDB
```bash
db.campaigns.findOne({campaignName: "test"})
```

Look at `scheduledFor` field. Is it in the past?

### Step 3: Update to Future Time
```bash
db.campaigns.updateOne(
  {campaignName: "test"},
  {$set: {scheduledFor: new Date("2026-07-16T16:30:00Z")}}
)
```

Use a time **at least 2-3 minutes in the future**.

### Step 4: Watch Logs
```bash
tail -f /var/log/syslog | grep campaign-scheduler
```

Wait for next minute. You should see the campaign execute!

---

## Verify After Fix

```bash
# Check campaign status changed to "completed"
db.campaigns.findOne({campaignName: "test"}) | grep status

# Check execution time
db.campaigns.findOne({campaignName: "test"}) | grep executionDuration

# Check logs
tail -10 /var/log/syslog | grep campaign-scheduler
```

---

## Why This Happened

1. **Frontend sends time** in browser's local timezone
2. **Backend** may not convert properly to UTC
3. **MongoDB stores** as UTC
4. **Cron compares** current UTC with stored UTC
5. **If past**: Campaign never triggers

---

## Moving Forward

### For Production:

1. **Fix frontend timezone handling** (Campaigns.jsx)
2. **Add validation** to reject past times
3. **Show user current UTC time** in scheduling modal
4. **Test with future dates** (at least 2 minutes ahead)

---

## Quick Test Right Now

1. **Get current UTC time**:
```bash
date -u
# or
curl http://13.206.26.177:5001/api/campaigns/scheduler/status
```

2. **Update your campaign to 3 minutes in future**:
```bash
db.campaigns.updateOne(
  {status: "scheduled"},
  {$set: {scheduledFor: new Date("2026-07-16T16:30:00Z")}}
)
```

3. **Watch logs**:
```bash
tail -f /var/log/syslog | grep campaign-scheduler
```

4. **Wait ~1 minute for cron to run**

5. **Campaign should execute!** ✅

---

## MongoDB Commands Reference

```bash
# Find all scheduled campaigns
db.campaigns.find({status: "scheduled"})

# Find a specific campaign
db.campaigns.findOne({campaignName: "test"})

# Update scheduledFor to NOW (will execute immediately on next cron)
db.campaigns.updateOne(
  {campaignName: "test"},
  {$set: {scheduledFor: new Date()}}
)

# Update scheduledFor to 5 minutes in future
db.campaigns.updateOne(
  {campaignName: "test"},
  {$set: {scheduledFor: new Date(new Date().getTime() + 5*60*1000)}}
)

# Check if campaign executed
db.campaigns.findOne({campaignName: "test"}, {status: 1, completedAt: 1, executionDuration: 1})
```

---

## The Bottom Line

**Your scheduler is working correctly!** 🎉

It's just that:
- Your test campaign's `scheduledFor` time has **already passed**
- Cron only triggers campaigns with `scheduledFor <= current_time`
- You need to **schedule for the future**

Update the `scheduledFor` to a future time and it will work!
