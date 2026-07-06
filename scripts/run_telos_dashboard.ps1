$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $Root "telos\dashboard"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$Log = Join-Path $LogDir "server.log"

Set-Location $Root
python telos_dashboard.py --host 0.0.0.0 --port 8765 *> $Log
