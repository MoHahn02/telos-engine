param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $Root "telos\worldview\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$Stamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$Date = Get-Date -Format "yyyy-MM-dd"
$Log = Join-Path $LogDir "$Stamp-worldview.log"
$GeoIndex = Join-Path $Root "telos\geopolitics\$Date\index.md"
$FinanceIndex = Join-Path $Root "telos\finance\$Date\index.md"
$MarketReport = Join-Path $Root "telos\markets\$Date-market-watch.md"
$WorldviewReport = Join-Path $Root "telos\worldview\$Date-worldview.md"
$PersonalReport = Join-Path $Root "telos\personal\$Date-personal-daily-report.md"
$DreamReport = Join-Path $Root "telos\dreams\$Date\dream-report.md"
$AiQuality = Join-Path $Root "telos\radar\$Date\quality-gate.json"
$GeoQuality = Join-Path $Root "telos\geopolitics\$Date\quality-gate.json"
$FinanceQuality = Join-Path $Root "telos\finance\$Date\quality-gate.json"

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

if (-not (Test-QualityGate $AiQuality)) {
    "AI radar quality gate is missing or failed; refusing to build downstream worldview outputs." *> $Log
    exit 1
}

$InputsChanged = $false

if ($Force -or -not (Test-Path $GeoIndex) -or -not (Test-QualityGate $GeoQuality)) {
    "Starting geopolitics pipeline." *> $Log
    python telos_domain_radar.py run --config telos_geopolitics_config.json --stage all *>> $Log
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    if (-not (Test-QualityGate $GeoQuality)) { exit 1 }
    $InputsChanged = $true
} else {
    "Geopolitics research pack already exists." *> $Log
}

if ($Force -or -not (Test-Path $FinanceIndex) -or -not (Test-QualityGate $FinanceQuality)) {
    Add-Content -Path $Log -Value "Starting finance pipeline."
    python telos_domain_radar.py run --config telos_finance_config.json --stage all *>> $Log
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    if (-not (Test-QualityGate $FinanceQuality)) { exit 1 }
    $InputsChanged = $true
} else {
    Add-Content -Path $Log -Value "Finance research pack already exists."
}

if ($Force -or -not (Test-Path $MarketReport)) {
    Add-Content -Path $Log -Value "Starting Telos 100 market update."
    python telos_market.py run *>> $Log
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} else {
    Add-Content -Path $Log -Value "Telos 100 market report already exists."
}

if ($Force -or $InputsChanged -or -not (Test-Path $WorldviewReport)) {
    Add-Content -Path $Log -Value "Starting cross-domain worldview synthesis."
    python telos_worldview.py run *>> $Log
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} else {
    Add-Content -Path $Log -Value "Cross-domain worldview already exists."
}

if ($Force -or $InputsChanged -or -not (Test-Path $PersonalReport)) {
    Add-Content -Path $Log -Value "Starting personal daily briefing from the three domain reports."
    python telos_personal_report.py run *>> $Log
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} else {
    Add-Content -Path $Log -Value "Personal daily briefing already exists."
}

if ($Force -or -not (Test-Path $DreamReport)) {
    Add-Content -Path $Log -Value "Starting bounded 30-minute Telos dreaming and forecast loop."
    $DreamArgs = @("telos_dream.py", "run", "--budget-minutes", "30")
    python @DreamArgs *>> $Log
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} else {
    Add-Content -Path $Log -Value "Dream report already exists."
}

Add-Content -Path $Log -Value "Worldview pipeline completed: $WorldviewReport"
Add-Content -Path $Log -Value "Personal daily briefing completed: $PersonalReport"
Add-Content -Path $Log -Value "Dreaming loop completed: $DreamReport"
