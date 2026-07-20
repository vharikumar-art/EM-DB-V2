import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.auth.router import router as auth_router
from app.campaigns.router import router as campaigns_router
from app.core.config import settings
from app.core.rate_limit import limiter
from app.dashboard.router import router as dashboard_router
from app.database.indexes import create_indexes
from app.database.mongodb import close_mongo_connection, connect_to_mongo
from app.email_accounts.router import router as email_accounts_router
from app.email_master.router import router as email_master_router
from app.employees.router import router as employees_router
from app.logs.router import router as logs_router
from app.middleware.error_handler import register_exception_handlers
from app.middleware.logging_middleware import RequestLoggingMiddleware
from app.middleware.audit_middleware import AuditLoggingMiddleware
from app.notifications.router import router as notifications_router
from app.options.router import router as options_router
from app.profile_emails.router import router as profile_emails_router
from app.profiles.router import router as profiles_router
from app.reports.router import router as reports_router
from app.templates.router import router as templates_router
from app.users.router import router as users_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await connect_to_mongo()
    await create_indexes()
    
    yield
    
    # Shutdown
    await close_mongo_connection()


app = FastAPI(
    title=settings.APP_NAME,
    version="2.0.0",
    description="Cold Email Management Platform — FastAPI + MongoDB + LangChain",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    # allow_origins=settings.cors_origins_list,
    allow_origins=["http://localhost:5173", "http://13.206.26.177:5001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuditLoggingMiddleware)
app.add_middleware(RequestLoggingMiddleware)

register_exception_handlers(app)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(employees_router)

app.include_router(email_accounts_router)   # Gmail / SMTP credential store
app.include_router(email_master_router)     # Permanent lead database
app.include_router(profiles_router)         # Campaign profiles (subject/body/filters)
app.include_router(profile_emails_router)   # Working email list per profile
app.include_router(templates_router)        # Reusable email templates
app.include_router(campaigns_router)        # Campaign lifecycle + start/pause/resume

app.include_router(dashboard_router)
app.include_router(logs_router)
app.include_router(reports_router)
app.include_router(notifications_router)
app.include_router(options_router)


# ────────────────────────────────────────────────────────────────────────────
# DEBUG ENDPOINTS - Remove in production
# ────────────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["Health"])
async def health_check():
    return {"success": True, "message": "Service is healthy", "version": "2.0.0"}
