#!/usr/bin/env bash
# Run the UHP conformance suite against a local SuperQode `serve uhp` bind.
#
#   export GEMINI_API_KEY=...
#   scripts/run_uhp_conformance.sh
#
# Runs about six real Gemini Flash tasks, so it costs tokens and a few minutes.
# Everything happens in a scratch directory, never in the repository.
#
# Environment:
#   GEMINI_API_KEY  required
#   WORK            scratch directory (default: a fresh mktemp -d)
#   PORT            bind port (default 8787)
#   CLASS           core | extended | full (default core)
#   SQ_SOURCE       what to install (default: this checkout with the uhp
#                   extra). Use 'superqode[uhp]' once that extra is published.
#   SQ_SPEC         HarnessSpec to bind (default: deploy/uhp/core.yaml, with a
#                   bounded max_iterations so a runaway loop cannot spend the
#                   whole key)
set -euo pipefail

: "${GEMINI_API_KEY:?export GEMINI_API_KEY first}"

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="${WORK:-$(mktemp -d)}"
PORT="${PORT:-8787}"
CLASS="${CLASS:-core}"
SQ_SOURCE="${SQ_SOURCE:-${REPO}[uhp]}"
BEARER="local-conformance-$$"

mkdir -p "$WORK"
WORK="$(cd "$WORK" && pwd)"
case "$WORK/" in
  "$REPO"/*)
    echo "refusing to run inside the repository: $WORK" >&2
    echo "set WORK to a directory outside $REPO" >&2
    exit 2
    ;;
esac

cd "$WORK"
echo "==> workspace $WORK"

echo "==> 1/5 SuperQode with the uhp extra"
echo "    source: $SQ_SOURCE"
python3 -m venv sq
./sq/bin/pip install -q --upgrade pip
./sq/bin/pip install -q "$SQ_SOURCE"
./sq/bin/superqode --version
./sq/bin/python -c "import fastapi, uvicorn" || {
  echo "the uhp extra did not install; is it published in $SQ_SOURCE?" >&2
  exit 1
}

echo "==> 2/5 conformance suite, in its own venv"
[ -d harnessrouter ] || git clone -q --depth 1 https://github.com/HarnessRouter/harnessrouter
python3 -m venv conf
./conf/bin/pip install -q --upgrade pip
./conf/bin/pip install -q -e harnessrouter/protocol/conformance

if [ -z "${SQ_SPEC:-}" ]; then
  SQ_SPEC="$WORK/core.yaml"
  # The deployed spec, with max_iterations bounded for a test run.
  sed 's/^    max_iterations: 0$/    max_iterations: 12/' \
    "$REPO/deploy/uhp/core.yaml" > "$SQ_SPEC"
fi
echo "    spec: $SQ_SPEC"

echo "==> 3/5 start the bind on 127.0.0.1:$PORT"
# Loopback with a server-side key: the suite is a stock UHP client and does
# not send SuperQode's X-Provider-Api-Key, so a BYOK bind would refuse every
# task. This is why the public host cannot be measured directly.
mkdir -p run
SUPERQODE_UHP_API_KEY="$BEARER" GEMINI_API_KEY="$GEMINI_API_KEY" \
  ./sq/bin/superqode serve uhp \
    --spec "$SQ_SPEC" --host 127.0.0.1 --port "$PORT" \
    --provider google --model gemini-flash-latest \
    --working-dir "$WORK/run" > "$WORK/server.log" 2>&1 &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null || true' EXIT

for _ in $(seq 1 30); do
  curl -sf -m 2 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break
  sleep 1
done
curl -sf -m 2 "http://127.0.0.1:$PORT/health" >/dev/null || {
  echo "server did not start:" >&2
  tail -20 "$WORK/server.log" >&2
  exit 1
}
echo "    up"

echo "==> 4/5 smoke test one real turn"
curl -sf -X POST "http://127.0.0.1:$PORT/v1/responses" \
  -H "Authorization: Bearer $BEARER" -H 'Content-Type: application/json' \
  -d '{"input":"Reply with exactly: ok"}' |
  python3 -c 'import json,sys; d=json.load(sys.stdin); print("    status:", d["status"], "| model:", d["model"])'

echo "==> 5/5 conformance, class $CLASS"
./conf/bin/uhp-conformance \
  --base-url "http://127.0.0.1:$PORT" --api-key "$BEARER" \
  --class "$CLASS" --task-timeout 120 --plain \
  --json "$WORK/superqode-$CLASS.json"

echo
echo "report: $WORK/superqode-$CLASS.json"
