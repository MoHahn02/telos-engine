param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [string]$LanHost = "192.168.2.118"
)

$ErrorActionPreference = "Stop"

$Python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"
if (-not (Test-Path $Python)) {
    throw "python.exe not found: $Python"
}

$Root = (Resolve-Path $Root).Path

function Stop-DashboardPort([int]$Port) {
    $lines = & netstat -ano
    foreach ($line in $lines) {
        if ($line -match "^\s*TCP\s+\S+:$Port\s+0\.0\.0\.0:0\s+\S+\s+(\d+)\s*$") {
            $processId = [int]$matches[1]
            if ($processId -gt 0) {
                Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

function Start-Dashboard([string]$HostName, [int]$Port) {
    $process = Start-Process `
        -FilePath $Python `
        -ArgumentList "telos_dashboard.py", "--host", $HostName, "--port", "$Port" `
        -WorkingDirectory $Root `
        -WindowStyle Hidden `
        -PassThru
    Write-Host "Started Telos dashboard on ${HostName}:$Port (PID $($process.Id))"
}

Stop-DashboardPort 8765
Stop-DashboardPort 8766

# Some Codex-launched shells contain both Path and PATH, which makes
# Start-Process throw. Normalize the process environment before spawning.
[System.Environment]::SetEnvironmentVariable("PATH", $null, "Process")
[System.Environment]::SetEnvironmentVariable(
    "Path",
    "C:\Windows\System32;C:\Windows;C:\Windows\System32\WindowsPowerShell\v1.0\",
    "Process"
)

Start-Dashboard "127.0.0.1" 8765
Start-Dashboard $LanHost 8766
