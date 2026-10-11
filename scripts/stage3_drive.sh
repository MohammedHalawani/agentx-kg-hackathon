#!/usr/bin/env bash
# Stage 3 run, start to end, as one unattended process (amendment 4):
#   run --max-cases 40  ->  checkpoint (no truth, exit 0 on pass)  ->  run --resume to the end with the extras.
# It stops with the checkpoint's output in the log when the checkpoint fails. No truth variable may be set.
# Usage (from anywhere):  bash scripts/stage3_drive.sh <run dir name>      e.g. run1
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN="$ROOT/artifacts/stage3/${1:?run name}"
PRE="$ROOT/docs/evals/2026-10-11_stage3/preregistration"
cd "$ROOT/chat" || exit 1
for v in $(env | cut -d= -f1); do case "$v" in *TRUTH*|SUHAIL_SIM_STATE_ROOT) echo "refusing: $v is set"; exit 2;; esac; done
export LLM_MODEL=openai/gpt-oss:120b
echo "[drive] $(date -u +%FT%TZ) start head=$(git rev-parse HEAD) run=$RUN"
( while true; do uv run python ../scripts/stage3_progress.py "$RUN" >/dev/null 2>&1; sleep 120; done ) &
PROGRESS=$!
trap 'kill $PROGRESS 2>/dev/null' EXIT

if [ ! -f "$RUN/checkpoint.json" ]; then
  echo "[drive] $(date -u +%FT%TZ) first 40 cases"
  SUHAIL_STAGE3_RESET_SESSION=1 uv run python -m stage3_eval run --selection "$PRE/selection.json" --out "$RUN" \
      --wiring scripts.stage3_wiring:build --max-cases 40 $([ -d "$RUN" ] && echo --resume) || { echo "[drive] run stopped (exit $?)"; exit 1; }
  echo "[drive] $(date -u +%FT%TZ) checkpoint"
  uv run python -m stage3_eval checkpoint --selection "$PRE/selection.json" --run "$RUN" --wiring scripts.stage3_wiring:build_checkpoint
  code=$?
  cat "$RUN/checkpoint.json" 2>/dev/null
  if [ $code -ne 0 ]; then echo "[drive] $(date -u +%FT%TZ) CHECKPOINT FAILED (exit $code); the run stays paused"; exit 3; fi
  echo "[drive] $(date -u +%FT%TZ) checkpoint passed; resuming to the end"
fi
uv run python -m stage3_eval run --selection "$PRE/selection.json" --out "$RUN" --wiring scripts.stage3_wiring:build \
    --extras "$PRE/extras.json" --resume
echo "[drive] $(date -u +%FT%TZ) run ended (exit $?)"
uv run python ../scripts/stage3_progress.py "$RUN"
