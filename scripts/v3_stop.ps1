param([ValidateSet(8023, 8024)][int[]]$Port = @(8023, 8024),
      [switch]$Check)
# Stop the V3 demo backends this checkout started, and nothing else.
#
#   8023  the V3 backend (scripts\v3_backend.ps1)
#   8024  the mock-provider backend (scripts\v3_mock_backend.py)
#
# A process is stopped only when it listens on one of these two ports AND it was started from this checkout's own
# Python environment (chat\.venv) with that port on its command line. Anything else on the port is reported and left
# alone. No other port can be named here: the recording backend on 8022 is out of reach of this script.
#
#   scripts\v3_stop.ps1            stop both, then report what is still listening
#   scripts\v3_stop.ps1 -Port 8024 stop the mock-provider backend only
#   scripts\v3_stop.ps1 -Check     stop nothing; report what is listening on 8023 and 8024
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$environment = (Join-Path $root 'chat\.venv') + '\'

function Listener([int]$number) {
    $connection = Get-NetTCPConnection -State Listen -LocalPort $number -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $connection) { return $null }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($connection.OwningProcess)"
    $parent = if ($process) { Get-CimInstance Win32_Process -Filter "ProcessId=$($process.ParentProcessId)" }
    $lines = "$($process.CommandLine) $($parent.CommandLine)"
    [pscustomobject]@{ Port = $number; Id = $connection.OwningProcess
                       Ours = $lines.Contains($environment) -and ($process.CommandLine -match "--port $number\b") }
}

foreach ($number in $Port) {
    $found = Listener $number
    if (-not $found) { "port ${number}: nothing is listening"; continue }
    if (-not $found.Ours) { "port ${number}: process $($found.Id) was not started from this checkout; left running"; continue }
    if ($Check) { "port ${number}: V3 demo backend is running (process $($found.Id))"; continue }
    Stop-Process -Id $found.Id -Force
    for ($i = 0; $i -lt 20 -and (Listener $number); $i++) { Start-Sleep -Milliseconds 500 }
    if (Listener $number) { "port ${number}: process $($found.Id) did not stop" } else { "port ${number}: stopped process $($found.Id)" }
}
$left = @(8023, 8024 | Where-Object { Listener $_ })
if ($left) { "still listening: $($left -join ', ')" } else { 'nothing is listening on 8023 or 8024' }
