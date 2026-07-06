# Operating Telos With an AI Agent

Telos is designed so a user can operate it through a normal chat with an AI
coding agent instead of manually remembering every command.

The user gives intent. The agent runs commands, edits configs, checks outputs,
keeps private files out of Git and explains what changed.

## User Role

The user should provide:

- theories, claims, questions and priorities
- new topics or sources worth monitoring
- feedback on report quality
- approval before publishing, deleting, exposing dashboards or changing sensitive settings
- judgment on whether a generated evidence update actually makes sense

The user does not need to memorize every script.

## Agent Role

The agent should:

- retrieve relevant context before acting
- store memories, claims and project notes in the correct Telos layer
- edit radar configs when topics or sources change
- run scan, deep, worldview, market and dream stages as requested
- inspect reports and quality gates, not just file existence
- promote evidence only after source review
- keep generated private data out of Git
- explain failures and repair the pipeline when possible

## Common Chat Requests

Examples:

```text
Add biotech automation as a new radar topic.
```

The agent should edit the relevant config, add keywords and possibly sources,
validate JSON, run a scan and inspect whether signals are being routed correctly.

```text
Replace the Telos 100 with a robotics and energy watchlist.
```

The agent should edit `telos_market_watchlist.json`, keep exactly 100 stocks
unless the code is intentionally changed, run `python telos_market.py run` and
check the generated report.

```text
Check this claim against today's evidence.
```

The agent should retrieve context, read the relevant reports and original
sources, then add supporting or opposing evidence only if the source actually
matches the claim.

```text
Run today's Telos loop.
```

The agent should run the configured scripts, monitor quality gates, then show
the user the important reports and failures.

```text
Show me what changed in the worldview today.
```

The agent should read the daily synthesis/worldview outputs and summarize the
highest-impact belief, claim, watchpoint and forecast changes.

## Commands Agents Should Prefer

Retrieve context:

```powershell
python telos.py context "<current user request>"
```

Add memory:

```powershell
python telos.py add "<text>" --tags "<comma,separated,tags>"
```

Add project/status/style notes without claim extraction:

```powershell
python telos.py add "<project/status/style note>" --tags "project,status" --no-extract
```

Create a claim:

```powershell
python telos.py claim "<testable statement>" --type theory --confidence 0.5 --importance 0.7
```

Attach evidence after review:

```powershell
python telos.py evidence claim <claim_id> for "<evidence summary>" --source "<source>" --reliability 0.7
python telos.py evidence claim <claim_id> against "<evidence summary>" --source "<source>" --reliability 0.7
```

Run the daily AI radar:

```powershell
python telos_radar.py run --stage scan
python telos_radar.py run --stage deep
```

Run domain radars:

```powershell
python telos_domain_radar.py run --config telos_geopolitics_config.json --stage all
python telos_domain_radar.py run --config telos_finance_config.json --stage all
```

Run market and worldview:

```powershell
python telos_market.py run
python telos_worldview.py run
```

## Dashboard

The dashboard is optional. It is useful for browsing reports, claims, beliefs,
market outputs and run status.

Local-only:

```powershell
python telos_dashboard.py --host 127.0.0.1 --port 8765
```

For phone access, bind only to a private LAN IP. Do not expose the dashboard to
the public internet without adding authentication and understanding the privacy
risk.

## Operating Principle

Telos should not auto-believe its own reports. The pipeline creates candidates,
dossiers and review queues. The agent can help process them, but confidence
should move slowly, explicitly and with a source trail.
