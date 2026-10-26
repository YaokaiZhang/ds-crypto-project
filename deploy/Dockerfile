# CPU model API image: pinned Release bundles + the same Gradio app as the HF Space.
# Build from the repository root:  docker build -f deploy/Dockerfile -t chainrisk-model-api .
# Runs on linux/amd64 and linux/arm64 (any Docker host, Verda, HF Docker Spaces).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 GRADIO_ANALYTICS_ENABLED=False PORT=7860
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.14.1 \
 && pip install --no-cache-dir gradio==6.30.0

WORKDIR /src
COPY packages/ packages/
COPY deploy/ deploy/
# Download + checksum-verify the pinned bundles, then build the same folder uploaded to the Space.
RUN python deploy/fetch_release.py --output /src/release \
 && python deploy/inference_service/prepare.py --config /src/release/models.json --output /app \
 && rm -rf /src/release/downloads

WORKDIR /app
RUN useradd --create-home --uid 1000 app
USER app
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
  CMD python -c "import os, urllib.request; request=urllib.request.Request('http://127.0.0.1:7860/health/ready', headers={'X-Inference-Key':os.environ.get('INFERENCE_API_KEY','')}); urllib.request.urlopen(request, timeout=4)"
CMD ["python", "app.py"]
