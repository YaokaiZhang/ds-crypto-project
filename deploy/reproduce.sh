#!/usr/bin/env bash
# One-command reviewer reproduction: build, start and verify the model API.
#
#   deploy/reproduce.sh            # container (docker or podman), default
#   deploy/reproduce.sh local      # Python 3.11 venv, no container
#   deploy/reproduce.sh verify URL # only check an already running service (e.g. a Space)
#
# Downloads the pinned Release bundles, verifies every checksum, starts the
# service on port 7860 with a random API key and runs deploy/verify_service.py.
# The service keeps running afterwards; the script prints how to stop it.
set -euo pipefail
cd "$(dirname "$0")/.."
MODE=${1:-container}
PORT=${PORT:-7860}
IMAGE=${IMAGE:-chainrisk-model-api}
if [ "$MODE" = verify ]; then
  # Uses the caller's INFERENCE_API_KEY / HF_TOKEN, if set, for a remote service.
  exec python3 deploy/verify_service.py "${2:?usage: deploy/reproduce.sh verify URL}"
fi
export INFERENCE_API_KEY=${INFERENCE_API_KEY:-$(python3 -c 'import secrets; print(secrets.token_hex(24))')}

case "$MODE" in
  container)
    ENGINE=${ENGINE:-$(command -v docker || command -v podman || true)}
    [ -n "$ENGINE" ] || { echo "Install Docker (or podman), or run: deploy/reproduce.sh local" >&2; exit 1; }
    "$ENGINE" build -f deploy/Dockerfile -t "$IMAGE" .
    "$ENGINE" rm -f chainrisk-model-api >/dev/null 2>&1 || true
    "$ENGINE" run -d --name chainrisk-model-api -p "$PORT:7860" -e INFERENCE_API_KEY "$IMAGE" >/dev/null
    STOP="$ENGINE rm -f chainrisk-model-api"
    ;;
  local)
    BUILD=deploy/.build/reviewer-$(date +%Y%m%d-%H%M%S)
    PYTHON=${PYTHON:-python3.11}
    "$PYTHON" -m venv "$BUILD/venv"
    "$BUILD/venv/bin/pip" install --quiet --index-url https://download.pytorch.org/whl/cpu torch==2.14.1
    "$BUILD/venv/bin/pip" install --quiet gradio==6.30.0
    "$BUILD/venv/bin/python" deploy/fetch_release.py --output "$BUILD/release"
    "$BUILD/venv/bin/python" deploy/inference_service/prepare.py --config "$BUILD/release/models.json" --output "$BUILD/space"
    pushd "$BUILD/space" >/dev/null
    PORT=$PORT GRADIO_ANALYTICS_ENABLED=False nohup ../venv/bin/python app.py > ../server.log 2>&1 &
    echo $! > ../server.pid
    popd >/dev/null
    STOP="kill \$(cat $BUILD/server.pid)"
    echo "server log: $BUILD/server.log"
    ;;
  *) echo "usage: deploy/reproduce.sh [container|local|verify URL]" >&2; exit 2 ;;
esac

python3 deploy/verify_service.py "http://127.0.0.1:$PORT"
echo
echo "Model API: http://127.0.0.1:$PORT  (header X-Inference-Key: $INFERENCE_API_KEY)"
echo "Stop it:   $STOP"
