from fastapi import HTTPException, status


class AppException(HTTPException):
    """Base application exception with sane defaults."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(status_code=status_code, detail=detail)


class NotFoundException(AppException):
    def __init__(self, detail: str = "Resource not found"):
        super().__init__(status.HTTP_404_NOT_FOUND, detail)


class BadRequestException(AppException):
    def __init__(self, detail: str = "Bad request"):
        super().__init__(status.HTTP_400_BAD_REQUEST, detail)


class UnauthorizedException(AppException):
    def __init__(self, detail: str = "Not authenticated"):
        super().__init__(status.HTTP_401_UNAUTHORIZED, detail)


class ForbiddenException(AppException):
    def __init__(self, detail: str = "Not permitted to perform this action"):
        super().__init__(status.HTTP_403_FORBIDDEN, detail)


class ConflictException(AppException):
    def __init__(self, detail: str = "Resource conflict"):
        super().__init__(status.HTTP_409_CONFLICT, detail)
