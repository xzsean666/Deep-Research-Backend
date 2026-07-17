from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from app.api.deps import DbSessionDep

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    return {"ok": True}


@router.get("/ready")
async def ready(session: DbSessionDep) -> dict:
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database not reachable") from exc
    return {"ok": True}
