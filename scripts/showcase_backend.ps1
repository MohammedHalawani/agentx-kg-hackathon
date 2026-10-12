param([Parameter(Mandatory = $true)][ValidateSet('A', 'B')][string]$Video,
      [int]$Port = 8022,
      [string]$Database = 'shipments-v2-world-ux-test',
      [string]$StateRoot = 'C:\Projects\suhail-sim-state\world-1-small-r4',
      [string]$Frontend = 'C:\Projects\demo\.ui-integration\frontend-next\dist-8022')
# (Re)start the isolated recording backend for one showcase video: the same database and world every time, with the
# list of shipments whose cases the monitor may open for that video. No secret is set here: the model key is read
# from chat\.env by the backend as usual. Run from anywhere; then seed a take with scripts\showcase_seed.py.
$shipments = @{
    A = 'SYN-SHP-000304,SYN-SHP-000269,SYN-SHP-000121,SYN-SHP-000599'
    B = 'SYN-SHP-000443,SYN-SHP-000050,SYN-SHP-000042,SYN-SHP-000460'
}[$Video]
$root = Split-Path -Parent $PSScriptRoot
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'uvicorn' -and $_.CommandLine -match "--port $Port" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2
$env:LLM_MODEL = 'openai/gpt-oss:120b'
$env:SUHAIL_OPERATIONS_DATABASE = $Database
$env:SUHAIL_SIM_STATE_ROOT = $StateRoot
$env:SUHAIL_FRONTEND_NEXT_DIST = $Frontend
$env:SUHAIL_MODEL_CALL_CAP = '12'; $env:SUHAIL_TOOL_BATCH = '3'; $env:SUHAIL_PREFETCH_OVERVIEW = '1'
$env:SUHAIL_INVALID_OUTPUT_REPAIR = '1'; $env:SUHAIL_FORCED_CONCLUSION = '1'; $env:SUHAIL_DEV_RESET = '1'
$env:SUHAIL_NARRATION = '1'; $env:SUHAIL_CANOPUS = '1'
$env:SUHAIL_DEMO_SHIPMENTS = $shipments
$env:SUHAIL_MEDIA_DIR = Join-Path $root 'artifacts\showcase\media'
$logs = Join-Path $root 'artifacts\demo'
New-Item -ItemType Directory -Force $logs | Out-Null
Start-Process -FilePath uv -ArgumentList 'run', 'uvicorn', '--app-dir', '../backend', 'main:app', '--host', '127.0.0.1', '--port', "$Port" `
    -WorkingDirectory (Join-Path $root 'chat') -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logs "backend_$Port.out.log") -RedirectStandardError (Join-Path $logs "backend_$Port.err.log") | Out-Null
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 3
    try { Invoke-RestMethod -Uri "http://127.0.0.1:$Port/simulation/status" -TimeoutSec 5 | Out-Null; "backend for video $Video is up on port $Port (shipments: $shipments)"; exit 0 } catch {}
}
"the backend did not answer on port $Port within 3 minutes; see $logs\backend_$Port.err.log"
exit 1
