param(
    [switch]$ForceDream,
    [switch]$DryRun,
    [string]$StatusPath = ""
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $Root "telos\manual-runs\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$Stamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$Date = Get-Date -Format "yyyy-MM-dd"
$Log = Join-Path $LogDir "$Stamp-manual.log"

Set-Location $Root

function Write-RunStatus([string]$State, [string]$Note = "") {
    if (-not $StatusPath) { return }
    $status = [ordered]@{
        state = $State
        updated_at = (Get-Date).ToUniversalTime().ToString("o")
        log_path = (Resolve-Path $Log -ErrorAction SilentlyContinue).Path
        note = $Note
    }
    if ($State -eq "running") {
        $status.pid = $PID
        $status.started_at = (Get-Date).ToUniversalTime().ToString("o")
    } else {
        $status.finished_at = (Get-Date).ToUniversalTime().ToString("o")
    }
    $status | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 -Path $StatusPath
}

function Write-Step([string]$Message) {
    $line = "$(Get-Date -Format o) $Message"
    Add-Content -Path $Log -Value $line
    Write-Output $line
}

function Run-Step([string]$Name, [string[]]$ArgsList) {
    if ($DryRun) {
        Write-Step "Would run $Name`: python $($ArgsList -join ' ')"
        return
    }
    Write-Step "Starting $Name."
    python @ArgsList *>> $Log
    $exit = $LASTEXITCODE
    if ($exit -ne 0) {
        Write-Step "$Name failed with exit code $exit."
        Write-RunStatus "failed" "$Name failed with exit code $exit."
        exit $exit
    }
    Write-Step "Finished $Name."
}

Write-RunStatus "running" "Manual Telos run started."
Write-Step "Manual Telos run started for $Date."

Run-Step "AI radar scan" @("telos_radar.py", "run", "--stage", "scan")
Run-Step "AI radar deep report" @("telos_radar.py", "run", "--stage", "deep")
Run-Step "Geopolitics radar" @("telos_domain_radar.py", "run", "--config", "telos_geopolitics_config.json", "--stage", "all")
Run-Step "Finance radar" @("telos_domain_radar.py", "run", "--config", "telos_finance_config.json", "--stage", "all")
Run-Step "Telos 100 market update" @("telos_market.py", "run")
Run-Step "Cross-domain worldview" @("telos_worldview.py", "run")
Run-Step "Personal daily briefing" @("telos_personal_report.py", "run")

$DreamArgs = @("telos_dream.py", "run", "--budget-minutes", "30")
if ($ForceDream) {
    $DreamArgs += "--force"
}
Run-Step "Dreaming and forecast loop" $DreamArgs

Write-Step "Manual Telos run completed for $Date."
Write-RunStatus "completed" "Manual Telos run completed."
