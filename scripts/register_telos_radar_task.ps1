param(
    [string]$TaskName = "Telos Daily Radar",
    [string]$At = "06:00"
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$PowerShell = (Get-Command powershell).Source
$Script = Join-Path $Root "scripts\run_telos_radar.ps1"
$LogDir = Join-Path $Root "telos\radar\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$Action = New-ScheduledTaskAction `
    -Execute $PowerShell `
    -Argument "-ExecutionPolicy Bypass -File `"$Script`"" `
    -WorkingDirectory $Root

$Trigger = New-ScheduledTaskTrigger -Daily -At $At
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Fetches and scores daily AI/robotics/compute signals for the local Telos Engine." `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName' daily at $At"
