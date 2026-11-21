from datetime import date
from enum import Enum

from pydantic import BaseModel


class DateRangePreset(str, Enum):
    TODAY = "today"
    YESTERDAY = "yesterday"
    LAST_7_DAYS = "last_7_days"
    LAST_MONTH = "last_month"
    CUSTOM = "custom"


class DashboardQuery(BaseModel):
    preset: DateRangePreset = DateRangePreset.LAST_7_DAYS
    startDate: date | None = None
    endDate: date | None = None


class ProfileStat(BaseModel):
    profileId: str
    profileName: str
    uploadedCount: int
    sentCount: int


class EmployeeDashboard(BaseModel):
    todayUploadCount: int
    last7DaysUploadCount: int
    totalUploadCount: int
    uniqueEmailCount: int
    allTimeUploadCount: int
    allTimeUniqueEmailCount: int
    sentEmailCount: int


class AdminDashboard(BaseModel):
    totalEmployees: int
    totalUploads: int
    totalUniqueEmails: int
    totalSentEmails: int
    totalProfiles: int
    activeProfiles: int
    employeeStatistics: list[dict]


class AdminScopedDashboard(BaseModel):
    adminOwnUploads: int
    assignedEmployeeUploads: int
    totalUploads: int
    totalDuplicates: int
    totalUniqueEmails: int
    totalSentToProfiles: int
    totalSent: int
    totalCampaigns: int
    runningCampaigns: int
    totalProfiles: int
    activeProfiles: int
