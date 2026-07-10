import math

from fastapi import Query

from app.schemas.common import PaginatedResponse, PaginationParams


def pagination_params(
    page: int = Query(1, ge=1),
    pageSize: int = Query(25, ge=1, le=500),
) -> PaginationParams:
    return PaginationParams(page=page, pageSize=pageSize)


def build_paginated_response(items: list, total: int, params: PaginationParams) -> PaginatedResponse:
    total_pages = math.ceil(total / params.pageSize) if total else 0
    return PaginatedResponse(
        data=items,
        total=total,
        page=params.page,
        pageSize=params.pageSize,
        totalPages=total_pages,
    )
