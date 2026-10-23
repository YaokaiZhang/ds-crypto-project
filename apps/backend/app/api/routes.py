from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse, StreamingResponse
from .dependencies import get_container
from .schemas import AnalysisRequest, AnalysisResult, GraphView, ActivitySeries, TransactionPage, FeedSnapshot
from ..container import Container
from ..domain import TaskId
from ..application.strategies import TASK_STRATEGIES

router = APIRouter()
Services = Annotated[Container, Depends(get_container)]

@router.get('/health/live', tags=['health'])
def live(services: Services):
    return {'status': 'ok', 'mode': 'demo' if services.demo else 'template'}

@router.get('/health/ready', tags=['health'], responses={503: {'description': 'Template integrations are unavailable'}})
async def ready(services: Services):
    feed_ready = bool(services.feed_store and services.feed_store.snapshot(1)['status'] == 'live')
    if services.demo:
        return {'status': 'ready', 'mode': 'demo', 'components': {'analysis': True, 'inference': False, 'feed': feed_ready}}
    return JSONResponse(status_code=503, content={'status': 'not_ready', 'mode': 'template',
        'components': {'repository': False, 'providers': False, 'inference': False, 'feed': feed_ready}})

@router.get('/capabilities', tags=['capabilities'])
def capabilities(services: Services):
    if services.demo:
        return {**services.demo.capabilities(), 'feed_enabled': services.feed_store is not None}
    return {'mode': 'template', 'analysis_enabled': False, 'feed_enabled': services.feed_store is not None,
            'tasks': [{'task_id': spec.task_id, 'entity': spec.entity,
                       'graph_family': spec.graph_family, 'stage': spec.stage,
                       'model_available': False} for spec in TASK_STRATEGIES.values()]}

@router.post('/analyses', response_model=AnalysisResult, status_code=202, tags=['analyses'])
async def create_analysis(body: AnalysisRequest, services: Services,
                          idempotency_key: Annotated[str | None, Header(min_length=1, max_length=128)] = None):
    return await services.analysis.create(body.to_command(), idempotency_key)

@router.get('/analyses/{analysis_id}', response_model=AnalysisResult, tags=['analyses'])
async def get_analysis(analysis_id: UUID, services: Services):
    return await services.analysis.get(str(analysis_id))

@router.get('/analyses/{analysis_id}/graphs/{task}', response_model=GraphView, tags=['analyses'])
async def get_graph(analysis_id: UUID, task: TaskId, services: Services):
    return await services.analysis.graph(str(analysis_id), task)

@router.get('/analyses/{analysis_id}/activity', response_model=ActivitySeries, tags=['analyses'])
async def get_activity(analysis_id: UUID, services: Services):
    return await services.analysis.activity(str(analysis_id))

@router.get('/analyses/{analysis_id}/transactions', response_model=TransactionPage, tags=['analyses'])
async def get_transactions(analysis_id: UUID, services: Services,
                           limit: Annotated[int, Query(ge=1, le=100)] = 30, cursor: str | None = None,
                           category: Annotated[str | None, Query(pattern='^(external|internal|token_transfer|pool_event)$')] = None):
    if services.demo:
        return await services.analysis.transactions(str(analysis_id), limit, cursor, category)
    return await services.analysis.transactions(str(analysis_id), limit, cursor)

@router.get('/analyses/{analysis_id}/events', response_class=StreamingResponse, tags=['analyses'])
async def analysis_events(analysis_id: UUID, services: Services,
                          last_event_id: Annotated[str | None, Header()] = None):
    return await services.analysis.events(str(analysis_id), last_event_id)

@router.get('/feed/recent', response_model=FeedSnapshot, tags=['feed'])
async def recent_feed(services: Services, limit: Annotated[int, Query(ge=1, le=100)] = 30):
    return await services.feed.recent(limit)

@router.get('/feed/events', response_class=StreamingResponse, tags=['feed'])
async def feed_events(services: Services, last_event_id: Annotated[str | None, Header()] = None):
    return await services.feed.events(last_event_id)
