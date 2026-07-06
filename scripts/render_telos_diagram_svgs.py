#!/usr/bin/env python3
"""Render static SVG diagrams for the Telos overview without external deps."""

from __future__ import annotations

import html
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "telos" / "diagrams" / "rendered"


COLORS = {
    "bg": "#f6f7f9",
    "panel": "#ffffff",
    "text": "#15181d",
    "muted": "#657080",
    "line": "#d5dce6",
    "blue": "#2563eb",
    "green": "#0f8a5f",
    "amber": "#a15c00",
    "red": "#c2413b",
    "purple": "#6d4aff",
    "ink": "#27313f",
}


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def wrap(text: str, width: int) -> list[str]:
    lines: list[str] = []
    for part in str(text).split("\n"):
        lines.extend(textwrap.wrap(part, width=width, break_long_words=False) or [""])
    return lines


class SVG:
    def __init__(self, width: int, height: int, title: str, subtitle: str = "") -> None:
        self.width = width
        self.height = height
        self.parts: list[str] = []
        self.parts.append(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}">'
        )
        self.parts.append("<defs>")
        self.parts.append(
            '<filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">'
            '<feDropShadow dx="0" dy="2" stdDeviation="2" flood-color="#101828" flood-opacity=".14"/>'
            "</filter>"
        )
        self.parts.append(
            '<marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="5" '
            'orient="auto" markerUnits="strokeWidth">'
            '<path d="M 0 0 L 10 5 L 0 10 z" fill="#748094"/></marker>'
        )
        self.parts.append("</defs>")
        self.parts.append(f'<rect width="100%" height="100%" fill="{COLORS["bg"]}"/>')
        self.text(40, 46, title, size=26, weight=760, color=COLORS["text"])
        if subtitle:
            self.text(40, 74, subtitle, size=13, color=COLORS["muted"])

    def raw(self, value: str) -> None:
        self.parts.append(value)

    def text(
        self,
        x: float,
        y: float,
        value: str,
        *,
        size: int = 13,
        color: str = COLORS["ink"],
        weight: int | str = 500,
        anchor: str = "start",
    ) -> None:
        self.parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" fill="{color}" font-family="Segoe UI, Arial, sans-serif" '
            f'font-size="{size}" font-weight="{weight}" text-anchor="{anchor}">{esc(value)}</text>'
        )

    def box(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        title: str,
        body: str = "",
        *,
        fill: str = COLORS["panel"],
        stroke: str = COLORS["line"],
        accent: str = COLORS["blue"],
        title_size: int = 15,
        body_size: int = 12,
        wrap_width: int = 28,
    ) -> None:
        self.raw(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="8" '
            f'fill="{fill}" stroke="{stroke}" filter="url(#shadow)"/>'
        )
        self.raw(f'<rect x="{x:.1f}" y="{y:.1f}" width="5" height="{h:.1f}" rx="2.5" fill="{accent}"/>')
        self.text(x + 16, y + 25, title, size=title_size, weight=720, color=COLORS["text"])
        if body:
            for i, line in enumerate(wrap(body, wrap_width)[:5]):
                self.text(x + 16, y + 48 + i * (body_size + 5), line, size=body_size, color=COLORS["muted"])

    def group_box(self, x: float, y: float, w: float, h: float, title: str) -> None:
        self.raw(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="12" '
            f'fill="#ffffff" stroke="{COLORS["line"]}" stroke-dasharray="6 5"/>'
        )
        self.text(x + 16, y + 26, title, size=13, weight=740, color=COLORS["muted"])

    def line(self, x1: float, y1: float, x2: float, y2: float, *, color: str = "#748094", arrow: bool = True) -> None:
        marker = ' marker-end="url(#arrow)"' if arrow else ""
        self.raw(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{color}" stroke-width="2.2" stroke-linecap="round"{marker}/>'
        )

    def path(self, d: str, *, color: str = "#748094", arrow: bool = True, dash: bool = False) -> None:
        marker = ' marker-end="url(#arrow)"' if arrow else ""
        dashed = ' stroke-dasharray="6 5"' if dash else ""
        self.raw(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2.2" stroke-linecap="round"{dashed}{marker}/>')

    def save(self, path: Path) -> None:
        self.parts.append("</svg>")
        path.write_text("\n".join(self.parts) + "\n", encoding="utf-8")


def architecture() -> None:
    s = SVG(1600, 1040, "Telos Complete Architecture", "Daily scheduler -> input layer -> processing layer, observed through the dashboard")

    s.box(610, 105, 300, 78, "Daily Scheduler", "starts the data collection loop", accent=COLORS["blue"], wrap_width=34)

    s.group_box(60, 230, 500, 235, "Input Layer")
    s.box(95, 285, 130, 82, "Feeds", "RSS, official sources, publishers", accent=COLORS["green"], wrap_width=16)
    s.box(245, 285, 130, 82, "APIs", "reader fallback, market data", accent=COLORS["amber"], wrap_width=16)
    s.box(395, 285, 130, 82, "User Context", "notes, theories, memories", accent=COLORS["purple"], wrap_width=16)

    s.group_box(610, 230, 520, 565, "Processing Layer")
    s.box(650, 285, 170, 70, "Scan", "collect and dedupe raw signals", accent=COLORS["blue"], wrap_width=22)
    s.box(900, 285, 170, 70, "Prefilter", "fast source and topic scoring", accent=COLORS["blue"], wrap_width=22)
    s.box(650, 405, 170, 70, "Full Fetch", "article text and reader fallback", accent=COLORS["amber"], wrap_width=22)
    s.box(900, 405, 170, 70, "Qwen Triage", "full-text relevance", accent=COLORS["amber"], wrap_width=22)
    s.box(650, 525, 170, 70, "Dossiers", "grounded article analysis", accent=COLORS["green"], wrap_width=22)
    s.box(900, 525, 170, 70, "Domain Syntheses", "AI, geopolitics, finance", accent=COLORS["green"], wrap_width=22)
    s.box(650, 645, 170, 70, "Worldview", "cross-domain causal model", accent=COLORS["purple"], wrap_width=22)
    s.box(900, 645, 170, 70, "Dreaming", "forecasts and cautious updates", accent=COLORS["red"], wrap_width=22)

    s.group_box(1180, 230, 360, 305, "Memory And Files")
    s.box(1215, 285, 135, 70, "telos.db", "claims, beliefs, evidence", accent=COLORS["blue"], wrap_width=16)
    s.box(1370, 285, 135, 70, "Reports", "dossiers, packs, queues", accent=COLORS["green"], wrap_width=16)
    s.box(1215, 400, 135, 70, "Forecasts", "ledger and calibration", accent=COLORS["purple"], wrap_width=16)
    s.box(1370, 400, 135, 70, "Audit", "reviews and run logs", accent=COLORS["amber"], wrap_width=16)

    s.group_box(1180, 575, 360, 220, "Guardrails")
    s.box(1215, 630, 135, 64, "Quality Gates", "stop weak runs", accent=COLORS["red"], wrap_width=16)
    s.box(1370, 630, 135, 64, "Doubt Engine", "conflicts and falsifiers", accent=COLORS["purple"], wrap_width=16)
    s.box(1292, 715, 135, 64, "Review", "evidence promotion", accent=COLORS["amber"], wrap_width=16)

    s.box(700, 875, 280, 82, "Telos Dashboard", "observes the whole process layer: reports, status, belief graph, reviews", accent=COLORS["blue"], wrap_width=34)
    s.box(1060, 875, 250, 82, "User / Codex / Phone", "accesses dashboard, reads, asks, reviews, adds theories", accent=COLORS["green"], wrap_width=30)

    s.path("M 760 183 C 760 215 310 215 310 285", color=COLORS["blue"])
    s.path("M 760 183 C 760 215 735 240 735 285", color=COLORS["blue"])

    s.line(525, 326, 650, 326)
    s.line(820, 320, 900, 320)
    s.path("M 985 355 C 985 385 735 380 735 405")
    s.line(820, 440, 900, 440)
    s.path("M 985 475 C 985 505 735 500 735 525")
    s.line(820, 560, 900, 560)
    s.path("M 985 595 C 985 625 735 620 735 645")
    s.line(820, 680, 900, 680)

    s.path("M 1070 560 C 1125 560 1140 320 1215 320", color=COLORS["muted"])
    s.path("M 1070 560 C 1160 560 1275 320 1370 320", color=COLORS["muted"])
    s.path("M 985 715 C 1090 750 1130 435 1215 435", color=COLORS["muted"])
    s.path("M 985 715 C 1130 785 1260 745 1292 745", color=COLORS["muted"])
    s.path("M 870 795 C 870 835 840 835 840 875", color=COLORS["blue"], dash=True)
    s.text(870, 835, "dashboard observation over entire process", size=12, color=COLORS["blue"], anchor="middle")
    s.path("M 1505 662 C 1535 820 1010 835 945 875", color=COLORS["purple"], dash=True)
    s.path("M 1350 745 C 1260 845 1030 835 945 875", color=COLORS["amber"], dash=True)
    s.line(1060, 916, 980, 916)
    s.path("M 1185 957 C 1040 1015 470 1010 460 367", color=COLORS["green"], dash=True)
    s.text(1010, 1000, "The process layer feeds the dashboard. The user accesses the dashboard and review feedback shapes the next run.", size=14, color=COLORS["muted"], anchor="middle")
    s.save(OUT / "01-complete-architecture.svg")


def daily_loop() -> None:
    s = SVG(1500, 520, "Automatic Daily Telos Pipeline Loop", "The scheduler starts data collection, then the system builds analysis, worldview and forecasts")
    labels = [
        ("Daily Trigger", "06:00 scheduler", COLORS["blue"]),
        ("AI Scan", "sources and candidates", COLORS["blue"]),
        ("AI Deep", "dossiers and synthesis", COLORS["green"]),
        ("Geopolitics", "domain radar", COLORS["amber"]),
        ("Finance", "domain radar", COLORS["amber"]),
        ("Markets", "Telos 100", COLORS["purple"]),
        ("Worldview", "cross-domain model", COLORS["purple"]),
        ("Personal", "German briefing", COLORS["green"]),
        ("Dream", "forecasts and updates", COLORS["red"]),
    ]
    x0, y = 55, 170
    w, h, gap = 135, 92, 24
    for i, (title, body, color) in enumerate(labels):
        x = x0 + i * (w + gap)
        s.box(x, y, w, h, title, body, accent=color, wrap_width=18)
        if i:
            s.line(x - gap + 4, y + h / 2, x - 5, y + h / 2)
    s.group_box(350, 320, 465, 105, "Quality gates")
    s.box(375, 355, 120, 48, "AI Gate", "", accent=COLORS["red"], title_size=13)
    s.box(525, 355, 120, 48, "Geo Gate", "", accent=COLORS["red"], title_size=13)
    s.box(675, 355, 120, 48, "Finance Gate", "", accent=COLORS["red"], title_size=13)
    s.path("M 392 262 C 392 300 435 320 435 355", dash=True)
    s.path("M 551 262 C 551 300 585 320 585 355", dash=True)
    s.path("M 710 262 C 710 300 735 320 735 355", dash=True)
    s.path("M 1340 262 C 1390 350 120 390 122 262", color=COLORS["blue"], dash=True)
    s.text(650, 470, "Reports update the dashboard. Review and feedback improve tomorrow's priorities.", size=14, color=COLORS["muted"], anchor="middle")
    s.save(OUT / "02-daily-pipeline-loop.svg")


def knowledge_evolution() -> None:
    s = SVG(1400, 760, "How Telos Knowledge Evolves", "From raw signals to reviewed evidence, claims, beliefs and calibrated forecasts")
    nodes = [
        (80, 145, "Raw Signal", "article, release, market move, note", COLORS["blue"]),
        (330, 145, "Candidate", "score, topic, source", COLORS["blue"]),
        (580, 145, "Dossier", "verified core and limits", COLORS["green"]),
        (830, 145, "Update Queue", "candidate evidence, not truth", COLORS["amber"]),
        (1080, 145, "Source Review", "exact claim comparison", COLORS["amber"]),
        (1080, 330, "Evidence", "for / against plus reliability", COLORS["green"]),
        (830, 330, "Claim", "testable statement", COLORS["purple"]),
        (580, 330, "Belief", "stable action-shaping assumption", COLORS["purple"]),
        (330, 515, "Forecast", "observable probability", COLORS["red"]),
        (580, 515, "Calibration", "resolution and Brier score", COLORS["red"]),
        (830, 515, "World Model", "priorities and causal chains", COLORS["blue"]),
        (80, 515, "Doubt Note", "open conflict or falsifier", COLORS["amber"]),
    ]
    for x, y, title, body, color in nodes:
        s.box(x, y, 190, 82, title, body, accent=color, wrap_width=24)
    for x1, y1, x2, y2 in [(270,186,330,186),(520,186,580,186),(770,186,830,186),(1020,186,1080,186)]:
        s.line(x1, y1, x2, y2)
    s.line(1175, 227, 1175, 330)
    s.line(1080, 371, 1020, 371)
    s.line(830, 371, 770, 371)
    s.path("M 675 412 C 675 470 425 470 425 515")
    s.line(520, 556, 580, 556)
    s.line(770, 556, 830, 556)
    s.path("M 925 515 C 930 455 680 440 675 412", dash=True)
    s.path("M 1080 205 C 900 280 230 420 175 515", color=COLORS["amber"], dash=True)
    s.path("M 830 596 C 560 700 120 660 175 227", color=COLORS["blue"], dash=True)
    s.text(260, 680, "Key rule: a report is not evidence. Evidence only exists after review against a specific claim.", size=15, color=COLORS["text"])
    s.save(OUT / "03-knowledge-evolution.svg")


def data_model() -> None:
    s = SVG(1300, 820, "Telos Data Model", "The local database and report files keep claims, beliefs, evidence, forecasts and reviews auditable")
    entities = [
        (80, 140, "MEMORY", "notes, context, theories", COLORS["blue"]),
        (365, 140, "CLAIM", "testable statement", COLORS["purple"]),
        (650, 140, "BELIEF", "stable assumption", COLORS["purple"]),
        (935, 140, "EVIDENCE", "polarity, source, reliability", COLORS["green"]),
        (80, 420, "RADAR RUN", "fetch and scan metadata", COLORS["blue"]),
        (365, 420, "RADAR ITEM", "signal, URL, score", COLORS["blue"]),
        (650, 420, "DOSSIER", "grounded article analysis", COLORS["green"]),
        (935, 420, "REVIEW", "audit and approval notes", COLORS["amber"]),
        (365, 630, "DREAM RUN", "bounded reflection", COLORS["red"]),
        (650, 630, "FORECAST", "probability and outcome", COLORS["red"]),
    ]
    for x, y, title, body, color in entities:
        s.box(x, y, 210, 92, title, body, accent=color, wrap_width=26)
    s.line(290, 186, 365, 186)
    s.line(575, 186, 650, 186)
    s.line(860, 186, 935, 186)
    s.path("M 935 207 C 840 280 565 280 470 232")
    s.line(290, 466, 365, 466)
    s.line(575, 466, 650, 466)
    s.line(860, 466, 935, 466)
    s.path("M 755 512 C 755 570 755 570 755 630")
    s.line(575, 676, 650, 676)
    s.path("M 1040 512 C 1040 670 860 700 860 676", dash=True)
    s.path("M 470 630 C 430 560 430 315 470 232", dash=True)
    s.text(80, 755, "SQLite stores structured state. Markdown stores human-readable reports, dossiers, queues and ledgers.", size=15, color=COLORS["text"])
    s.save(OUT / "04-data-model.svg")


def agent_roles() -> None:
    s = SVG(1350, 760, "Local Qwen Agent Roles And Permissions", "Models can write text/JSON. Python validators decide what becomes state.")
    roles = [
        (80, 150, "Prefilter", "title, source, snippet", COLORS["blue"]),
        (300, 150, "Triage", "full text relevance", COLORS["blue"]),
        (520, 150, "Dossier Writer", "grounded article analysis", COLORS["green"]),
        (740, 150, "Synthesis", "domain summary", COLORS["green"]),
        (960, 150, "Worldview", "cross-domain integration", COLORS["purple"]),
        (80, 380, "Dream A", "imaginative pass", COLORS["red"]),
        (300, 380, "Dream C", "skeptical critic", COLORS["red"]),
        (520, 380, "Dream B", "final arbiter", COLORS["red"]),
        (740, 380, "Personal", "German briefing only", COLORS["green"]),
    ]
    for x, y, title, body, color in roles:
        s.box(x, y, 175, 82, title, body, accent=color, wrap_width=20)
    s.group_box(960, 345, 300, 250, "Permission boundary")
    s.box(990, 385, 230, 54, "Text or JSON only", "", accent=COLORS["blue"], title_size=14)
    s.box(990, 455, 230, 54, "No shell / browser / mouse", "", accent=COLORS["red"], title_size=14)
    s.box(990, 525, 230, 54, "Core beliefs locked", "", accent=COLORS["purple"], title_size=14)
    for x, y, *_ in roles:
        s.path(f"M {x+175} {y+41} C 890 {y+41} 900 412 990 412", dash=True)
    s.path("M 1105 439 C 1105 450 1105 450 1105 455")
    s.path("M 1105 509 C 1105 520 1105 520 1105 525")
    s.text(80, 660, "Only the Dreaming stage can propose bounded state updates. Evidence promotion still needs review.", size=15, color=COLORS["text"])
    s.save(OUT / "05-agent-roles.svg")


def dashboard_flow() -> None:
    s = SVG(1400, 720, "Automatic Loop And Dashboard Monitoring", "The scheduler starts the run; the dashboard watches status, reports and review outputs")
    actors = [
        (90, "Scheduler"),
        (310, "Dashboard"),
        (560, "telos_dashboard.py"),
        (830, "Daily loop scripts"),
        (1100, "Pipeline + files"),
    ]
    for x, label in actors:
        s.box(x, 120, 170, 56, label, "", accent=COLORS["blue"], title_size=14)
        s.line(x + 85, 176, x + 85, 610, color="#c3cad5", arrow=False)
    steps = [
        (90, 830, 220, "daily trigger starts data collection"),
        (310, 560, 280, "poll status"),
        (560, 830, 340, "read status/logs"),
        (830, 1100, 400, "scan, deep, domains, worldview, dream"),
        (1100, 560, 470, "write reports, db, status"),
        (310, 560, 540, "poll status and reports"),
    ]
    for x1, x2, y, label in steps:
        s.line(x1 + 85, y, x2 + 85, y)
        s.text((x1 + x2) / 2 + 85, y - 10, label, size=12, color=COLORS["muted"], anchor="middle")
    s.box(520, 600, 250, 62, "Single-run guard", "skip or report running if active", accent=COLORS["red"])
    s.save(OUT / "06-dashboard-control-flow.svg")


def gallery() -> None:
    cards = []
    for svg in sorted(OUT.glob("*.svg")):
        cards.append(
            f'<article><h2>{esc(svg.stem.replace("-", " ").title())}</h2>'
            f'<a href="{esc(svg.name)}"><img src="{esc(svg.name)}" alt="{esc(svg.stem)}"></a></article>'
        )
    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Telos Diagrams</title>
  <style>
    body {{ margin: 0; padding: 24px; background: #f6f7f9; color: #15181d; font: 14px/1.45 system-ui, sans-serif; }}
    h1 {{ margin: 0 0 18px; }}
    article {{ margin: 0 0 24px; padding: 16px; background: white; border: 1px solid #dce1e8; border-radius: 10px; }}
    h2 {{ margin: 0 0 12px; font-size: 16px; }}
    img {{ display: block; width: 100%; height: auto; border: 1px solid #dce1e8; border-radius: 8px; background: #f6f7f9; }}
  </style>
</head>
<body>
  <h1>Telos Diagram Gallery</h1>
  {''.join(cards)}
</body>
</html>
"""
    (OUT / "index.html").write_text(html_doc, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    architecture()
    daily_loop()
    knowledge_evolution()
    data_model()
    agent_roles()
    dashboard_flow()
    gallery()
    print(f"rendered={OUT.relative_to(ROOT)} svgs={len(list(OUT.glob('*.svg')))}")


if __name__ == "__main__":
    main()
