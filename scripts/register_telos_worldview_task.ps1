param(
    [string]$TaskName = "Telos Daily Worldview",
    [string]$FallbackAt = "11:00",
    [int]$ExecutionHours = 10
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$PowerShell = (Get-Command powershell).Source
$RunScript = Join-Path $Root "scripts\run_telos_worldview.ps1"
$LogDir = Join-Path $Root "telos\worldview\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$Action = New-ScheduledTaskAction `
    -Execute $PowerShell `
    -Argument "-ExecutionPolicy Bypass -File `"$RunScript`"" `
    -WorkingDirectory $Root

$Trigger = New-ScheduledTaskTrigger -Daily -At $FallbackAt
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours $ExecutionHours)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Builds geopolitics and finance packs, Telos 100, worldview, personal briefing, and the bounded three-role Dreaming and forecast loop after the AI radar." `
    -Force | Out-Null

Write-Host "Registered '$TaskName' fallback daily at $FallbackAt with ${ExecutionHours}h limit"
