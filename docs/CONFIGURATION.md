# Configuration

Telos is configured through JSON files in the repository root. The private
database and generated reports live under `telos/`; the scan logic itself is
controlled by the config files.

## Main Config Files

- `telos_radar_config.json`: AI, frontier models, agents, robotics, compute and related infrastructure.
- `telos_geopolitics_config.json`: geopolitics, regulation, conflict, industrial policy and state capacity.
- `telos_finance_config.json`: finance, markets, macro, companies and capital flows.
- `telos_market_watchlist.json`: the thesis-linked market watchlist used by `telos_market.py`.

Each radar config has the same broad structure:

```json
{
  "lookback_hours": 36,
  "min_score": 6,
  "max_report_candidates": 150,
  "max_report_items": 25,
  "topics": [],
  "sources": [],
  "llm_prefilter": {},
  "llm_report": {},
  "daily_synthesis": {}
}
```

## Add a New Scan Topic

Add a topic object to the `topics` array in the relevant config.

Example for `telos_radar_config.json`:

```json
{
  "id": "space_infrastructure",
  "label": "Space Infrastructure",
  "weight": 4,
  "keywords": [
    "satellite",
    "launch vehicle",
    "orbital",
    "space manufacturing",
    "space station",
    "off-world industry"
  ],
  "claim_ids": []
}
```

Field meanings:

- `id`: stable machine-readable identifier. Use lowercase words separated by underscores.
- `label`: readable name used in reports and topic indexes.
- `weight`: how strongly keyword matches should matter in rule scoring. Higher means stronger routing priority.
- `keywords`: terms that should route an article or signal into this topic.
- `claim_ids`: optional links to your own Telos claims, for example `["clm_abc123"]`.

Keep `claim_ids` empty until you have created real local claims:

```powershell
python telos.py claim "Space-based sensors will become active decision systems rather than passive data collectors." --type theory --confidence 0.45 --importance 0.7
```

Then copy the returned `clm_...` ID into the topic.

Important: topic links are routing metadata. They do not prove the claim. Promote
evidence only after reading the source and checking whether it supports or
weakens the exact claim.

## Add a Source

Add source objects to the `sources` array. Telos supports RSS, Atom/arXiv-style
feeds and simple HTML listing pages.

RSS example:

```json
{
  "id": "example_blog",
  "name": "Example Blog",
  "type": "rss",
  "priority": 3,
  "url": "https://example.com/feed.xml"
}
```

arXiv / Atom example:

```json
{
  "id": "arxiv_space",
  "name": "arXiv Space / Robotics",
  "type": "atom",
  "priority": 3,
  "url": "https://export.arxiv.org/api/query?search_query=cat:cs.RO+OR+cat:astro-ph.IM&sortBy=submittedDate&sortOrder=descending&max_results=100"
}
```

HTML listing example:

```json
{
  "id": "example_news",
  "name": "Example News",
  "type": "html_listing",
  "priority": 3,
  "url": "https://example.com/news",
  "link_include": "/news/",
  "link_exclude": "tag|author|privacy",
  "max_links": 30
}
```

Field meanings:

- `priority`: rough source importance. Official labs, primary sources and high-signal research sources should be higher.
- `link_include`: regex or substring pattern for links that should be accepted from HTML listing pages.
- `link_exclude`: regex or substring pattern for links that should be ignored.
- `max_links`: maximum links to collect from one HTML listing page.

Prefer primary sources where possible: official company labs, research groups,
regulators, standards bodies, exchanges, filings, central banks and direct
project blogs.

## Scoring Knobs

Common fields:

- `lookback_hours`: how far back a scan should look.
- `min_score`: minimum rule score for normal digest inclusion.
- `storage_min_score`: lower threshold for storing weaker raw signals.
- `max_report_candidates`: number of candidates passed into deeper triage.
- `max_report_items`: target number of dossiers for the daily report.
- `min_grounded_report_items`: quality gate floor. If fewer dossiers are grounded, downstream stages should stop.
- `negative_keywords`: terms that reduce noisy or low-value matches.

Local model stages:

- `llm_prefilter`: quick first-pass model scoring over title, source, snippet and optional first paragraph.
- `llm_report`: deeper article analysis and dossier generation.
- `daily_synthesis`: second-pass synthesis over the highest-value dossiers.

On small machines, reduce `max_items`, `max_report_items`, `num_ctx` or disable
one of the LLM stages.

## Run After Changes

After editing a radar config:

```powershell
python telos_radar.py run --stage scan
python telos_radar.py run --stage deep
```

For domain radars:

```powershell
python telos_domain_radar.py run --config telos_geopolitics_config.json --stage all
python telos_domain_radar.py run --config telos_finance_config.json --stage all
```

If you use an AI coding agent, ask it to edit the relevant config, validate the
JSON, run a scan, inspect the outputs and keep generated private files out of
Git.
