param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $Root "telos\radar\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$Stamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$Log = Join-Path $LogDir "$Stamp-deep.log"
$Date = Get-Date -Format "yyyy-MM-dd"
$ReportPath = Join-Path $Root "telos\radar\$Date-daily-report.md"
$PackIndexPath = Join-Path $Root "telos\radar\$Date\index.md"
$QualityPath = Join-Path $Root "telos\radar\$Date\quality-gate.json"
$WorldviewTaskName = "Telos Daily Worldview"

Set-Location $Root

function Test-QualityGate([string]$Path) {
    if (-not (Test-Path $Path)) { return $false }
    try {
        $Gate = Get-Content -Raw -Path $Path | ConvertFrom-Json
        return $Gate.passed -eq $true
    } catch {
        return $false
    }
}

$DeepComplete = (Test-Path $ReportPath) -and (Test-Path $PackIndexPath) -and (Test-QualityGate $QualityPath)
if (-not $Force -and $DeepComplete) {
    "Deep report already exists for $Date. Use -Force to rebuild." *> $Log
    exit 0
}

python telos_radar.py run --stage deep *> $Log
$DeepExit = $LASTEXITCODE

if ($DeepExit -ne 0) {
    Add-Content -Path $Log -Value "Deep report failed with exit code $DeepExit."
    exit $DeepExit
}

if (-not (Test-QualityGate $QualityPath)) {
    Add-Content -Path $Log -Value "Deep report process exited successfully but its quality gate did not pass."
    exit 1
}

Add-Content -Path $Log -Value "Deep report completed."

try {
    $WorldviewTask = Get-ScheduledTask -TaskName $WorldviewTaskName -ErrorAction Stop
    if ($WorldviewTask.State -eq "Running") {
        Add-Content -Path $Log -Value "Worldview task is already running; not starting another instance."
    } else {
        Start-ScheduledTask -TaskName $WorldviewTaskName
        Add-Content -Path $Log -Value "Started worldview task '$WorldviewTaskName' after deep report completion."
    }
} catch {
    Add-Content -Path $Log -Value "Could not start worldview task '$WorldviewTaskName': $($_.Exception.Message)"
}
