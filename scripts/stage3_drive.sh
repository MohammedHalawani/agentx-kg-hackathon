#!/usr/bin/env bash
# Stage 3 run, start to end, as one unattended process (amendment 4):
#   run --max-cases 40  ->  checkpoint (no truth, exit 0 on pass)  ->  run --resume to the end with the extras.
# It stops with the checkpoint's output in the log when the checkpoint fails. No truth variable may be set.
# Usage (from anywhere):  bash scripts/stage3_drive.sh <run dir name>      e.g. run1
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NAME="${1:?run name}"
RUN="$ROOT/artifacts/stage3/$NAME"
PRE="$ROOT/docs/evals/2026-10-11_stage3/preregistration"
PIDFILE="$ROOT/artifacts/stage3/$NAME.pid"
cd "$ROOT/chat" || exit 1
for v in $(env | cut -d= -f1); do case "$v" in *TRUTH*|SUHAIL_SIM_STATE_ROOT) echo "refusing: $v is set"; exit 2;; esac; done
# The extras file is local (it derives from truth) and is opened only after the last main case: check it now.
[ -f "$PRE/extras.json" ] && [ -f "$PRE/extras.json.sha256" ] || { echo "refusing: $PRE/extras.json or its sha256 is missing"; exit 2; }
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then echo "refusing: a driver is already running for $NAME"; exit 2; fi
mkdir -p "$ROOT/artifacts/stage3"; echo $$ > "$PIDFILE"
status() { uv run --frozen python -c "import json,sys;print(json.load(open(sys.argv[1],encoding='utf-8')).get(sys.argv[2]))" "$1" "$2" 2>/dev/null; }
if [ "$(status "$RUN/run_manifest.json" status)" = "completed" ]; then echo "refusing: $NAME is already completed"; exit 0; fi
export LLM_MODEL=openai/gpt-oss:120b
echo "[drive] $(date -u +%FT%TZ) start head=$(git rev-parse HEAD) run=$RUN pid=$$"
( while true; do uv run --frozen python ../scripts/stage3_progress.py "$RUN" >/dev/null 2>&1; sleep 120; done ) &
PROGRESS=$!
trap 'kill $PROGRESS 2>/dev/null; rm -f "$PIDFILE"' EXIT

if [ "$(status "$RUN/checkpoint.json" pass)" != "True" ]; then
  echo "[drive] $(date -u +%FT%TZ) first 40 cases"
  SUHAIL_STAGE3_RESET_SESSION=1 uv run --frozen python -m stage3_eval run --selection "$PRE/selection.json" --out "$RUN" \
      --wiring scripts.stage3_wiring:build --max-cases 40 $([ -d "$RUN" ] && echo --resume) || { echo "[drive] run stopped (exit $?)"; exit 1; }
  echo "[drive] $(date -u +%FT%TZ) checkpoint"
  uv run --frozen python -m stage3_eval checkpoint --selection "$PRE/selection.json" --run "$RUN" --wiring scripts.stage3_wiring:build_checkpoint
  code=$?
  cat "$RUN/checkpoint.json" 2>/dev/null
  if [ $code -ne 0 ]; then echo "[drive] $(date -u +%FT%TZ) CHECKPOINT FAILED (exit $code); the run stays paused"; exit 3; fi
  echo "[drive] $(date -u +%FT%TZ) checkpoint passed; resuming to the end"
fi
uv run --frozen python -m stage3_eval run --selection "$PRE/selection.json" --out "$RUN" --wiring scripts.stage3_wiring:build \
    --extras "$PRE/extras.json" --resume
echo "[drive] $(date -u +%FT%TZ) run ended (exit $?)"
uv run --frozen python ../scripts/stage3_progress.py "$RUN"
