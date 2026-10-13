param([ValidateSet(1, 2)][int]$Workers = 1,
      [ValidateSet(1, 2)][int]$ProviderMaxInflight = 1,
      [switch]$RulesOnly,
      [switch]$Narration,
      [switch]$Canopus,
      [switch]$CheckOnly)
# Start the isolated V3 backend: one Uvicorn process on port 8023, the V3 world database and its own state root.
# The settings below are this process's own; nothing here reads, stops or changes the V2 recording backend (port
# 8022), its database or its checkouts. Unlike scripts\showcase_backend.ps1 this script never stops a process: if
# the port is taken it refuses and exits.
#
#   -Workers 1|2              cases investigated at once. Default 1, which is also the rollback.
#   -ProviderMaxInflight 1|2  provider calls open at once. Default 1. Use 2 only after a higher capacity of the
#                             provider account has been verified and a bounded live test has been approved.
#   -RulesOnly                no model: investigations run on rules only (SUHAIL_V2_AGENTS=off).
#   -Narration, -Canopus      off unless asked for: both make model calls that share the provider limit.
#   -CheckOnly                run every check and print the configuration without starting anything.
#
# No secret is set here: the database password and the model key are read by the backend from the ignored .env at
# the root of this checkout. Starting the backend initializes the ledger and its workers, and with a model key
# present an investigation calls the provider. To roll back: start again with -Workers 1 -ProviderMaxInflight 1
# after the live claims and provider calls have drained, or check out the previous integration commit.
$ErrorActionPreference = 'Stop'
$Port = 8023
$Database = 'shipments-v2-world-v3-20261013'
$StateRoot = 'C:\Projects\suhail-v3-state\world-v3-20261013'
$Model = 'openai/gpt-oss:120b'            # the only place V3 selects its model; .env is not relied on for it
$ApiBase = 'https://ollama.com/v1'
$root = Split-Path -Parent $PSScriptRoot
$frontend = Join-Path $root 'frontend-next\dist'
$logs = Join-Path $root 'artifacts\v3'
$pidFile = Join-Path $logs "backend_$Port.pid"

function Refuse([string]$why) { "refused: $why"; exit 1 }

if ($root -ne 'C:\Projects\suhail-v3-integration') { Refuse "this launcher runs from C:\Projects\suhail-v3-integration only (found $root)" }
if (-not (Test-Path (Join-Path $root '.env'))) { Refuse 'no .env at the root of this checkout (database settings are read from it)' }
if (-not (Test-Path (Join-Path $StateRoot 'DEMO-SUHAIL-WORLD-V3-20261013'))) { Refuse "the V3 state root is missing: $StateRoot" }
if (-not (Test-Path (Join-Path $frontend 'index.html'))) { Refuse "no frontend build at $frontend (run npm.cmd run build in frontend-next)" }
if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) {
    Refuse "port $Port is already in use; this launcher never stops a process"
}

$settings = [ordered]@{
    LLM_MODEL                      = $Model
    LLM_API_BASE                   = $ApiBase
    SUHAIL_OPERATIONS_DATABASE     = $Database
    SUHAIL_SIM_STATE_ROOT          = $StateRoot
    SUHAIL_FRONTEND_NEXT_DIST      = $frontend
    SUHAIL_INVESTIGATION_WORKERS   = "$Workers"
    SUHAIL_PROVIDER_MAX_INFLIGHT   = "$ProviderMaxInflight"
    SUHAIL_CLAIM_LEASE_SECONDS     = '180'
    SUHAIL_CLAIM_HEARTBEAT_SECONDS = '15'
    SUHAIL_MODEL_CALL_CAP          = '12'
    SUHAIL_TOOL_BATCH              = '3'
    SUHAIL_PREFETCH_OVERVIEW       = '1'
    SUHAIL_INVALID_OUTPUT_REPAIR   = '1'
    SUHAIL_FORCED_CONCLUSION       = '1'
    SUHAIL_DEV_RESET               = '0'
    SUHAIL_NARRATION               = $(if ($Narration) { '1' } else { '0' })
    SUHAIL_CANOPUS                 = $(if ($Canopus) { '1' } else { '0' })
    SUHAIL_V2_AGENTS               = $(if ($RulesOnly) { 'off' } else { 'gpt-oss' })
    SUHAIL_MEDIA_DIR               = Join-Path $root 'artifacts\v3\media'
}
# Settings of another session that must not leak into this process.
$cleared = 'SUHAIL_DEMO_SHIPMENTS', 'SUHAIL_LIVE_BUNDLE', 'SUHAIL_EVAL_TRUTH_ROOT', 'SUHAIL_DISABLED_TOOLS',
           'SUHAIL_V3_RACE_TESTS', 'SUHAIL_V3_CI_DATABASE'

"V3 backend configuration (port $Port, one process):"
$settings.GetEnumerator() | ForEach-Object { "  {0} = {1}" -f $_.Key, $_.Value }
if ($CheckOnly) { 'checks passed; nothing was started (-CheckOnly)'; exit 0 }

foreach ($entry in $settings.GetEnumerator()) { Set-Item "Env:$($entry.Key)" $entry.Value }
foreach ($name in $cleared) { Remove-Item "Env:$name" -ErrorAction SilentlyContinue }
New-Item -ItemType Directory -Force $logs | Out-Null
$process = Start-Process -FilePath uv -ArgumentList 'run', 'uvicorn', '--app-dir', '../backend', 'main:app', '--host', '127.0.0.1', '--port', "$Port" `
    -WorkingDirectory (Join-Path $root 'chat') -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $logs "backend_$Port.out.log") -RedirectStandardError (Join-Path $logs "backend_$Port.err.log")
Set-Content -Path $pidFile -Value $process.Id
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 3
    try {
        $status = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/worker/status" -TimeoutSec 5
        if ($status.database -ne $Database) { "the backend on port $Port answers for '$($status.database)', not '$Database'; stop process $($process.Id) yourself"; exit 1 }
        "V3 backend is up on port $Port (process $($process.Id), database $Database, workers $($status.worker.concurrency), provider limit $ProviderMaxInflight)"
        "open http://127.0.0.1:$Port/app/ ; the process id is in $pidFile"
        exit 0
    } catch {}
}
"the backend did not answer on port $Port within 3 minutes; see $logs\backend_$Port.err.log (process $($process.Id))"
exit 1
