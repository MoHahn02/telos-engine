# Telos Engine

Telos Engine is a local second-brain and evidence pipeline for AI-assisted research.
It stores memories, claims, beliefs, evidence and daily research outputs in a local
SQLite database and Markdown files.

The core idea is simple:

- raw inputs become memories, not truth
- claims are explicit statements with confidence and evidence
- beliefs are slower-moving, action-shaping claims
- daily radar runs collect signals, build dossiers and prepare review queues
- downstream worldview and dream stages are gated by quality checks

This repository is the public template version. It contains no private beliefs,
reports, database, forecasts or personal daily briefings.

## Features

- Local memory, claim, belief and evidence store
- RSS/Atom/arXiv radar pipeline
- Domain radars for AI, geopolitics and finance
- Optional local LLM analysis through Ollama
- Market watchlist ranking tied to claim strength
- Dashboard for browsing claims, beliefs, reports and run status
- Windows scripts for manual runs and scheduled tasks

## Requirements

- Python 3.11+
- Windows PowerShell for the included task scripts
- Optional: Ollama for local model analysis

The core memory store uses only the Python standard library. Tests use `pytest`.

## Quick Start

```powershell
git clone https://github.com/YOUR_USER/telos-engine.git
cd telos-engine

python telos.py init
python telos.py seed
python telos.py list beliefs
```

Start the dashboard:

```powershell
python telos_dashboard.py --host 127.0.0.1 --port 8765
```

Open:

```text
http://127.0.0.1:8765
```

## Add Your First Inputs

Add a memory and let Telos extract candidate claims:

```powershell
python telos.py add "I think AI assistants need durable memory before they become truly personal." --tags ai,memory
```

Add a claim directly:

```powershell
python telos.py claim "Long-horizon task reliability is a better AGI signal than chat quality." --type theory --confidence 0.55 --importance 0.8
```

Attach evidence:

```powershell
python telos.py evidence claim <claim_id> for "Benchmark result or source summary" --source "https://example.com/source" --reliability 0.7
```

Retrieve context for an assistant:

```powershell
python telos.py context "What do I currently believe about AI agents?"
```

## Daily Radar

Run AI radar scan and deep report:

```powershell
python telos_radar.py run --stage scan
python telos_radar.py run --stage deep
```

Run a combined manual loop:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_telos_manual.ps1
```

Generated reports are written under `telos/` and are ignored by Git by default.

## Optional Local LLM

Install Ollama and pull a model:

```powershell
ollama pull qwen3.5:9b
```

Then edit:

```text
telos_radar_config.json
telos_geopolitics_config.json
telos_finance_config.json
```

Set the model fields under `llm_prefilter`, `llm_report` and `daily_synthesis`
to a model available on your machine. If you do not want local LLM analysis,
set the relevant `enabled` fields to `false`.

## Configuration

- `telos_radar_config.json`: AI/frontier/robotics/compute sources and topics
- `telos_geopolitics_config.json`: geopolitics sources and topics
- `telos_finance_config.json`: finance sources and topics
- `telos_market_watchlist.json`: example 100-item research watchlist

The default configs contain no private claim IDs. After creating your own claims,
you can link topic entries or watchlist themes to claim IDs manually.

## Privacy Model

This project is local-first. Your database, reports, memories and generated
dossiers stay under `telos/` and are ignored by Git. Do not remove those ignore
rules unless you intentionally want to publish your private research state.

Read [docs/PRIVACY.md](docs/PRIVACY.md) before making a public repository.

## Architecture

See:

- [docs/SETUP.md](docs/SETUP.md)
- [docs/PRIVACY.md](docs/PRIVACY.md)
- [docs/PUBLISHING.md](docs/PUBLISHING.md)
- [docs/architecture.html](docs/architecture.html)

## Tests

```powershell
python -m pytest
```

## License

MIT. See [LICENSE](LICENSE).
