"""Health endpoint — walking skeleton proof of FastAPI -> AsyncSession -> Postgres round-trip."""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SenderAllowlist
from app.db.session import get_db

router = APIRouter()


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    """Walking skeleton: proves FastAPI -> AsyncSession -> Postgres round-trip works."""
    result = await db.execute(
        select(func.count()).select_from(SenderAllowlist)
    )
    count = result.scalar_one()
    return {"status": "ok", "allowlist_count": count, "db": "connected"}
