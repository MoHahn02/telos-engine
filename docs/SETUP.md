# Setup

## 1. Clone and Initialize

```powershell
git clone https://github.com/YOUR_USER/telos-engine.git
cd telos-engine
python telos.py init
python telos.py seed
```

This creates a local `telos/` workspace with:

```text
telos/
  inbox/
  memories/
  claims/
  beliefs/
  sources/
  reviews/
  telos.db
```

These files are intentionally ignored by Git.

## 2. Choose a Local Model

The radar pipeline can use Ollama for article triage and dossier generation.

Example:

```powershell
ollama pull qwen3.5:9b
```

Then set the model names in:

```text
telos_radar_config.json
telos_geopolitics_config.json
telos_finance_config.json
```

For smaller GPUs, use smaller models and lower `num_ctx`.

## 3. Run the Radar

```powershell
python telos_radar.py run --stage scan
python telos_radar.py run --stage deep
```

Domain radars:

```powershell
python telos_domain_radar.py run --config telos_geopolitics_config.json --stage all
python telos_domain_radar.py run --config telos_finance_config.json --stage all
```

Market watchlist:

```powershell
python telos_market.py run
```

Worldview:

```powershell
python telos_worldview.py run
```

## 4. Dashboard

```powershell
python telos_dashboard.py --host 127.0.0.1 --port 8765
```

For LAN/phone access, bind to your private LAN IP only. Do not expose the dashboard publicly.

## 5. Scheduled Tasks

Windows scheduled tasks are optional:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/register_telos_radar_split_tasks.ps1
powershell -ExecutionPolicy Bypass -File scripts/register_telos_worldview_task.ps1
```

Review scripts before registering tasks on your machine.
