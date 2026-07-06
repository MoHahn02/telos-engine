param(
    [string]$ScanTaskName = "Telos Daily Radar Scan",
    [string]$DeepTaskName = "Telos Daily Radar Deep Report",
    [string]$LegacyTaskName = "Telos Daily Radar",
    [string]$ScanAt = "06:00",
    [string]$DeepAt = "10:00",
    [int]$ScanHours = 4,
    [int]$DeepHours = 6
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$PowerShell = (Get-Command powershell).Source
$ScanScript = Join-Path $Root "scripts\run_telos_radar_scan.ps1"
$DeepScript = Join-Path $Root "scripts\run_telos_radar_deep.ps1"
$LogDir = Join-Path $Root "telos\radar\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$ScanAction = New-ScheduledTaskAction `
    -Execute $PowerShell `
    -Argument "-ExecutionPolicy Bypass -File `"$ScanScript`"" `
    -WorkingDirectory $Root

$DeepAction = New-ScheduledTaskAction `
    -Execute $PowerShell `
    -Argument "-ExecutionPolicy Bypass -File `"$DeepScript`"" `
    -WorkingDirectory $Root

$ScanTrigger = New-ScheduledTaskTrigger -Daily -At $ScanAt
$DeepTrigger = New-ScheduledTaskTrigger -Daily -At $DeepAt

$ScanSettings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours $ScanHours)

$DeepSettings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours $DeepHours)

Register-ScheduledTask `
    -TaskName $ScanTaskName `
    -Action $ScanAction `
    -Trigger $ScanTrigger `
    -Settings $ScanSettings `
    -Description "Fetches sources, writes the digest, prepares LLM prefilter/triage caches, then starts the deep Telos Radar task." `
    -Force | Out-Null

Register-ScheduledTask `
    -TaskName $DeepTaskName `
    -Action $DeepAction `
    -Trigger $DeepTrigger `
    -Settings $DeepSettings `
    -Description "Fallback task that builds Telos Radar article dossiers, topic indexes, daily report, and synthesis from cached candidates if not already built after scan." `
    -Force | Out-Null

$legacy = Get-ScheduledTask -TaskName $LegacyTaskName -ErrorAction SilentlyContinue
if ($legacy) {
    Disable-ScheduledTask -TaskName $LegacyTaskName | Out-Null
}

Write-Host "Registered '$ScanTaskName' daily at $ScanAt with ${ScanHours}h limit"
Write-Host "Registered '$DeepTaskName' fallback daily at $DeepAt with ${DeepHours}h limit"
if ($legacy) {
    Write-Host "Disabled legacy task '$LegacyTaskName'"
}
