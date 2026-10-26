"""FastAPI application with real model-service analysis and independent live feed."""
from contextlib import asynccontextmanager
import time
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from .api.routes import router
from .container import build_container
from .errors import FeatureNotImplemented, ServiceError
from .settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_environment()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.container = build_container(settings)
        try:
            yield
        finally:
            application.state.container.close()

    application = FastAPI(title='Chainrisk API', version='0.1.0', lifespan=lifespan)

    @application.exception_handler(ServiceError)
    async def service_error(_request: Request, error: ServiceError):
        return JSONResponse(status_code=error.status_code, content=error.public_body(),
                            headers=error.response_headers(time.time()))

    @application.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, _error: RequestValidationError):
        error = ServiceError('invalid_request')
        return JSONResponse(status_code=422, content=error.public_body())

    @application.exception_handler(Exception)
    async def unexpected_error(_request: Request, _error: Exception):
        error = ServiceError('internal_error')
        return JSONResponse(status_code=500, content=error.public_body())

    @application.exception_handler(FeatureNotImplemented)
    async def not_implemented(_request: Request, error: FeatureNotImplemented):
        return JSONResponse(status_code=501, content={'code': 'not_implemented',
            'operation': error.operation, 'message': str(error)})

    application.include_router(router, prefix=settings.api_prefix,
                               responses={501: {'description': 'Integration not implemented'}})
    return application

app = create_app()
