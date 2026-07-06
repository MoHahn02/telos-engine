# Telos Workspace Protocol

This workspace contains a local Telos Engine memory store.

Use this file as operating context for AI coding agents working in the repository.

## Core Rules

- Treat generated reports, memories, claims, beliefs and the SQLite database as private local state.
- Do not commit `telos/telos.db` or generated `telos/radar`, `telos/finance`, `telos/geopolitics`, `telos/worldview`, `telos/personal`, `telos/dreams` outputs.
- Raw input is memory, not truth.
- Claims are testable statements with confidence.
- Beliefs are more stable, action-shaping claims.
- Evidence should support or weaken a specific claim or belief.
- Keep uncertainty explicit.
- Do not silently increase confidence without evidence or a review note.

## Useful Commands

Initialize:

```powershell
python telos.py init
python telos.py seed
```

Context retrieval:

```powershell
python telos.py context "<current request>"
```

Add memory:

```powershell
python telos.py add "<text>" --tags "<comma,separated,tags>"
```

Add project/status notes without claim extraction:

```powershell
python telos.py add "<note>" --tags "project,status" --no-extract
```

Run radar:

```powershell
python telos_radar.py run --stage scan
python telos_radar.py run --stage deep
```

Run full manual loop:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_telos_manual.ps1
```

Start dashboard:

```powershell
python telos_dashboard.py --host 127.0.0.1 --port 8765
```

## Public Repo Safety

Before publishing, run:

```powershell
git status --short
git check-ignore -v telos/telos.db
git check-ignore -v telos/radar/example.md
```

If any generated personal output appears as unignored, fix `.gitignore` before committing.

## Configuration Work

When the user asks to add scanned topics or sources, edit the relevant config
and follow [docs/CONFIGURATION.md](docs/CONFIGURATION.md). Validate JSON before
running the pipeline.

When the user asks to replace the market universe, edit
`telos_market_watchlist.json` and follow [docs/WATCHLIST.md](docs/WATCHLIST.md).
The default implementation expects exactly 100 stocks.

When the user expects Telos to be operated through chat, follow
[docs/OPERATING_WITH_AN_AGENT.md](docs/OPERATING_WITH_AN_AGENT.md): the agent
should retrieve context, run commands, inspect outputs and explain changes
without committing private generated state.
