#!/usr/bin/env bash
# run_local.sh  –  CEOClaw local launcher and API smoke-check
#
# Usage:
#   ./scripts/run_local.sh demo             # 8-cycle demo run
#   ./scripts/run_local.sh demo --cycles 5  # custom cycle count
#   ./scripts/run_local.sh smoke            # start server, seed data, hit endpoints, stop
#   ./scripts/run_local.sh smoke --port 8765
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

PYTHON="${PYTHON:-python3}"
PORT=8000

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_green()  { printf '\033[32m%s\033[0m\n' "$*"; }
_red()    { printf '\033[31m%s\033[0m\n' "$*"; }
_bold()   { printf '\033[1m%s\033[0m\n'  "$*"; }
_header() { echo; _bold "── $* ──"; }

_check_endpoint() {
    local label="$1"
    local url="$2"
    local expect_status="${3:-200}"

    http_code=$(curl -s -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || echo "000")
    if [ "$http_code" = "$expect_status" ]; then
        _green "  PASS  [$http_code]  $label"
        return 0
    else
        _red  "  FAIL  [$http_code]  $label  (expected $expect_status)"
        return 1
    fi
}

_wait_for_server() {
    local url="$1"
    local retries=15
    local i=0
    while [ $i -lt $retries ]; do
        if curl -s -o /dev/null "$url" 2>/dev/null; then
            return 0
        fi
        sleep 0.4
        i=$((i+1))
    done
    _red "Server did not start in time at $url"
    return 1
}

# ---------------------------------------------------------------------------
# Subcommand: demo
# ---------------------------------------------------------------------------

_cmd_demo() {
    local cycles=8
    local extra_args=()

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --cycles) cycles="$2"; shift 2 ;;
            *)        extra_args+=("$1"); shift ;;
        esac
    done

    "$PYTHON" main.py demo --cycles "$cycles" "${extra_args[@]+"${extra_args[@]}"}"
}

# ---------------------------------------------------------------------------
# Subcommand: smoke
# ---------------------------------------------------------------------------

_bootstrap_check() {
    if ! "$PYTHON" -c "import langgraph, langchain_core, fastapi, uvicorn" 2>/dev/null; then
        _red "  Missing dependencies. Run: bash scripts/bootstrap.sh"
        return 1
    fi
    _green "  Dependencies OK"
    return 0
}

_cmd_smoke() {
    # Parse optional --port
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --port) PORT="$2"; shift 2 ;;
            *) shift ;;
        esac
    done

    BASE="http://localhost:${PORT}"
    SERVER_PID=""
    PASS=0
    FAIL=0

    cleanup() {
        [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null && wait "$SERVER_PID" 2>/dev/null || true
    }
    trap cleanup EXIT

    # 0. Bootstrap check
    _header "Bootstrap check"
    if ! _bootstrap_check; then
        exit 1
    fi

    # 1. Run 3 cycles to seed the database
    _header "Seeding database (3-cycle run)"
    "$PYTHON" main.py run --cycles 3 --goal-mrr 100 2>/dev/null

    # 2. Start API server in background (kill any stale process on that port first)
    _header "Starting API server on port $PORT"
    lsof -ti :"$PORT" 2>/dev/null | xargs kill -9 2>/dev/null || true
    sleep 0.3
    uvicorn api.server:app --port "$PORT" --log-level error &
    SERVER_PID=$!

    _wait_for_server "$BASE/health"
    echo "  Server PID $SERVER_PID — ready"

    # 3. Hit every endpoint
    _header "Endpoint smoke check"

    endpoints=(
        "/health               $BASE/health              200"
        "/status               $BASE/status              200"
        "/metrics/latest       $BASE/metrics/latest      200"
        "/runs/recent          $BASE/runs/recent         200"
        "/kpi/trend            $BASE/kpi/trend           200"
        "/artifacts/recent     $BASE/artifacts/recent    200"
        "/summary/latest       $BASE/summary/latest      200"
    )

    for entry in "${endpoints[@]}"; do
        read -r label url expected <<< "$entry"
        if _check_endpoint "$label" "$url" "$expected"; then
            PASS=$((PASS+1))
        else
            FAIL=$((FAIL+1))
        fi
    done

    # Test a 404 case (unknown run_id)
    if _check_endpoint "/runs/{bad-id}  →404" "$BASE/runs/00000000-0000-0000-0000-000000000000" "404"; then
        PASS=$((PASS+1))
    else
        FAIL=$((FAIL+1))
    fi

    # 4. Summary
    echo
    _bold "── Smoke check complete ──"
    TOTAL=$((PASS+FAIL))
    if [ "$FAIL" -eq 0 ]; then
        _green "  $PASS / $TOTAL endpoints PASSED"
    else
        _red   "  $PASS passed, $FAIL FAILED (total $TOTAL)"
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

CMD="${1:-demo}"
shift || true

case "$CMD" in
    demo)  _cmd_demo  "$@" ;;
    smoke) _cmd_smoke "$@" ;;
    *)
        echo "Usage: $0 [demo|smoke] [options]"
        echo "  demo  [--cycles N]   Run 8-cycle demo (default: 8 cycles)"
        echo "  smoke [--port N]     API smoke-check against a fresh server"
        exit 1
        ;;
esac
