# V3.2 real-Neo4j release gate: the 4 race tests and the V3.2 action-protocol tests, on ONE disposable database only.
#
# Target: shipments-v2-world-v32-race-20261015 (created empty by the operator on 2026-10-15). Nothing else is ever used:
# this script refuses before running anything if the settings name another database, and the tests themselves refuse
# (fail, never skip or fall back) unless the server reports that exact database online and either empty or holding only
# the race fixture. The CI database, the frozen V3 world and every V2 database are refused by name.
#
# Credentials: read from the integration worktree's ignored .env, three keys only (NEO4J_URI, NEO4J_USERNAME,
# NEO4J_PASSWORD), plus the names of the application's own databases so the tests can refuse them. If a key is
# missing you are prompted (the password masked). Nothing is printed, written to disk or kept after the run.
# No model key is read; model settings are blanked. No paid inference, no external request.
param([string]$Python = 'C:\Projects\suhail-v3-1-corrective\chat\.venv\Scripts\python.exe',
      [string]$EnvFile = 'C:\Projects\suhail-v3-integration\.env')
$ErrorActionPreference = 'Stop'
$Target = 'shipments-v2-world-v32-race-20261015'
$Refused = @('shipments-v2-world-v3-ci-20261013', 'shipments-v2-world-v3-20261013', 'neo4j', 'system', 'shipments')
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path -LiteralPath $Python)) { throw "Python environment not found: $Python" }

$wanted = 'NEO4J_URI','NEO4J_USERNAME','NEO4J_PASSWORD','NEO4J_DATABASE','SHIPMENT_DATABASE','CHAT_DATABASE'
$cfg = @{}
if (Test-Path -LiteralPath $EnvFile) {
    foreach ($line in Get-Content -LiteralPath $EnvFile) {
        if ($line -match '^\s*([A-Z_]+)\s*=(.*)$' -and $wanted -contains $Matches[1]) { $cfg[$Matches[1]] = $Matches[2].Trim().Trim('"', "'") }
    }
}
if (-not $cfg.NEO4J_URI) { $cfg.NEO4J_URI = 'neo4j://127.0.0.1:7687' }
if (-not $cfg.NEO4J_USERNAME) { $cfg.NEO4J_USERNAME = Read-Host 'Neo4j user' }
if (-not $cfg.NEO4J_PASSWORD) {
    $secure = Read-Host 'Neo4j password' -AsSecureString
    $cfg.NEO4J_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
}

# Fail closed before anything connects.
if ($cfg.NEO4J_URI -notmatch '^(neo4j|bolt)://(127\.0\.0\.1|localhost)(:\d+)?/?$') { throw 'Refused: the Neo4j URI is not the local server' }
foreach ($name in 'NEO4J_DATABASE','SHIPMENT_DATABASE','CHAT_DATABASE') {
    if ($cfg[$name] -and $cfg[$name] -ieq $Target) { throw "Refused: $name names the test target; it must stay an application database" }
}
if ($Refused -contains $Target) { throw 'Refused: the target is a protected database' }

$settings = @{
    NEO4J_URI = $cfg.NEO4J_URI; NEO4J_USERNAME = $cfg.NEO4J_USERNAME; NEO4J_PASSWORD = $cfg.NEO4J_PASSWORD
    NEO4J_DATABASE = $cfg.NEO4J_DATABASE; SHIPMENT_DATABASE = $cfg.SHIPMENT_DATABASE; CHAT_DATABASE = $cfg.CHAT_DATABASE
    SUHAIL_V3_RACE_TESTS = '1'; SUHAIL_V3_CI_DATABASE = $Target; SUHAIL_OPERATIONS_DATABASE = $Target
    SUHAIL_NEO4J_TESTS = '0'                                  # the V2 scratch-database tests stay off
    OLLAMA_API_KEY = ''; OPENAI_API_KEY = ''; LLM_API_KEY = 'offline-placeholder'; LLM_API_BASE = 'http://127.0.0.1:1/v1'
    LITELLM_LOCAL_MODEL_COST_MAP = 'True'; LITELLM_TELEMETRY = 'False'; SUHAIL_PROVIDER_MAX_INFLIGHT = '1'
    SUHAIL_INFERENCE_LEDGER = (Join-Path ([IO.Path]::GetTempPath()) ('suhail-v32-neo4j-' + [guid]::NewGuid().ToString('N') + '.json'))
    PYTHONDONTWRITEBYTECODE = '1'; PYTHONIOENCODING = 'utf-8'
    PYTHONPATH = ((Join-Path $root 'chat') + ';' + (Join-Path $root 'chat\tests'))
}
$previous = @{}
foreach ($name in $settings.Keys) {
    $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
    [Environment]::SetEnvironmentVariable($name, $settings[$name], 'Process')
}
$cfg = $null; $secure = $null
$log = Join-Path $root 'artifacts\v3.2\neo4j-gate.log'
Write-Host "Target: $Target only. Log: $log"
Push-Location (Join-Path $root 'chat')
try {
    & $Python -m unittest -v tests.test_v3_concurrency_neo4j tests.test_v32_actions_neo4j 2>&1 | Tee-Object -FilePath $log
    $code = $LASTEXITCODE
} finally {
    Pop-Location
    foreach ($name in $previous.Keys) { [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process') }
}
Write-Host "Exit code: $code (0 = every test passed)"
