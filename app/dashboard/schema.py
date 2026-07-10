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
    sentEmailCount: int
    profileStatistics: list[ProfileStat]
    recentUploadHistory: list[dict]


class EmployeeRanking(BaseModel):
    employeeId: str
    employeeName: str
    uploadedCount: int
    sentCount: int


class Top7DaysRanking(BaseModel):
    employeeId: str
    employeeName: str
    uploadedCount: int


class AdminDashboard(BaseModel):
    totalEmployees: int
    totalUploads: int
    totalUniqueEmails: int
    totalSentEmails: int
    employeeRanking: list[EmployeeRanking]
    top7DaysUploadRanking: list[Top7DaysRanking]
    employeeStatistics: list[dict]
    recentActivities: list[dict]
    profileUsage: list[dict]
