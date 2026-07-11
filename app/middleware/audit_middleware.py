"""
Admin Audit Logging Middleware

Logs all actions performed by admin users (when they override employee context).
Stores audit records in MongoDB for compliance and accountability.
"""

import logging
import json
from datetime import datetime, timezone
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.security import decode_token
from app.database.mongodb import get_collection

logger = logging.getLogger("app.audit")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

AUDIT_COLLECTION = "audit_logs"

# HTTP methods that modify data (should be audited for admins)
MODIFYING_METHODS = {"POST", "PATCH", "PUT", "DELETE"}

# Paths that don't need admin audit logging (internal, health checks, etc)
EXCLUDED_PATHS = {
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/favicon.ico",
}


class AuditLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware that logs all admin actions when they override employee context.
    
    Captures:
    - Admin user ID
    - Target employee ID (if admin is acting as another employee)
    - HTTP method and path
    - Request parameters
    - Timestamp
    - Status code
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip excluded paths
        if request.url.path in EXCLUDED_PATHS:
            return await call_next(request)

        # Only audit modifying operations
        if request.method not in MODIFYING_METHODS:
            return await call_next(request)

        # Extract JWT token and check if admin
        admin_info = await self._extract_admin_context(request)
        
        # Process request
        response = await call_next(request)
        
        # Log if admin performed action
        if admin_info:
            await self._log_audit(request, response, admin_info)

        return response

    async def _extract_admin_context(self, request: Request) -> dict | None:
        """
        Extract admin user info from JWT token.
        Returns admin context if user is admin, None otherwise.
        """
        try:
            # Get auth header
            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                return None

            token = auth_header.split(" ")[1]
            payload = decode_token(token)

            # Check if admin
            if payload.get("role") != "admin":
                return None

            # Get target employee ID from query params (if provided)
            target_employee_id = request.query_params.get("employeeId")

            return {
                "admin_user_id": payload.get("sub"),
                "target_employee_id": target_employee_id,
                "role": payload.get("role"),
            }
        except Exception:
            return None

    async def _log_audit(
        self,
        request: Request,
        response: Response,
        admin_info: dict
    ) -> None:
        """Log admin action to audit collection."""
        try:
            audit_col = get_collection(AUDIT_COLLECTION)

            # Extract query parameters
            query_params = dict(request.query_params)
            
            audit_record = {
                "timestamp": datetime.now(timezone.utc),
                "admin_user_id": admin_info["admin_user_id"],
                "target_employee_id": admin_info["target_employee_id"],
                "method": request.method,
                "path": request.url.path,
                "query_params": query_params,
                "status_code": response.status_code,
                "action": self._classify_action(request.method, request.url.path),
                "success": 200 <= response.status_code < 300,
            }

            # Insert into audit log
            await audit_col.insert_one(audit_record)

            # Also log to application logger
            logger.info(
                f"ADMIN_ACTION: admin={admin_info['admin_user_id']} "
                f"target_emp={admin_info['target_employee_id']} "
                f"{request.method} {request.url.path} "
                f"status={response.status_code}"
            )
        except Exception as e:
            logger.error(f"Failed to log audit record: {str(e)}")

    @staticmethod
    def _classify_action(method: str, path: str) -> str:
        """Classify the action type for readability."""
        if method == "POST":
            if "/start" in path:
                return "campaign_started"
            elif "/upload" in path:
                return "file_uploaded"
            return "created"
        elif method == "PATCH":
            return "updated"
        elif method == "DELETE":
            return "deleted"
        elif method == "PUT":
            return "replaced"
        return "modified"
