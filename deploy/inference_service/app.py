"""Gradio Server Mode entrypoint for a single multi-model Space."""
from __future__ import annotations

import hmac
import logging
import os
from pathlib import Path

from fastapi.responses import JSONResponse
from gradio import Server

try:
    from .runtime import BusyError, InferenceRuntime
except ImportError:
    from runtime import BusyError, InferenceRuntime

HERE = Path(__file__).resolve().parent
log = logging.getLogger(__name__)


class RequestGuard:
    """Protect both Gradio and REST inference routes and bound request bodies."""
    def __init__(self, app, *, api_key='', max_bytes=16 * 1024 * 1024):
        self.app, self.api_key, self.max_bytes = app, api_key, max_bytes

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = dict(scope['headers'])
        path = scope['path']
        protected = path in ('/predict', '/models', '/health/ready') or (
            path.startswith('/gradio_api/') and path != '/gradio_api/startup-events')
        if self.api_key and protected:
            supplied = headers.get(b'x-inference-key', b'')
            if not hmac.compare_digest(supplied, self.api_key.encode()):
                return await JSONResponse({'detail': 'Unauthorized'}, status_code=401)(scope, receive, send)
        if scope['method'] in ('POST', 'PUT', 'PATCH'):
            body = bytearray()
            while True:
                message = await receive()
                if message['type'] == 'http.disconnect':
                    return
                body.extend(message.get('body', b''))
                if len(body) > self.max_bytes:
                    return await JSONResponse({'detail': 'Request too large'}, status_code=413)(scope, receive, send)
                if not message.get('more_body', False):
                    break
            delivered = False

            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
                return await receive()

            return await self.app(scope, replay, send)
        return await self.app(scope, receive, send)


def create_app(runtime=None, *, api_key=None):
    runtime = runtime or InferenceRuntime(
        os.getenv('MODEL_CONFIG') or HERE / 'models.json',
        device=os.getenv('INFERENCE_DEVICE', 'cpu'),
        risk_policy_path=os.getenv('RISK_POLICY_PATH') or (
            HERE / 'risk_policies.json' if (HERE / 'risk_policies.json').exists()
            else HERE.parent / 'registry/risk_policies.json'),
        forecast_policy_path=os.getenv('FORECAST_POLICY_PATH') or (
            HERE / 'forecast_policy.json' if (HERE / 'forecast_policy.json').exists()
            else HERE.parent / 'registry/forecast_policy.json'))
    app = Server(title='Chainrisk inference', docs_url=None, redoc_url=None)
    app.add_middleware(RequestGuard, api_key=os.getenv('INFERENCE_API_KEY', '') if api_key is None else api_key)

    def infer(payload: dict) -> dict:
        try:
            return runtime.predict(payload)
        except BusyError:
            return {'status': 'busy', 'score': None, 'reason': 'Inference is busy; retry later.'}
        except (ValueError, KeyError, TypeError, IndexError, OverflowError):
            return {'status': 'invalid_input', 'score': None, 'reason': 'Input does not match the model contract.'}
        except Exception:
            log.exception('Inference failed')
            return {'status': 'model_error', 'score': None, 'reason': 'Model execution failed.'}

    @app.api(name='predict', concurrency_limit=1)
    def predict(payload: dict) -> dict:
        """Predict one task from its canonical graph_sample; no labels required."""
        return infer(payload)

    @app.post('/predict')
    def predict_rest(payload: dict):
        result = infer(payload)
        status = {'busy': 429, 'invalid_input': 422, 'model_error': 500, 'model_unavailable': 503}.get(result['status'], 200)
        return JSONResponse(result, status_code=status,
                            headers={'Retry-After': '2'} if status == 429 else None)

    @app.get('/health/live')
    def live():
        return {'status': 'ok'}

    @app.get('/health/ready')
    def ready():
        return {'status': 'ready', 'loaded_tasks': list(runtime.bundles)}

    @app.get('/models')
    def models():
        return runtime.models()

    @app.get('/')
    def index():
        return {'service': 'Chainrisk inference', 'models': '/models', 'health': '/health/ready',
                'rest': 'POST /predict', 'gradio': '/gradio_api/call/predict'}

    return app


if __name__ == '__main__':
    os.environ.setdefault('GRADIO_ANALYTICS_ENABLED', 'False')
    create_app().launch(server_name='0.0.0.0', server_port=int(os.getenv('PORT', '7860')),
                        share=False, show_error=False)
