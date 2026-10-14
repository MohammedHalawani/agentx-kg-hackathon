# Run only offline mocks and ephemeral loopback HTTP probes. No service is started.
# The already locked V3.1 environment is read with bytecode writes disabled; the
# V3.2 source/test paths take precedence. Override Python to use an equivalent own venv.
param([string]$Python='C:\Projects\suhail-v3-1-corrective\chat\.venv\Scripts\python.exe')
$ErrorActionPreference='Stop'
$reviewRoot=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path -LiteralPath $Python)) { throw 'Supply the locked chat Python environment with -Python' }
$offlineSettings=@{
    PYTHONDONTWRITEBYTECODE='1'; PYTHONIOENCODING='utf-8'
    PYTHONPATH=((Join-Path $reviewRoot 'chat')+';'+(Join-Path $reviewRoot 'chat/tests'))
    NEO4J_URI='bolt://127.0.0.1:1'; NEO4J_USERNAME='offline'; NEO4J_PASSWORD='offline'
    LLM_API_KEY='offline-placeholder'; LLM_API_BASE='http://127.0.0.1:1/v1'
    LITELLM_LOCAL_MODEL_COST_MAP='True'; LITELLM_TELEMETRY='False'
    SUHAIL_NEO4J_TESTS='0'; SUHAIL_V3_RACE_TESTS='0'
    SUHAIL_MAX_OUTPUT_TOKENS='2048'; SUHAIL_MAX_INPUT_BYTES='65536'
    # Test-only arithmetic rates and generous caps; these are NOT provider prices.
    SUHAIL_INPUT_USD_PER_MILLION='1'; SUHAIL_OUTPUT_USD_PER_MILLION='1'
    SUHAIL_INFERENCE_MAX_CALLS='10000'; SUHAIL_INFERENCE_MAX_TOKENS='1000000000'
    SUHAIL_INFERENCE_MAX_USD='1000'
    SUHAIL_INFERENCE_LEDGER=(Join-Path ([IO.Path]::GetTempPath()) ('suhail-v32-offline-'+[guid]::NewGuid().ToString('N')+'.json'))
}
$previousSettings=@{}
foreach ($name in $offlineSettings.Keys) {
    $previousSettings[$name]=[Environment]::GetEnvironmentVariable($name,'Process')
    [Environment]::SetEnvironmentVariable($name,$offlineSettings[$name],'Process')
}
Push-Location (Join-Path $reviewRoot 'chat')
try {
    & $Python -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Offline Python regression gate failed' }
} finally {
    Pop-Location
    foreach ($name in $previousSettings.Keys) { [Environment]::SetEnvironmentVariable($name,$previousSettings[$name],'Process') }
}
# Preserve the synthetic audit ledger rather than deleting any computed path.
