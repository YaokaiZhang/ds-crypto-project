"""FastAPI application with optional analysis demo and independent live feed."""
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from .api.routes import router
from .container import build_container
from .errors import FeatureNotImplemented
from .settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_environment()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.container = build_container(settings)
        if application.state.container.demo:
            await application.state.container.demo.start()
        try:
            yield
        finally:
            if application.state.container.demo:
                await application.state.container.demo.close()
            application.state.container.close()

    application = FastAPI(title='Chainrisk API', version='0.1.0', lifespan=lifespan)

    @application.exception_handler(FeatureNotImplemented)
    async def not_implemented(_request: Request, error: FeatureNotImplemented):
        return JSONResponse(status_code=501, content={'code': 'not_implemented',
            'operation': error.operation, 'message': str(error)})

    application.include_router(router, prefix=settings.api_prefix,
                               responses={501: {'description': 'Integration not implemented'}})
    return application

app = create_app()
