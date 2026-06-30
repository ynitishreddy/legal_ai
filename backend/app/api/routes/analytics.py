from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Query

from app.schemas import AnalyticsOverviewResponse
from app.services.mock_data import MockDataService

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("", response_model=AnalyticsOverviewResponse, summary="Get analytics overview")
async def get_analytics(
    case_id: Optional[UUID] = Query(None),
    category: Optional[str] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
) -> AnalyticsOverviewResponse:
    return MockDataService.get_analytics()


@router.get("/metrics", summary="Get analytics metrics")
async def get_metrics() -> dict:
    data = MockDataService.get_analytics()
    return {"metrics": data.metrics}


@router.get("/charts", summary="Get analytics charts")
async def get_charts() -> dict:
    data = MockDataService.get_analytics()
    return {"charts": data.charts}
