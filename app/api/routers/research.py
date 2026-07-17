from fastapi import APIRouter, Depends

from app.api.deps import (
    SettingsDep,
    get_research_sessionmaker,
    get_search_provider_dep,
    require_api_key,
)
from app.schemas.research import ResearchRequest, ResearchResponse
from app.services.research import research as run_research

router = APIRouter(prefix="/v1", tags=["research"], dependencies=[Depends(require_api_key)])


@router.post("/research", response_model=ResearchResponse)
async def create_research(
    body: ResearchRequest,
    settings: SettingsDep,
    search_provider=Depends(get_search_provider_dep),
    sessionmaker=Depends(get_research_sessionmaker),
) -> ResearchResponse:
    execution_mode = body.execution_mode or settings.research_execution_mode_default
    return await run_research(
        sessionmaker,
        search_provider,
        settings,
        query=body.query,
        limit=body.limit,
        refresh=body.refresh,
        execution_mode=execution_mode,
        mode=body.mode,
    )
