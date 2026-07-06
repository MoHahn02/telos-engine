$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $Root "telos\radar\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$Stamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$Log = Join-Path $LogDir "$Stamp-scan.log"
$DeepTaskName = "Telos Daily Radar Deep Report"

Set-Location $Root
python telos_radar.py run --stage scan *> $Log
$ScanExit = $LASTEXITCODE

if ($ScanExit -ne 0) {
    Add-Content -Path $Log -Value "Scan failed with exit code $ScanExit. Deep report was not started."
    exit $ScanExit
}

try {
    $DeepTask = Get-ScheduledTask -TaskName $DeepTaskName -ErrorAction Stop
    if ($DeepTask.State -eq "Running") {
        Add-Content -Path $Log -Value "Deep task is already running; not starting another instance."
    } else {
        Start-ScheduledTask -TaskName $DeepTaskName
        Add-Content -Path $Log -Value "Started deep report task '$DeepTaskName' after scan completion."
    }
} catch {
    Add-Content -Path $Log -Value "Could not start deep report task '$DeepTaskName': $($_.Exception.Message)"
    exit 1
}
