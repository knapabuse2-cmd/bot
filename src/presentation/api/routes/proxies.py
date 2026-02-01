"""
Proxies API routes.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from src.infrastructure.database.repositories import PostgresProxyRepository
from src.domain.entities import Proxy, ProxyType, ProxyStatus

from ..dependencies import get_proxy_repo
from ..schemas import (
    ProxyCreate,
    ProxyBulkCreate,
    ProxyResponse,
    ProxyListResponse,
)

router = APIRouter()


@router.get("", response_model=ProxyListResponse)
async def list_proxies(
    status: Optional[str] = Query(None, description="Filter by status"),
    available_only: bool = Query(False, description="Only available proxies"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    repo: PostgresProxyRepository = Depends(get_proxy_repo),
):
    """List all proxies."""
    if available_only:
        proxies = await repo.list_available()
    elif status:
        try:
            proxy_status = ProxyStatus(status)
            proxies = await repo.list_by_status(proxy_status)
        except ValueError:
            raise HTTPException(400, f"Invalid status: {status}")
    else:
        proxies = await repo.list_all(limit=per_page * page)
    
    # Pagination
    total = len(proxies)
    start = (page - 1) * per_page
    end = start + per_page
    paginated = proxies[start:end]
    
    return ProxyListResponse(
        items=[_proxy_to_response(p) for p in paginated],
        total=total,
        page=page,
        per_page=per_page,
        pages=(total + per_page - 1) // per_page,
    )


@router.get("/{proxy_id}", response_model=ProxyResponse)
async def get_proxy(
    proxy_id: UUID,
    repo: PostgresProxyRepository = Depends(get_proxy_repo),
):
    """Get proxy by ID."""
    proxy = await repo.get_by_id(proxy_id)
    if not proxy:
        raise HTTPException(404, "Proxy not found")
    return _proxy_to_response(proxy)


@router.post("", response_model=ProxyResponse, status_code=201)
async def create_proxy(
    data: ProxyCreate,
    repo: PostgresProxyRepository = Depends(get_proxy_repo),
):
    """Create a new proxy."""
    # Check if exists
    existing = await repo.get_by_address(data.host, data.port)
    if existing:
        raise HTTPException(400, "Proxy already exists")
    
    try:
        proxy_type = ProxyType(data.proxy_type)
    except ValueError:
        raise HTTPException(400, f"Invalid proxy type: {data.proxy_type}")
    
    proxy = Proxy(
        host=data.host,
        port=data.port,
        proxy_type=proxy_type,
        username=data.username,
        password=data.password,
        status=ProxyStatus.UNKNOWN,
    )
    
    await repo.save(proxy)
    return _proxy_to_response(proxy)


@router.post("/bulk", status_code=201)
async def create_proxies_bulk(
    data: ProxyBulkCreate,
    repo: PostgresProxyRepository = Depends(get_proxy_repo),
):
    """Bulk create proxies."""
    added = 0
    skipped = 0
    
    for p in data.proxies:
        existing = await repo.get_by_address(p.host, p.port)
        if existing:
            skipped += 1
            continue
        
        try:
            proxy_type = ProxyType(p.proxy_type)
        except ValueError:
            skipped += 1
            continue
        
        proxy = Proxy(
            host=p.host,
            port=p.port,
            proxy_type=proxy_type,
            username=p.username,
            password=p.password,
            status=ProxyStatus.UNKNOWN,
        )
        
        await repo.save(proxy)
        added += 1
    
    return {"added": added, "skipped": skipped}


@router.delete("/{proxy_id}", status_code=204)
async def delete_proxy(
    proxy_id: UUID,
    repo: PostgresProxyRepository = Depends(get_proxy_repo),
):
    """Delete a proxy."""
    deleted = await repo.delete(proxy_id)
    if not deleted:
        raise HTTPException(404, "Proxy not found")


@router.get("/stats/summary")
async def get_proxy_stats(
    repo: PostgresProxyRepository = Depends(get_proxy_repo),
):
    """Get proxy statistics."""
    all_proxies = await repo.list_all(limit=1000)
    available = await repo.count_available()
    
    by_status = {}
    for p in all_proxies:
        status = p.status.value
        by_status[status] = by_status.get(status, 0) + 1
    
    by_type = {}
    for p in all_proxies:
        ptype = p.proxy_type.value
        by_type[ptype] = by_type.get(ptype, 0) + 1
    
    return {
        "total": len(all_proxies),
        "available": available,
        "by_status": by_status,
        "by_type": by_type,
    }


def _proxy_to_response(proxy: Proxy) -> ProxyResponse:
    """Convert proxy entity to response."""
    return ProxyResponse(
        id=proxy.id,
        host=proxy.host,
        port=proxy.port,
        proxy_type=proxy.proxy_type.value,
        username=proxy.username,
        status=proxy.status.value,
        assigned_account_id=proxy.assigned_account_id,
        last_check_at=proxy.last_check_at,
        last_check_latency_ms=proxy.last_check_latency_ms,
        fail_count=proxy.fail_count,
        created_at=proxy.created_at,
    )
