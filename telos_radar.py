#!/usr/bin/env python3
"""
Telos Radar

Daily local signal pipeline for AI, agents, robotics, compute, crypto infra,
and related Telos topics. Uses only the Python standard library.
"""

from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import hashlib
import html
import json
import re
import sqlite3
import sys
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
TELOS_DIR = ROOT / "telos"
DB_PATH = TELOS_DIR / "telos.db"
CONFIG_PATH = ROOT / "telos_radar_config.json"
RADAR_DIR = TELOS_DIR / "radar"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "TelosRadar/0.1 Safari/537.36"
)


@dataclass
class FeedItem:
    source_id: str
    source_name: str
    source_priority: int
    title: str
    url: str
    published_at: str | None
    summary: str
    authors: str | None = None


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso_now() -> str:
    return utc_now().isoformat()


def parse_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    value = value.strip()
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except (TypeError, ValueError, IndexError):
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            parsed = dt.datetime.strptime(value, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.timezone.utc)
            return parsed.astimezone(dt.timezone.utc)
        except ValueError:
            continue
    return None


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def slugify(value: str, max_length: int = 90) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    if not value:
        value = "item"
    return value[:max_length].strip("-") or "item"


def md_link(target: Path, base_dir: Path) -> str:
    return target.relative_to(base_dir).as_posix()


def stable_id(*parts: str) -> str:
    raw = "|".join(part.strip().lower() for part in parts if part)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Missing config: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def connect() -> sqlite3.Connection:
    TELOS_DIR.mkdir(exist_ok=True)
    RADAR_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS radar_runs (
            id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL,
            config_hash TEXT NOT NULL,
            fetched_count INTEGER NOT NULL DEFAULT 0,
            stored_count INTEGER NOT NULL DEFAULT 0,
            digest_path TEXT,
            report_path TEXT,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS radar_items (
            id TEXT PRIMARY KEY,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            source_id TEXT NOT NULL,
            source_name TEXT NOT NULL,
            source_priority INTEGER NOT NULL,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            published_at TEXT,
            summary TEXT NOT NULL,
            score INTEGER NOT NULL,
            topic_hits TEXT NOT NULL,
            keyword_hits TEXT NOT NULL,
            negative_hits TEXT NOT NULL DEFAULT '[]',
            claim_ids TEXT NOT NULL,
            raw TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'new'
        );

        CREATE INDEX IF NOT EXISTS idx_radar_items_seen ON radar_items(last_seen_at);
        CREATE INDEX IF NOT EXISTS idx_radar_items_score ON radar_items(score DESC);
        CREATE INDEX IF NOT EXISTS idx_radar_items_source ON radar_items(source_id);

        CREATE TABLE IF NOT EXISTS radar_failures (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            source_id TEXT NOT NULL,
            source_name TEXT NOT NULL,
            url TEXT NOT NULL,
            error TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS radar_article_reads (
            item_id TEXT PRIMARY KEY,
            fetched_at TEXT NOT NULL,
            status TEXT NOT NULL,
            url TEXT NOT NULL,
            title TEXT NOT NULL,
            text TEXT NOT NULL,
            error TEXT
        );

        CREATE TABLE IF NOT EXISTS radar_llm_analyses (
            id TEXT PRIMARY KEY,
            item_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_hash TEXT NOT NULL,
            analysis TEXT NOT NULL,
            status TEXT NOT NULL,
            error TEXT
        );

        CREATE TABLE IF NOT EXISTS radar_llm_triage (
            id TEXT PRIMARY KEY,
            item_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_hash TEXT NOT NULL,
            relevance INTEGER NOT NULL,
            decision TEXT NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL,
            error TEXT
        );

        CREATE TABLE IF NOT EXISTS radar_llm_prefilter (
            id TEXT PRIMARY KEY,
            item_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_hash TEXT NOT NULL,
            score INTEGER NOT NULL,
            category TEXT NOT NULL,
            should_read_full_article INTEGER NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL,
            error TEXT
        );

        CREATE TABLE IF NOT EXISTS radar_daily_syntheses (
            id TEXT PRIMARY KEY,
            date TEXT NOT NULL,
            run_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_hash TEXT NOT NULL,
            synthesis TEXT NOT NULL,
            status TEXT NOT NULL,
            error TEXT
        );
        """
    )
    ensure_column(con, "radar_items", "negative_hits", "TEXT NOT NULL DEFAULT '[]'")
    ensure_column(con, "radar_runs", "report_path", "TEXT")
    con.commit()


def ensure_column(con: sqlite3.Connection, table: str, column: str, declaration: str) -> None:
    columns = {row["name"] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def fetch_url(url: str, timeout: int = 25) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def reader_api_url(url: str) -> str:
    return "https://r.jina.ai/http://" + url


def fetch_reader_text(url: str, timeout: int = 35, max_chars: int = 30000) -> str:
    payload = fetch_url(reader_api_url(url), timeout=timeout)
    text = payload.decode("utf-8", errors="replace")
    if re.search(r"(?i)\b(451|unavailable for legal reasons|access denied|captcha)\b", text[:1000]):
        raise ValueError("Reader API did not return readable article content")
    lines = []
    for line in text.splitlines():
        if line.startswith("Warning:"):
            continue
        lines.append(line)
    return clean_text("\n".join(lines))[:max_chars]


def is_google_news_article_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.netloc.lower() == "news.google.com" and "/articles/" in parsed.path


def resolve_google_news_url(url: str, timeout: int = 25) -> str:
    """Resolve a Google News RSS article wrapper to its publisher URL."""
    if not is_google_news_article_url(url):
        return url
    article_id = urllib.parse.urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    if not article_id:
        raise ValueError("Google News URL has no article id")

    page_url = f"https://news.google.com/articles/{article_id}?hl=en-US&gl=US&ceid=US:en"
    page = fetch_url(page_url, timeout=timeout).decode("utf-8", errors="replace")
    timestamp_match = re.search(r'data-n-a-ts="([^"]+)"', page)
    signature_match = re.search(r'data-n-a-sg="([^"]+)"', page)
    if not timestamp_match or not signature_match:
        raise ValueError("Google News did not expose article resolution parameters")

    timestamp = timestamp_match.group(1)
    signature = html.unescape(signature_match.group(1))
    request_body = (
        '["garturlreq",[["en-US","US",'
        '["FINANCE_TOP_INDICES","WEB_TEST_1_0_0"],null,null,1,1,'
        '"US:en",null,180,null,null,null,null,null,0,null,null,'
        '[1608992183,723341000]],"en-US","US",1,[2,3,4,8],1,0,'
        f'"655000234",0,0,null,0],"{article_id}",{timestamp},"{signature}"]'
    )
    batch = [[['Fbv4je', request_body, None, 'generic']]]
    encoded = urllib.parse.urlencode({"f.req": json.dumps(batch)}).encode("utf-8")
    request = urllib.request.Request(
        "https://news.google.com/_/DotsSplashUi/data/batchexecute?rpcids=Fbv4je",
        data=encoded,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
    for line in raw.splitlines():
        if not line.startswith("[["):
            continue
        outer = json.loads(line)
        decoded = json.loads(outer[0][2])
        resolved = str(decoded[1])
        if resolved.startswith(("http://", "https://")):
            return resolved
    raise ValueError("Google News article URL could not be resolved")


def resolve_article_url(url: str, timeout: int = 25) -> str:
    return resolve_google_news_url(url, timeout=timeout) if is_google_news_article_url(url) else url


def text_of(node: ET.Element, path: str, ns: dict[str, str]) -> str:
    found = node.find(path, ns)
    if found is None or found.text is None:
        return ""
    return clean_text(found.text)


def parse_feed(source: dict[str, Any], payload: bytes) -> list[FeedItem]:
    root = ET.fromstring(payload)
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "dc": "http://purl.org/dc/elements/1.1/",
    }
    if root.tag.endswith("feed"):
        return parse_atom(source, root, ns)
    return parse_rss(source, root, ns)


def parse_html_listing(source: dict[str, Any], payload: bytes) -> list[FeedItem]:
    page = payload.decode("utf-8", errors="ignore")
    include = source.get("link_include", "")
    exclude = source.get("link_exclude", "")
    max_items = int(source.get("max_links", 40))
    seen: set[str] = set()
    items: list[FeedItem] = []
    for match in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', page, re.IGNORECASE | re.DOTALL):
        href = html.unescape(match.group(1)).strip()
        if not href or href.startswith(("#", "mailto:", "tel:")):
            continue
        url = urllib.parse.urljoin(source["url"], href)
        if include and not re.search(include, url):
            continue
        if exclude and re.search(exclude, url):
            continue
        if url in seen:
            continue
        title = clean_text(match.group(2))
        if not title or len(title) < 8:
            continue
        seen.add(url)
        published = embedded_date_from_text(title)
        items.append(make_item(source, title, url, published, title, None))
        if len(items) >= max_items:
            break
    return items


def embedded_date_from_text(text: str) -> str | None:
    months = {
        "jan": 1,
        "january": 1,
        "feb": 2,
        "february": 2,
        "mar": 3,
        "march": 3,
        "apr": 4,
        "april": 4,
        "may": 5,
        "jun": 6,
        "june": 6,
        "jul": 7,
        "july": 7,
        "aug": 8,
        "august": 8,
        "sep": 9,
        "sept": 9,
        "september": 9,
        "oct": 10,
        "october": 10,
        "nov": 11,
        "november": 11,
        "dec": 12,
        "december": 12,
    }
    match = re.search(
        r"\b("
        + "|".join(months.keys())
        + r")\.?\s+(\d{1,2}),\s+(20\d{2})\b",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    month = months[match.group(1).lower().rstrip(".")]
    day = int(match.group(2))
    year = int(match.group(3))
    return dt.datetime(year, month, day, tzinfo=dt.timezone.utc).isoformat()


def parse_source_payload(source: dict[str, Any], payload: bytes) -> list[FeedItem]:
    source_type = str(source.get("type", "rss")).lower()
    if source_type in ("rss", "atom"):
        return parse_feed(source, payload)
    if source_type in ("html", "html_listing"):
        return parse_html_listing(source, payload)
    raise ValueError(f"Unsupported source type: {source_type}")


def parse_atom(source: dict[str, Any], root: ET.Element, ns: dict[str, str]) -> list[FeedItem]:
    items: list[FeedItem] = []
    for entry in root.findall("atom:entry", ns):
        title = text_of(entry, "atom:title", ns)
        url = ""
        for link in entry.findall("atom:link", ns):
            href = link.attrib.get("href", "")
            rel = link.attrib.get("rel", "alternate")
            if href and rel in ("alternate", ""):
                url = href
                break
        if not url:
            url = text_of(entry, "atom:id", ns)
        summary = text_of(entry, "atom:summary", ns) or text_of(entry, "atom:content", ns)
        published = text_of(entry, "atom:published", ns) or text_of(entry, "atom:updated", ns)
        authors = ", ".join(
            text_of(author, "atom:name", ns)
            for author in entry.findall("atom:author", ns)
            if text_of(author, "atom:name", ns)
        )
        if title and url:
            items.append(make_item(source, title, url, published, summary, authors or None))
    return items


def parse_rss(source: dict[str, Any], root: ET.Element, ns: dict[str, str]) -> list[FeedItem]:
    items: list[FeedItem] = []
    for item in root.findall(".//item"):
        title = clean_text(item.findtext("title"))
        link = clean_text(item.findtext("link"))
        guid = clean_text(item.findtext("guid"))
        url = link or guid
        published = clean_text(item.findtext("pubDate")) or clean_text(item.findtext("date"))
        summary = clean_text(item.findtext("description")) or clean_text(item.findtext("summary"))
        authors = clean_text(item.findtext("author")) or text_of(item, "dc:creator", ns)
        if title and url:
            items.append(make_item(source, title, url, published, summary, authors or None))
    return items


def make_item(
    source: dict[str, Any],
    title: str,
    url: str,
    published: str | None,
    summary: str,
    authors: str | None,
) -> FeedItem:
    parsed = parse_time(published)
    return FeedItem(
        source_id=source["id"],
        source_name=source["name"],
        source_priority=int(source.get("priority", 1)),
        title=title,
        url=url,
        published_at=parsed.isoformat() if parsed else None,
        summary=summary,
        authors=authors,
    )


def score_item(item: FeedItem, config: dict[str, Any]) -> dict[str, Any]:
    hay_title = item.title.lower()
    hay_body = f"{item.title} {item.summary} {item.url}".lower()
    topic_hits: list[dict[str, Any]] = []
    keyword_hits: list[str] = []
    negative_hits: list[str] = []
    claim_ids: set[str] = set()
    score = item.source_priority

    for topic in config["topics"]:
        topic_keywords: list[str] = []
        for keyword in topic["keywords"]:
            low = keyword.lower()
            if low in hay_body:
                topic_keywords.append(keyword)
                keyword_hits.append(keyword)
                score += int(topic.get("weight", 1))
                if low in hay_title:
                    score += 3
        if topic_keywords:
            topic_hits.append(
                {
                    "id": topic["id"],
                    "label": topic["label"],
                    "keywords": sorted(set(topic_keywords)),
                }
            )
            for claim_id in topic.get("claim_ids", []):
                claim_ids.add(claim_id)

    for keyword in config.get("negative_keywords", []):
        low = keyword.lower()
        if low in hay_body:
            negative_hits.append(keyword)
            score -= 8
            if low in hay_title:
                score -= 6

    release_boost = frontier_model_release_boost(item, hay_title, hay_body)
    if release_boost:
        score += release_boost
        keyword_hits.append("frontier model release")
        if not any(topic["id"] == "ai_frontier" for topic in topic_hits):
            topic_hits.append(
                {
                    "id": "ai_frontier",
                    "label": "Frontier AI",
                    "keywords": ["frontier model release"],
                }
            )

    return {
        "score": score,
        "topic_hits": topic_hits,
        "keyword_hits": sorted(set(keyword_hits), key=str.lower),
        "negative_hits": sorted(set(negative_hits), key=str.lower),
        "claim_ids": sorted(claim_ids),
    }


def frontier_model_release_boost(item: FeedItem, hay_title: str, hay_body: str) -> int:
    official_sources = {
        "anthropic_news",
        "openai_news",
        "google_deepmind",
        "google_research",
    }
    major_vendors = (
        "anthropic",
        "openai",
        "deepmind",
        "google",
        "meta",
        "xai",
        "mistral",
    )
    model_terms = (
        "claude opus",
        "claude sonnet",
        "claude haiku",
        "claude fable",
        "claude mythos",
        "fable 5",
        "mythos 5",
        "opus 4",
        "sonnet 4",
        "haiku 4",
        "gpt-",
        "gpt 5",
        "gemini",
        "gemma",
        "llama",
        "grok",
        "mistral",
        "kimi",
    )
    release_terms = (
        "introducing",
        "release",
        "released",
        "launch",
        "launched",
        "available",
        "generally available",
        "new model",
        "next generation",
    )
    benchmark_terms = (
        "benchmark",
        "eval",
        "state-of-the-art",
        "sota",
        "task horizon",
        "long-horizon",
        "coding",
        "reasoning",
        "agentic",
    )
    has_vendor = any(term in hay_body for term in major_vendors)
    has_model = any(term in hay_body for term in model_terms)
    has_release = any(term in hay_body for term in release_terms)
    if not (has_vendor and has_model and has_release):
        return 0

    boost = 35
    if item.source_id in official_sources:
        boost += 25
    if any(term in hay_body for term in benchmark_terms):
        boost += 15
    if any(term in hay_title for term in ("claude", "mythos", "fable", "gpt", "gemini")):
        boost += 10
    return boost


def within_lookback(item: FeedItem, hours: int) -> bool:
    if not item.published_at:
        return True
    published = parse_time(item.published_at)
    if not published:
        return True
    return published >= utc_now() - dt.timedelta(hours=hours)


def upsert_item(con: sqlite3.Connection, item: FeedItem, analysis: dict[str, Any]) -> bool:
    item_id = stable_id(item.url, item.title)
    now = iso_now()
    raw = {
        "authors": item.authors,
        "source_id": item.source_id,
        "source_name": item.source_name,
    }
    existing = con.execute("SELECT id FROM radar_items WHERE id = ?", (item_id,)).fetchone()
    if existing:
        con.execute(
            """
            UPDATE radar_items
            SET last_seen_at = ?, score = ?, topic_hits = ?, keyword_hits = ?,
                negative_hits = ?, claim_ids = ?, summary = ?, raw = ?
            WHERE id = ?
            """,
            (
                now,
                analysis["score"],
                json.dumps(analysis["topic_hits"], ensure_ascii=False),
                json.dumps(analysis["keyword_hits"], ensure_ascii=False),
                json.dumps(analysis.get("negative_hits", []), ensure_ascii=False),
                json.dumps(analysis["claim_ids"], ensure_ascii=False),
                item.summary,
                json.dumps(raw, ensure_ascii=False),
                item_id,
            ),
        )
        return False

    con.execute(
        """
        INSERT INTO radar_items(
            id, first_seen_at, last_seen_at, source_id, source_name, source_priority,
            title, url, published_at, summary, score, topic_hits, keyword_hits,
            negative_hits, claim_ids, raw
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item_id,
            now,
            now,
            item.source_id,
            item.source_name,
            item.source_priority,
            item.title,
            item.url,
            item.published_at,
            item.summary,
            analysis["score"],
            json.dumps(analysis["topic_hits"], ensure_ascii=False),
            json.dumps(analysis["keyword_hits"], ensure_ascii=False),
            json.dumps(analysis.get("negative_hits", []), ensure_ascii=False),
            json.dumps(analysis["claim_ids"], ensure_ascii=False),
            json.dumps(raw, ensure_ascii=False),
        ),
    )
    return True


def item_exists(con: sqlite3.Connection, item: FeedItem) -> bool:
    item_id = stable_id(item.url, item.title)
    row = con.execute("SELECT 1 FROM radar_items WHERE id = ?", (item_id,)).fetchone()
    return row is not None


def run_pipeline(args: argparse.Namespace) -> None:
    config = load_config(Path(args.config))
    if args.lookback_hours is not None:
        config["lookback_hours"] = args.lookback_hours
    if args.min_score is not None:
        config["min_score"] = args.min_score

    con = connect()
    init_db(con)

    run_id = "run_" + utc_now().strftime("%Y%m%d_%H%M%S")
    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    con.execute(
        "INSERT INTO radar_runs(id, started_at, status, config_hash) VALUES (?, ?, ?, ?)",
        (run_id, iso_now(), "running", config_hash),
    )
    con.commit()

    stage = str(getattr(args, "stage", "all"))
    fetched = 0
    stored = 0
    failures: list[dict[str, str]] = []
    digest_path: Path | None = None
    report_path: Path | None = None
    notes: list[str] = [f"stage={stage}"]

    try:
        if stage in ("scan", "all"):
            fetched, stored, failures = fetch_and_store_sources(con, run_id, config, timeout=args.timeout)
            digest_path = write_digest(con, run_id, config, failures, fetched=fetched, stored=stored)
            print(f"digest: {digest_path.relative_to(ROOT)}")

        if stage == "scan":
            prep_path = write_candidate_prep(con, run_id, config, failures, timeout=args.timeout, use_llm=not args.no_llm)
            report_path = prep_path
            notes.append("prepared candidate cache")
            print(f"candidate_prep: {prep_path.relative_to(ROOT)}")

        if stage in ("deep", "all"):
            if digest_path is None:
                digest_path = latest_digest_path()
            if stage == "deep":
                failures = recent_failures_for_latest_scan(con)
            report_path = write_report(con, run_id, config, failures, timeout=args.timeout, use_llm=not args.no_llm)
            print(f"report: {report_path.relative_to(ROOT)}")

        status = "ok" if not failures else "partial"
        finish_run(
            con=con,
            run_id=run_id,
            status=status,
            fetched=fetched,
            stored=stored,
            digest_path=digest_path,
            report_path=report_path,
            notes=", ".join(notes + [f"{len(failures)} source failures"]),
        )
    except Exception as exc:
        finish_run(
            con=con,
            run_id=run_id,
            status="error",
            fetched=fetched,
            stored=stored,
            digest_path=digest_path,
            report_path=report_path,
            notes=", ".join(notes + [f"error={exc}"]),
        )
        raise
    finally:
        con.close()

    print(f"run: {run_id}")
    print(f"stage: {stage}")
    print(f"fetched: {fetched}")
    print(f"new_items: {stored}")
    if failures:
        print(f"source_failures: {len(failures)}")


def fetch_and_store_sources(
    con: sqlite3.Connection,
    run_id: str,
    config: dict[str, Any],
    timeout: int,
) -> tuple[int, int, list[dict[str, str]]]:
    fetched = 0
    stored = 0
    failures: list[dict[str, str]] = []
    for source in config["sources"]:
        try:
            payload = fetch_url(source["url"], timeout=timeout)
            items = parse_source_payload(source, payload)
            fetched += len(items)
        except (urllib.error.URLError, TimeoutError, ET.ParseError, ValueError) as exc:
            failure = {
                "source_id": source["id"],
                "source_name": source["name"],
                "url": source["url"],
                "error": str(exc),
            }
            failures.append(failure)
            con.execute(
                """
                INSERT INTO radar_failures(id, run_id, created_at, source_id, source_name, url, error)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stable_id(run_id, source["id"], str(time.time())),
                    run_id,
                    iso_now(),
                    source["id"],
                    source["name"],
                    source["url"],
                    str(exc),
                ),
            )
            continue

        for item in items[: int(config.get("max_items_per_source", 75))]:
            if not within_lookback(item, int(config.get("lookback_hours", 36))):
                continue
            analysis = score_item(item, config)
            storage_min_score = int(config.get("storage_min_score", config.get("min_score", 6)))
            if analysis["score"] < storage_min_score and not item_exists(con, item):
                continue
            if upsert_item(con, item, analysis):
                stored += 1
    con.commit()
    return fetched, stored, failures


def finish_run(
    con: sqlite3.Connection,
    run_id: str,
    status: str,
    fetched: int,
    stored: int,
    digest_path: Path | None,
    report_path: Path | None,
    notes: str,
) -> None:
    con.execute(
        """
        UPDATE radar_runs
        SET finished_at = ?, status = ?, fetched_count = ?, stored_count = ?, digest_path = ?, report_path = ?, notes = ?
        WHERE id = ?
        """,
        (
            iso_now(),
            status,
            fetched,
            stored,
            str(digest_path.relative_to(ROOT)) if digest_path else None,
            str(report_path.relative_to(ROOT)) if report_path else None,
            notes,
            run_id,
        ),
    )
    con.commit()


def latest_digest_path() -> Path | None:
    paths = sorted(RADAR_DIR.glob("*-daily-radar.md"), key=lambda path: path.stat().st_mtime, reverse=True)
    return paths[0] if paths else None


def recent_failures_for_latest_scan(con: sqlite3.Connection) -> list[dict[str, str]]:
    row = con.execute(
        """
        SELECT id
        FROM radar_runs
        WHERE status IN ('ok', 'partial') AND notes LIKE '%stage=scan%'
        ORDER BY started_at DESC
        LIMIT 1
        """
    ).fetchone()
    if not row:
        return []
    failures = con.execute(
        """
        SELECT source_id, source_name, url, error
        FROM radar_failures
        WHERE run_id = ?
        ORDER BY created_at
        """,
        (row["id"],),
    ).fetchall()
    return [dict(failure) for failure in failures]


def rows_for_digest(con: sqlite3.Connection, config: dict[str, Any]) -> list[sqlite3.Row]:
    max_items = int(config.get("max_digest_items", 40))
    since = (utc_now() - dt.timedelta(hours=int(config.get("lookback_hours", 36)))).isoformat()
    return con.execute(
        """
        SELECT *
        FROM radar_items
        WHERE last_seen_at >= ? AND (published_at IS NULL OR published_at >= ?) AND score >= ?
        ORDER BY score DESC, published_at DESC, first_seen_at DESC
        LIMIT ?
        """,
        (since, since, int(config.get("min_score", 6)), max_items),
    ).fetchall()


def write_digest(
    con: sqlite3.Connection,
    run_id: str,
    config: dict[str, Any],
    failures: list[dict[str, str]],
    fetched: int = 0,
    stored: int = 0,
) -> Path:
    RADAR_DIR.mkdir(parents=True, exist_ok=True)
    date = utc_now().strftime("%Y-%m-%d")
    path = RADAR_DIR / f"{date}-daily-radar.md"
    rows = rows_for_digest(con, config)

    lines: list[str] = []
    lines.append(f"# Telos Daily Radar - {date}")
    lines.append("")
    lines.append(f"- Run: `{run_id}`")
    lines.append(f"- Lookback: `{config.get('lookback_hours', 36)}h`")
    lines.append(f"- Min score: `{config.get('min_score', 6)}`")
    lines.append(f"- Feed entries fetched: `{fetched}`")
    lines.append(f"- Items stored/updated: `{stored}`")
    lines.append(f"- Candidates in digest: `{len(rows)}`")
    lines.append(f"- Source failures: `{len(failures)}`")
    lines.append("")
    lines.append("## Top Signals")
    lines.append("")
    if not rows:
        lines.append("- No matching signals.")
    for row in rows:
        topics = json.loads(row["topic_hits"])
        keywords = json.loads(row["keyword_hits"])
        negative = json.loads(row["negative_hits"] if "negative_hits" in row.keys() else "[]")
        claims = json.loads(row["claim_ids"])
        topic_labels = ", ".join(topic["label"] for topic in topics)
        lines.append(f"### {row['title']}")
        lines.append("")
        lines.append(f"- Source: {row['source_name']}")
        lines.append(f"- Score: `{row['score']}`")
        if row["published_at"]:
            lines.append(f"- Published: `{row['published_at']}`")
        if topic_labels:
            lines.append(f"- Topics: {topic_labels}")
        if keywords:
            lines.append(f"- Keyword hits: {', '.join(keywords[:12])}")
        if negative:
            lines.append(f"- Negative hits: {', '.join(negative[:8])}")
        if claims:
            lines.append(f"- Claim touchpoints: {', '.join(claims)}")
        lines.append(f"- URL: {row['url']}")
        if row["summary"]:
            lines.append("")
            lines.append(clip(row["summary"], 700))
        lines.append("")

    lines.append("## Topic Counts")
    lines.append("")
    counts: dict[str, int] = {}
    for row in rows:
        for topic in json.loads(row["topic_hits"]):
            counts[topic["label"]] = counts.get(topic["label"], 0) + 1
    if counts:
        for label, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"- {label}: {count}")
    else:
        lines.append("- None")

    lines.append("")
    lines.append("## Source Failures")
    lines.append("")
    if failures:
        for failure in failures:
            lines.append(f"- {failure['source_name']}: {failure['error']}")
    else:
        lines.append("- None")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def prepare_daily_candidates(
    con: sqlite3.Connection,
    config: dict[str, Any],
    timeout: int,
    use_llm: bool,
) -> tuple[list[sqlite3.Row], list[dict[str, Any]], bool, bool]:
    llm_config = config.get("llm_report", {})
    llm_enabled = bool(use_llm and llm_config.get("enabled", False))
    triage_enabled = bool(llm_enabled and llm_config.get("triage_enabled", False))
    candidate_rows = rows_for_report_candidates(con, config, use_llm=llm_enabled)

    candidates: list[dict[str, Any]] = []
    for index, row in enumerate(candidate_rows):
        article_text, article_status, article_error = get_or_fetch_article_text(
            con=con,
            row=row,
            max_chars=int(config.get("max_article_chars", 30000)),
            timeout=timeout,
        )
        keywords = json.loads(row["keyword_hits"])
        topics = json.loads(row["topic_hits"])
        claims = json.loads(row["claim_ids"])
        triage = None
        if article_status != "ok":
            triage = {
                "relevance": 0,
                "decision": "skip",
                "reason": f"No grounded current article: {article_error or article_status}",
                "status": "ok",
                "error": "",
            }
        elif triage_enabled and index < int(llm_config.get("triage_max_candidates", 24)):
            triage = get_or_create_llm_triage(
                con=con,
                row=row,
                article_text=article_text or row["summary"],
                topics=topics,
                keywords=keywords,
                claims=claims,
                llm_config=llm_config,
            )
        candidates.append(
            {
                "row": row,
                "topics": topics,
                "keywords": keywords,
                "claims": claims,
                "article_text": article_text,
                "article_status": article_status,
                "article_error": article_error,
                "triage": triage,
            }
        )

    candidates = filter_and_rank_candidates(candidates, config, llm_config, triage_enabled)
    candidates = [candidate for candidate in candidates if candidate["article_status"] == "ok"]
    return candidate_rows, candidates, llm_enabled, triage_enabled


def write_candidate_prep(
    con: sqlite3.Connection,
    run_id: str,
    config: dict[str, Any],
    failures: list[dict[str, str]],
    timeout: int,
    use_llm: bool,
) -> Path:
    RADAR_DIR.mkdir(parents=True, exist_ok=True)
    date = utc_now().strftime("%Y-%m-%d")
    path = RADAR_DIR / f"{date}-candidate-prep.md"
    candidate_rows, candidates, llm_enabled, triage_enabled = prepare_daily_candidates(
        con=con,
        config=config,
        timeout=timeout,
        use_llm=use_llm,
    )
    selected = candidates[: int(config.get("max_report_items", 8))]
    lines: list[str] = []
    lines.append(f"# Telos Candidate Prep - {date}")
    lines.append("")
    lines.append(f"- Run: `{run_id}`")
    lines.append(f"- Candidate rows: `{len(candidate_rows)}`")
    lines.append(f"- Filtered candidates: `{len(candidates)}`")
    lines.append(f"- Top deep candidates: `{len(selected)}`")
    lines.append(f"- Local LLM prefilter: `{config.get('llm_prefilter', {}).get('model') if llm_enabled else 'disabled'}`")
    lines.append(f"- Local LLM triage: `{triage_enabled}`")
    lines.append("")
    lines.append("## Top Deep Candidates")
    lines.append("")
    if not selected:
        lines.append("- None")
    for index, item in enumerate(selected, start=1):
        row = item["row"]
        topic_labels = ", ".join(topic["label"] for topic in item["topics"]) or "Unclassified"
        lines.append(f"### {index}. {row['title']}")
        lines.append("")
        lines.append(f"- Source: {row['source_name']}")
        lines.append(f"- Final priority: `{final_priority_score(item)}/100`")
        lines.append(f"- Local relevance: `{item_relevance(item)}/100`")
        lines.append(f"- Rule score: `{row['score']}`")
        lines.append(f"- Topics: {topic_labels}")
        lines.append(f"- URL: {row['url']}")
        if item.get("triage"):
            triage = item["triage"]
            lines.append(f"- Triage: `{item_relevance(item)}/100` {triage['decision']} - {triage['reason']}")
        pref = get_latest_prefilter_result(con, row["id"])
        if pref:
            lines.append(f"- Prefilter: `{pref['score']}/100` {pref['category']} - {pref['reason']}")
        lines.append("")
    lines.append("## Source Failures")
    lines.append("")
    if failures:
        for failure in failures:
            lines.append(f"- {failure['source_name']}: {failure['error']}")
    else:
        lines.append("- None")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_report(
    con: sqlite3.Connection,
    run_id: str,
    config: dict[str, Any],
    failures: list[dict[str, str]],
    timeout: int,
    use_llm: bool,
) -> Path:
    RADAR_DIR.mkdir(parents=True, exist_ok=True)
    date = utc_now().strftime("%Y-%m-%d")
    path = RADAR_DIR / f"{date}-daily-report.md"

    llm_config = config.get("llm_report", {})
    llm_max_items = int(llm_config.get("max_items", 0))
    candidate_rows, candidates, llm_enabled, triage_enabled = prepare_daily_candidates(
        con=con,
        config=config,
        timeout=timeout,
        use_llm=use_llm,
    )
    candidates = candidates[: int(config.get("max_report_items", 8))]
    minimum = int(config.get("min_grounded_report_items", 3))
    if len(candidates) < minimum:
        day_dir = RADAR_DIR / date
        day_dir.mkdir(parents=True, exist_ok=True)
        blocked = (
            f"# Telos Daily Report - {date}\n\n"
            "## Quality Gate Failed\n\n"
            f"Only `{len(candidates)}` grounded current items were available; the minimum is `{minimum}`. "
            "No deep report was produced and downstream Telos updates are blocked.\n"
        )
        path.write_text(blocked, encoding="utf-8")
        (day_dir / "daily-synthesis.md").write_text(blocked, encoding="utf-8")
        (day_dir / "index.md").write_text(blocked, encoding="utf-8")
        (day_dir / "quality-gate.json").write_text(
            json.dumps({
                "date": date, "domain": "ai-radar",
                "grounded_dossiers": len(candidates),
                "minimum_grounded_dossiers": minimum, "passed": False,
                "reason": "insufficient grounded current items",
            }, indent=2),
            encoding="utf-8",
        )
        raise RuntimeError(
            f"AI quality gate failed: only {len(candidates)} grounded current items; minimum is {minimum}"
        )

    analyzed: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        row = candidate["row"]
        article_text = candidate["article_text"]
        article_status = candidate["article_status"]
        article_error = candidate["article_error"]
        keywords = candidate["keywords"]
        topics = candidate["topics"]
        item_context = {
            "row": row,
            "topics": topics,
            "keywords": keywords,
            "claims": candidate["claims"],
            "article_text": article_text,
            "article_status": article_status,
            "article_error": article_error,
            "sentences": extract_relevant_sentences(article_text or row["summary"], keywords, limit=5),
            "triage": candidate["triage"],
            "prefilter": get_latest_prefilter_result(con, row["id"]),
        }
        if llm_enabled and index < llm_max_items:
            item_context["llm_analysis"] = get_or_create_llm_analysis(
                con=con,
                row=row,
                article_text=article_text or row["summary"],
                topics=topics,
                keywords=keywords,
                claims=item_context["claims"],
                llm_config=llm_config,
            )
        else:
            item_context["llm_analysis"] = None
        analyzed.append(item_context)

    analyzed = [
        item for item in analyzed
        if item["article_status"] == "ok"
        and (
            not llm_enabled
            or (
                item.get("llm_analysis")
                and item["llm_analysis"]["status"] == "ok"
                and str(item["llm_analysis"].get("analysis", "")).strip()
            )
        )
    ]
    quality_path = RADAR_DIR / date / "quality-gate.json"
    quality_path.parent.mkdir(parents=True, exist_ok=True)
    quality_path.write_text(
        json.dumps(
            {
                "date": date,
                "domain": "ai-radar",
                "grounded_dossiers": len(analyzed),
                "minimum_grounded_dossiers": minimum,
                "passed": len(analyzed) >= minimum,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if len(analyzed) < minimum:
        blocked = (
            f"# Telos Daily Report - {date}\n\n"
            "## Quality Gate Failed\n\n"
            f"Only `{len(analyzed)}` grounded items produced a valid deep analysis; the minimum is `{minimum}`. "
            "No downstream synthesis or Telos update may use this pack.\n"
        )
        path.write_text(blocked, encoding="utf-8")
        (RADAR_DIR / date / "daily-synthesis.md").write_text(blocked, encoding="utf-8")
        (RADAR_DIR / date / "index.md").write_text(blocked, encoding="utf-8")
        raise RuntimeError(
            f"AI quality gate failed after deep analysis: {len(analyzed)} grounded dossiers; minimum is {minimum}"
        )

    docs = write_research_documents(
        con=con,
        analyzed=analyzed,
        date=date,
        run_id=run_id,
        config=config,
        llm_enabled=llm_enabled,
        triage_enabled=triage_enabled,
    )
    synthesis_result = docs.get("synthesis_result")
    if synthesis_result and synthesis_result.get("status") != "ok":
        quality_path.write_text(
            json.dumps({
                "date": date, "domain": "ai-radar",
                "grounded_dossiers": len(analyzed),
                "minimum_grounded_dossiers": minimum, "passed": False,
                "reason": f"daily synthesis failed: {synthesis_result.get('error', 'unknown error')}",
            }, indent=2),
            encoding="utf-8",
        )
        raise RuntimeError(f"AI daily synthesis failed: {synthesis_result.get('error', 'unknown error')}")
    article_paths = docs["article_paths"]

    lines: list[str] = []
    lines.append(f"# Telos Daily Report - {date}")
    lines.append("")
    lines.append(f"- Run: `{run_id}`")
    lines.append(f"- Candidate items read: `{len(candidate_rows)}`")
    lines.append(f"- Report items: `{len(analyzed)}`")
    lines.append(f"- Research pack: [{md_link(docs['index_path'], RADAR_DIR)}]({md_link(docs['index_path'], RADAR_DIR)})")
    lines.append(f"- Deep research queue: [{md_link(docs['queue_path'], RADAR_DIR)}]({md_link(docs['queue_path'], RADAR_DIR)})")
    if docs.get("synthesis_path"):
        lines.append(f"- Daily synthesis: [{md_link(docs['synthesis_path'], RADAR_DIR)}]({md_link(docs['synthesis_path'], RADAR_DIR)})")
    if llm_enabled:
        prefilter_config = config.get("llm_prefilter", {})
        if prefilter_config.get("enabled", False):
            lines.append(
                f"- LLM prefilter: `{prefilter_config.get('model')}` "
                f"batch `{prefilter_config.get('batch_size')}`, pool `{prefilter_config.get('max_items')}`, "
                f"thinking `{bool(prefilter_config.get('thinking', False))}`"
            )
        lines.append(f"- Triage thinking: `{bool(llm_config.get('triage_thinking', False))}`")
        lines.append(f"- Analysis thinking: `{bool(llm_config.get('analysis_thinking', False))}`")
    mode = "feed scan + full-page fetch + extractive notes"
    if llm_enabled:
        mode += f" + local Ollama analysis ({llm_config.get('model')})"
    if triage_enabled:
        mode += " + local LLM relevance triage"
    lines.append(f"- Mode: {mode}")
    lines.append("")

    lines.append("## Executive View")
    lines.append("")
    if not analyzed:
        lines.append("No high-scoring signals crossed the report threshold today.")
    else:
        for item in analyzed:
            row = item["row"]
            topic_labels = ", ".join(topic["label"] for topic in item["topics"])
            article_path = article_paths[row["id"]]
            article_link = md_link(article_path, RADAR_DIR)
            lines.append(
                f"- **[{row['title']}]({article_link})** "
                f"({row['source_name']}, priority {final_priority_score(item)}/100, relevance {item_relevance(item)}/100, rule score {row['score']}): "
                f"{topic_labels or 'Unclassified'}"
            )
    lines.append("")

    lines.append("## Signals")
    lines.append("")
    if not analyzed:
        lines.append("- None")
    for item in analyzed:
        row = item["row"]
        topic_labels = ", ".join(topic["label"] for topic in item["topics"])
        lines.append(f"### {row['title']}")
        lines.append("")
        lines.append(f"- Source: {row['source_name']}")
        lines.append(f"- Final priority: `{final_priority_score(item)}/100`")
        lines.append(f"- Local relevance: `{item_relevance(item)}/100`")
        lines.append(f"- Rule score: `{row['score']}`")
        if row["published_at"]:
            lines.append(f"- Published: `{row['published_at']}`")
        if topic_labels:
            lines.append(f"- Topics: {topic_labels}")
        if item["keywords"]:
            lines.append(f"- Keyword hits: {', '.join(item['keywords'][:12])}")
        if item["claims"]:
            lines.append(f"- Claim touchpoints: {', '.join(item['claims'])}")
        lines.append(f"- URL: {row['url']}")
        lines.append(f"- Article dossier: [{md_link(article_paths[row['id']], RADAR_DIR)}]({md_link(article_paths[row['id']], RADAR_DIR)})")
        if item.get("prefilter"):
            pref = item["prefilter"]
            lines.append(f"- Prefilter: `{pref['score']}/100` {pref['category']} - {pref['reason']}")
        lines.append(f"- Fetch status: `{item['article_status']}`")
        if item.get("triage"):
            triage = item["triage"]
            lines.append(f"- Triage: `{item_relevance(item)}/100` ({triage['decision']})")
        if item["article_error"]:
            lines.append(f"- Fetch error: {item['article_error']}")
        lines.append("")
        lines.append("**Why it matters**")
        lines.append("")
        lines.append(why_it_matters(item["topics"], item["claims"]))
        lines.append("")
        if item.get("llm_analysis"):
            llm_analysis = item["llm_analysis"]
            lines.append("**Local model analysis**")
            lines.append("")
            lines.append(llm_analysis["analysis"] if llm_analysis["status"] == "ok" else f"LLM analysis unavailable: {llm_analysis['error']}")
            lines.append("")
        lines.append("**Extractive notes**")
        lines.append("")
        if item["sentences"]:
            for sentence in item["sentences"]:
                lines.append(f"- {sentence}")
        elif row["summary"]:
            lines.append(f"- {clip(row['summary'], 350)}")
        else:
            lines.append("- No extractable article text.")
        lines.append("")
        lines.append("**Telos action**")
        lines.append("")
        if item["claims"]:
            lines.append("- Candidate for manual review before adding as evidence to linked claims.")
        else:
            lines.append("- Keep as weak signal unless it repeats or links to a tracked claim.")
        lines.append("")

    lines.append("## Source Health")
    lines.append("")
    if failures:
        for failure in failures:
            lines.append(f"- {failure['source_name']}: {failure['error']}")
    else:
        lines.append("- All configured sources fetched successfully.")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def rows_for_report(con: sqlite3.Connection, config: dict[str, Any]) -> list[sqlite3.Row]:
    max_items = int(config.get("max_report_items", 8))
    since = (utc_now() - dt.timedelta(hours=int(config.get("lookback_hours", 36)))).isoformat()
    return con.execute(
        """
        SELECT *
        FROM radar_items
        WHERE last_seen_at >= ? AND (published_at IS NULL OR published_at >= ?) AND score >= ?
        ORDER BY score DESC, published_at DESC, first_seen_at DESC
        LIMIT ?
        """,
        (since, since, int(config.get("min_score", 6)), max_items),
    ).fetchall()


def rows_for_report_candidates(
    con: sqlite3.Connection,
    config: dict[str, Any],
    use_llm: bool = True,
) -> list[sqlite3.Row]:
    max_items = int(config.get("max_report_candidates", config.get("max_report_items", 8)))
    prefilter_config = config.get("llm_prefilter", {})
    if use_llm and prefilter_config.get("enabled", False):
        pool = rows_for_prefilter_pool(con, config)
        prefilter_scores = get_or_create_llm_prefilter_scores(con, pool, config)
        min_model_score = int(prefilter_config.get("min_model_score", 55))
        selected = []
        for row in pool:
            score = prefilter_scores.get(row["id"])
            if not score or score.get("status") != "ok":
                continue
            if not score.get("should_read_full_article"):
                continue
            if int(score.get("score", 0)) < min_model_score:
                continue
            selected.append(row)
        selected.sort(
            key=lambda row: (
                int(prefilter_scores[row["id"]]["score"]),
                int(row["score"]),
                row["published_at"] or "",
            ),
            reverse=True,
        )
        if len(selected) < max_items:
            selected_ids = {row["id"] for row in selected}
            for row in rows_for_rule_candidates(con, config, max_items * 2):
                if row["id"] not in selected_ids:
                    selected.append(row)
                    selected_ids.add(row["id"])
                if len(selected) >= max_items:
                    break
        return selected[:max_items]

    return rows_for_rule_candidates(con, config, max_items)


def rows_for_prefilter_pool(con: sqlite3.Connection, config: dict[str, Any]) -> list[sqlite3.Row]:
    prefilter_config = config.get("llm_prefilter", {})
    max_items = int(prefilter_config.get("max_items", 500))
    min_rule_score = int(prefilter_config.get("min_rule_score", config.get("storage_min_score", 2)))
    return rows_for_rule_candidates(con, {**config, "min_score": min_rule_score}, max_items)


def rows_for_rule_candidates(con: sqlite3.Connection, config: dict[str, Any], max_items: int) -> list[sqlite3.Row]:
    since = (utc_now() - dt.timedelta(hours=int(config.get("lookback_hours", 36)))).isoformat()
    return con.execute(
        """
        SELECT *
        FROM radar_items
        WHERE last_seen_at >= ? AND (published_at IS NULL OR published_at >= ?) AND score >= ?
        ORDER BY score DESC, published_at DESC, first_seen_at DESC
        LIMIT ?
        """,
        (since, since, int(config.get("min_score", 6)), int(max_items)),
    ).fetchall()


def get_or_create_llm_prefilter_scores(
    con: sqlite3.Connection,
    rows: list[sqlite3.Row],
    config: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    prefilter_config = config.get("llm_prefilter", {})
    model = str(prefilter_config.get("model", "qwen3.5:9b"))
    thinking = bool(prefilter_config.get("thinking", False))
    batch_size = int(prefilter_config.get("batch_size", 16))
    item_inputs: dict[str, dict[str, str]] = {}
    results: dict[str, dict[str, Any]] = {}
    uncached: list[sqlite3.Row] = []

    for index, row in enumerate(rows):
        item_text = build_prefilter_item_text(con, row, config, index)
        prompt_hash = hashlib.sha256(f"prefilter_v3_en_release\nthinking={thinking}\n{item_text}".encode("utf-8")).hexdigest()[:24]
        prefilter_id = stable_id("prefilter", row["id"], model, f"thinking={thinking}", prompt_hash)
        item_inputs[row["id"]] = {
            "text": item_text,
            "prompt_hash": prompt_hash,
            "prefilter_id": prefilter_id,
        }
        cached = con.execute(
            """
            SELECT score, category, should_read_full_article, reason, status, error
            FROM radar_llm_prefilter
            WHERE id = ? AND status = 'ok'
            """,
            (prefilter_id,),
        ).fetchone()
        if cached:
            results[row["id"]] = {
                "score": int(cached["score"]),
                "category": cached["category"],
                "should_read_full_article": bool(cached["should_read_full_article"]),
                "reason": cached["reason"],
                "status": cached["status"],
                "error": cached["error"] or "",
            }
        else:
            uncached.append(row)

    for start in range(0, len(uncached), batch_size):
        batch = uncached[start : start + batch_size]
        prompt = build_prefilter_batch_prompt(batch, item_inputs)
        try:
            raw = call_ollama(
                model=model,
                prompt=prompt,
                timeout=int(prefilter_config.get("timeout_seconds", 900)),
                temperature=float(prefilter_config.get("temperature", 0.0)),
                num_ctx=int(prefilter_config.get("num_ctx", 8192)),
                num_predict=int(prefilter_config.get("num_predict", 2600)),
                thinking=thinking,
            )
            parsed = parse_prefilter_response(raw)
            by_id = {str(item.get("id")): item for item in parsed}
            for row in batch:
                local = by_id.get(row["id"])
                if not local:
                    store_prefilter_result(con, row, model, item_inputs[row["id"]], 0, "error", False, "", "error", "Missing item in batch response")
                    results[row["id"]] = {"score": 0, "category": "error", "should_read_full_article": False, "reason": "", "status": "error", "error": "Missing item in batch response"}
                    continue
                score = max(0, min(100, int(local.get("score", 0))))
                category = clean_text(str(local.get("category", "unknown")))[:80] or "unknown"
                should_read = bool(local.get("should_read_full_article", score >= 55))
                reason = clean_text(str(local.get("reason", "")))[:500]
                store_prefilter_result(con, row, model, item_inputs[row["id"]], score, category, should_read, reason, "ok", None)
                results[row["id"]] = {
                    "score": score,
                    "category": category,
                    "should_read_full_article": should_read,
                    "reason": reason,
                    "status": "ok",
                    "error": "",
                }
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError, json.JSONDecodeError) as exc:
            for row in batch:
                store_prefilter_result(con, row, model, item_inputs[row["id"]], 0, "error", False, "", "error", str(exc))
                results[row["id"]] = {"score": 0, "category": "error", "should_read_full_article": False, "reason": "", "status": "error", "error": str(exc)}

    return results


def build_prefilter_item_text(
    con: sqlite3.Connection,
    row: sqlite3.Row,
    config: dict[str, Any],
    index: int,
) -> str:
    prefilter_config = config.get("llm_prefilter", {})
    snippet_chars = int(prefilter_config.get("snippet_chars", 700))
    topics = ", ".join(topic["label"] for topic in json.loads(row["topic_hits"])) or "None"
    keywords = ", ".join(json.loads(row["keyword_hits"])[:14]) or "None"
    claims = ", ".join(json.loads(row["claim_ids"])[:8]) or "None"
    snippet = clip(row["summary"], snippet_chars)
    first_paragraph = ""
    if prefilter_config.get("include_first_paragraph", True) and index < int(prefilter_config.get("first_paragraph_max_items", 250)):
        article_text, _, _ = get_or_fetch_article_text(
            con=con,
            row=row,
            max_chars=1500,
            timeout=25,
        )
        first_paragraph = clip(first_nonempty_paragraph(article_text), snippet_chars)
    return textwrap.dedent(
        f"""
        id: {row['id']}
        source: {row['source_name']}
        rule_score: {row['score']}
        published_at: {row['published_at'] or 'unknown'}
        title: {row['title']}
        url: {row['url']}
        topics: {topics}
        keyword_hits: {keywords}
        claim_touchpoints: {claims}
        snippet: {snippet or 'None'}
        first_paragraph: {first_paragraph or 'None'}
        """
    ).strip()


def first_nonempty_paragraph(text: str) -> str:
    for part in re.split(r"\n{2,}|(?<=[.!?])\s+(?=[A-Z])", clean_text(text)):
        part = part.strip()
        if len(part) >= 80:
            return part
    return clean_text(text)[:800]


def build_prefilter_batch_prompt(rows: list[sqlite3.Row], item_inputs: dict[str, dict[str, str]]) -> str:
    items = "\n\n---\n\n".join(item_inputs[row["id"]]["text"] for row in rows)
    return textwrap.dedent(
        f"""
        You are the fast first-pass Telos relevance filter.
        Score each signal using only the title, source, snippet and first paragraph.
        Work in English only. Do not write German. Return no thinking trace and no explanation outside JSON.

        Telos is looking for early, important signals about:
        - Frontier AI, model capabilities, task horizon, benchmarks
        - Major model releases from OpenAI, Anthropic, Google DeepMind, Meta, xAI, Mistral and similar labs
        - Agents, Memory, Tool Use, Orchestration, Workflows, Security
        - Robotics, World Models, Physical AI, Humanoids, Drones
        - Compute, Energy, Chips, Data Centers, Inference, HPC
        - AI for Science, automated labs, research agents
        - Useful data advantage: workflow data, physical data, first-person data
        - Crypto only when real agent, compute, or payment utility is visible

        Scoring rules:
        95-100 = major frontier model release or benchmark shift from a leading lab; always read in full.
        90-100 = very important, likely a top dossier.
        75-89 = important, should be read in full.
        55-74 = relevant, read in full if capacity allows.
        35-54 = weak or only indirectly relevant.
        0-34 = noise, marketing, event, tutorial, coupon, or no substance.

        Return exactly one JSON array. No Markdown fences.
        Schema per item:
        {{
          "id": "...",
          "score": 0-100,
          "category": "frontier_model_release|frontier_ai|agents_memory|robotics_world_models|compute_energy_chips|ai_science_rsi|useful_data|crypto_agent_infra|security|business_market|noise",
          "should_read_full_article": true/false,
          "reason": "short English reason"
        }}

        Items:
        {items}
        """
    ).strip()


def parse_prefilter_response(text: str) -> list[dict[str, Any]]:
    text = strip_thinking(text).strip()
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end < start:
        raise ValueError(f"Missing JSON array in prefilter response: {text[:300]}")
    return json.loads(text[start : end + 1])


def store_prefilter_result(
    con: sqlite3.Connection,
    row: sqlite3.Row,
    model: str,
    item_input: dict[str, str],
    score: int,
    category: str,
    should_read: bool,
    reason: str,
    status: str,
    error: str | None,
) -> None:
    con.execute(
        """
        INSERT INTO radar_llm_prefilter(
            id, item_id, created_at, model, prompt_hash, score, category,
            should_read_full_article, reason, status, error
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            created_at = excluded.created_at,
            score = excluded.score,
            category = excluded.category,
            should_read_full_article = excluded.should_read_full_article,
            reason = excluded.reason,
            status = excluded.status,
            error = excluded.error
        """,
        (
            item_input["prefilter_id"],
            row["id"],
            iso_now(),
            model,
            item_input["prompt_hash"],
            score,
            category,
            1 if should_read else 0,
            reason,
            status,
            error,
        ),
    )
    con.commit()


def get_latest_prefilter_result(con: sqlite3.Connection, item_id: str) -> dict[str, Any] | None:
    row = con.execute(
        """
        SELECT score, category, should_read_full_article, reason, status, error
        FROM radar_llm_prefilter
        WHERE item_id = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (item_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "score": int(row["score"]),
        "category": row["category"],
        "should_read_full_article": bool(row["should_read_full_article"]),
        "reason": row["reason"],
        "status": row["status"],
        "error": row["error"] or "",
    }


def filter_and_rank_candidates(
    candidates: list[dict[str, Any]],
    config: dict[str, Any],
    llm_config: dict[str, Any],
    triage_enabled: bool,
) -> list[dict[str, Any]]:
    min_relevance = int(llm_config.get("min_relevance", 60))

    filtered = []
    for candidate in candidates:
        triage = candidate.get("triage")
        if triage_enabled and triage and triage.get("status") == "ok":
            if normalize_relevance(triage.get("relevance", 0)) < min_relevance:
                continue
            if triage.get("decision") == "skip":
                continue
        filtered.append(candidate)

    filtered.sort(
        key=lambda item: (
            final_priority_score(item),
            item_relevance(item),
            prefilter_score(item),
            item["row"]["published_at"] or "",
        ),
        reverse=True,
    )
    return filtered


def write_research_documents(
    con: sqlite3.Connection,
    analyzed: list[dict[str, Any]],
    date: str,
    run_id: str,
    config: dict[str, Any],
    llm_enabled: bool,
    triage_enabled: bool,
) -> dict[str, Any]:
    day_dir = RADAR_DIR / date
    article_dir = day_dir / "articles"
    topic_dir = day_dir / "topics"
    article_dir.mkdir(parents=True, exist_ok=True)
    topic_dir.mkdir(parents=True, exist_ok=True)
    clear_generated_research_pack(day_dir, article_dir, topic_dir)

    article_paths: dict[str, Path] = {}
    topic_items: dict[str, list[dict[str, Any]]] = {}

    for index, item in enumerate(analyzed, start=1):
        row = item["row"]
        relevance = item_relevance(item)
        priority = final_priority_score(item)
        filename = f"{index:02d}-p{priority:03d}-r{relevance:03d}-s{int(row['score']):03d}-{slugify(row['title'])}.md"
        path = article_dir / filename
        article_paths[row["id"]] = path
        path.write_text(render_article_document(item, date, run_id, index), encoding="utf-8")

        if not item["topics"]:
            topic_items.setdefault("unclassified", []).append(item)
        for topic in item["topics"]:
            topic_items.setdefault(topic["label"], []).append(item)

    topic_paths: dict[str, Path] = {}
    for label, items in sorted(topic_items.items()):
        sorted_items = sorted(
            items,
            key=lambda entry: (final_priority_score(entry), item_relevance(entry), prefilter_score(entry), entry["row"]["published_at"] or ""),
            reverse=True,
        )
        path = topic_dir / f"{slugify(label)}.md"
        topic_paths[label] = path
        path.write_text(render_topic_document(label, sorted_items, article_paths, date, run_id), encoding="utf-8")

    queue_path = day_dir / "deep-research-queue.md"
    queue_path.write_text(render_deep_research_queue(analyzed, article_paths, date, run_id), encoding="utf-8")

    belief_queue_path = day_dir / "belief-update-queue.md"
    belief_queue_path.write_text(render_belief_update_queue(analyzed, article_paths, date, run_id), encoding="utf-8")

    synthesis_path = day_dir / "daily-synthesis.md"
    synthesis_result = None
    synthesis_config = config.get("daily_synthesis", {})
    if llm_enabled and synthesis_config.get("enabled", False):
        synthesis_result = get_or_create_daily_synthesis(
            con=con,
            analyzed=analyzed,
            article_paths=article_paths,
            date=date,
            run_id=run_id,
            synthesis_config=synthesis_config,
        )
        synthesis_path.write_text(synthesis_result["synthesis"], encoding="utf-8")
    else:
        synthesis_path.write_text(
            f"# Daily Synthesis - {date}\n\nDaily synthesis is disabled for this run.\n",
            encoding="utf-8",
        )

    index_path = day_dir / "index.md"
    index_path.write_text(
        render_research_index(
            analyzed=analyzed,
            article_paths=article_paths,
            topic_paths=topic_paths,
            queue_path=queue_path,
            belief_queue_path=belief_queue_path,
            synthesis_path=synthesis_path,
            date=date,
            run_id=run_id,
            config=config,
            llm_enabled=llm_enabled,
            triage_enabled=triage_enabled,
        ),
        encoding="utf-8",
    )

    return {
        "day_dir": day_dir,
        "index_path": index_path,
        "article_paths": article_paths,
        "topic_paths": topic_paths,
        "queue_path": queue_path,
        "belief_queue_path": belief_queue_path,
        "synthesis_path": synthesis_path,
        "synthesis_result": synthesis_result,
    }


def clear_generated_research_pack(day_dir: Path, article_dir: Path, topic_dir: Path) -> None:
    for directory in (article_dir, topic_dir):
        if directory.exists():
            for path in directory.glob("*.md"):
                path.unlink()
    for filename in ("index.md", "deep-research-queue.md", "belief-update-queue.md", "daily-synthesis.md"):
        path = day_dir / filename
        if path.exists():
            path.unlink()


def render_article_document(item: dict[str, Any], date: str, run_id: str, rank: int) -> str:
    row = item["row"]
    topic_labels = ", ".join(topic["label"] for topic in item["topics"]) or "Unclassified"
    relevance = item_relevance(item)
    lines: list[str] = []
    lines.append(f"# {row['title']}")
    lines.append("")
    lines.append(f"- Date: `{date}`")
    lines.append(f"- Run: `{run_id}`")
    lines.append(f"- Rank: `{rank}`")
    lines.append(f"- Final priority: `{final_priority_score(item)}/100`")
    lines.append(f"- Local relevance: `{relevance}/100`")
    lines.append(f"- Rule score: `{row['score']}`")
    lines.append(f"- Source: {row['source_name']}")
    if row["published_at"]:
        lines.append(f"- Published: `{row['published_at']}`")
    lines.append(f"- URL: {row['url']}")
    lines.append(f"- Fetch status: `{item['article_status']}`")
    lines.append(f"- Topics: {topic_labels}")
    if item["keywords"]:
        lines.append(f"- Keyword hits: {', '.join(item['keywords'][:16])}")
    if item["claims"]:
        lines.append(f"- Claim touchpoints: {', '.join(item['claims'])}")
    if item.get("triage"):
        triage = item["triage"]
        lines.append(f"- Local relevance note: `{item_relevance(item)}/100` {triage['decision']} - {triage['reason']}")
    if item.get("prefilter"):
        pref = item["prefilter"]
        lines.append(f"- Prefilter: `{pref['score']}/100` {pref['category']} - {pref['reason']}")
    if item["article_error"]:
        lines.append(f"- Fetch error: {item['article_error']}")
    lines.append("")

    lines.append("## Why It Matters")
    lines.append("")
    lines.append(why_it_matters(item["topics"], item["claims"]))
    lines.append("")

    lines.append("## Local Model Analysis")
    lines.append("")
    if item.get("llm_analysis"):
        llm_analysis = item["llm_analysis"]
        lines.append(llm_analysis["analysis"] if llm_analysis["status"] == "ok" else f"LLM analysis unavailable: {llm_analysis['error']}")
    else:
        lines.append("No local LLM analysis was generated for this item.")
    lines.append("")

    lines.append("## Extractive Notes")
    lines.append("")
    if item["sentences"]:
        for sentence in item["sentences"]:
            lines.append(f"- {sentence}")
    elif row["summary"]:
        lines.append(f"- {clip(row['summary'], 500)}")
    else:
        lines.append("- No extractable article text.")
    lines.append("")

    lines.append("## Further Browser Research")
    lines.append("")
    for query in research_queries(item):
        lines.append(f"- `{query}`")
    lines.append("")

    lines.append("## Telos Action")
    lines.append("")
    if item["claims"]:
        lines.append("- Manual review candidate before adding as evidence to linked claims.")
    else:
        lines.append("- Keep as weak signal unless it repeats or connects to a tracked claim.")
    lines.append("- Check original source before changing belief confidence.")
    lines.append("")
    return "\n".join(lines)


def render_topic_document(
    label: str,
    items: list[dict[str, Any]],
    article_paths: dict[str, Path],
    date: str,
    run_id: str,
) -> str:
    lines: list[str] = []
    lines.append(f"# {label} - {date}")
    lines.append("")
    lines.append(f"- Run: `{run_id}`")
    lines.append(f"- Items: `{len(items)}`")
    lines.append("- Sorted by final priority, local relevance, prefilter score, then recency.")
    lines.append("")
    for index, item in enumerate(items, start=1):
        row = item["row"]
        article_path = article_paths[row["id"]]
        relevance = item_relevance(item)
        triage_reason = ""
        if item.get("triage"):
            triage_reason = f" - {item['triage']['reason']}"
        lines.append(f"## {index}. {row['title']}")
        lines.append("")
        lines.append(f"- Final priority: `{final_priority_score(item)}/100`")
        lines.append(f"- Local relevance: `{relevance}/100`")
        lines.append(f"- Rule score: `{row['score']}`")
        lines.append(f"- Source: {row['source_name']}")
        lines.append(f"- Article dossier: [{article_path.name}](../articles/{article_path.name})")
        lines.append(f"- URL: {row['url']}")
        if item["claims"]:
            lines.append(f"- Claim touchpoints: {', '.join(item['claims'])}")
        if triage_reason:
            lines.append(f"- Local reason:{triage_reason}")
        lines.append("")
    return "\n".join(lines)


def render_deep_research_queue(
    analyzed: list[dict[str, Any]],
    article_paths: dict[str, Path],
    date: str,
    run_id: str,
) -> str:
    sorted_items = sorted(
        analyzed,
        key=lambda item: (final_priority_score(item), item_relevance(item), prefilter_score(item), item["row"]["published_at"] or ""),
        reverse=True,
    )
    lines: list[str] = []
    lines.append(f"# Deep Research Queue - {date}")
    lines.append("")
    lines.append(f"- Run: `{run_id}`")
    lines.append("- Use this for follow-up browser searches before promoting an item to Telos evidence.")
    lines.append("")
    for index, item in enumerate(sorted_items, start=1):
        row = item["row"]
        article_path = article_paths[row["id"]]
        lines.append(f"## {index}. {row['title']}")
        lines.append("")
        lines.append(f"- Final priority: `{final_priority_score(item)}/100`")
        lines.append(f"- Local relevance: `{item_relevance(item)}/100`")
        lines.append(f"- Rule score: `{row['score']}`")
        lines.append(f"- Dossier: [open](articles/{article_path.name})")
        lines.append(f"- Source: {row['url']}")
        lines.append("- Search next:")
        for query in research_queries(item):
            lines.append(f"  - `{query}`")
        lines.append("")
    return "\n".join(lines)


def render_belief_update_queue(
    analyzed: list[dict[str, Any]],
    article_paths: dict[str, Path],
    date: str,
    run_id: str,
) -> str:
    claim_items: dict[str, list[dict[str, Any]]] = {}
    unlinked: list[dict[str, Any]] = []
    for item in analyzed:
        if item["claims"]:
            for claim_id in item["claims"]:
                claim_items.setdefault(claim_id, []).append(item)
        else:
            unlinked.append(item)

    ranked_claims = sorted(
        claim_items.items(),
        key=lambda pair: (
            max(final_priority_score(item) for item in pair[1]),
            max(item_relevance(item) for item in pair[1]),
            sum(final_priority_score(item) for item in pair[1]),
            len(pair[1]),
        ),
        reverse=True,
    )

    lines: list[str] = []
    lines.append(f"# Belief Update Queue - {date}")
    lines.append("")
    lines.append(f"- Run: `{run_id}`")
    lines.append("- Purpose: review high-priority dossier signals before promoting them to Telos evidence.")
    lines.append("- Radar items are not beliefs. Only reviewed source claims should update confidence.")
    lines.append("")
    lines.append("## Review Priority")
    lines.append("")
    if not ranked_claims:
        lines.append("- No linked claims in today's dossiers.")
    for index, (claim_id, items) in enumerate(ranked_claims, start=1):
        sorted_items = sorted(
            items,
            key=lambda item: (final_priority_score(item), item_relevance(item), prefilter_score(item), item["row"]["published_at"] or ""),
            reverse=True,
        )
        top = sorted_items[0]
        suggested = suggested_belief_effect(sorted_items)
        lines.append(f"### {index}. `{claim_id}`")
        lines.append("")
        lines.append(f"- Suggested effect: `{suggested['effect']}`")
        lines.append(f"- Review strength: `{suggested['strength']}`")
        lines.append(f"- Reason: {suggested['reason']}")
        lines.append(f"- Items linked: `{len(sorted_items)}`")
        lines.append(f"- Highest priority: `{final_priority_score(top)}/100`")
        lines.append(f"- Highest local relevance: `{item_relevance(top)}/100`")
        lines.append("")
        lines.append("#### Evidence Candidates")
        lines.append("")
        for item in sorted_items[:6]:
            row = item["row"]
            path = article_paths[row["id"]]
            lines.append(f"- [{row['title']}](articles/{path.name})")
            lines.append(f"  - Source: {row['source_name']}")
            lines.append(f"  - Final priority: `{final_priority_score(item)}/100`; relevance `{item_relevance(item)}/100`; rule score `{row['score']}`")
            lines.append(f"  - Suggested polarity: `{suggested_item_polarity(item)}`")
            if item.get("prefilter"):
                lines.append(f"  - Prefilter: {item['prefilter']['score']}/100 {item['prefilter']['category']} - {item['prefilter']['reason']}")
            if item.get("triage"):
                lines.append(f"  - Triage: {item_relevance(item)}/100 {item['triage']['decision']} - {item['triage']['reason']}")
            if item.get("llm_analysis") and item["llm_analysis"]["status"] == "ok":
                lines.append(f"  - Local analysis: {clip(item['llm_analysis']['analysis'], 360)}")
            lines.append("")
        lines.append("#### Before Promotion")
        lines.append("")
        for check in belief_update_checks(sorted_items):
            lines.append(f"- {check}")
        lines.append("")

    lines.append("## Unlinked High-Relevance Items")
    lines.append("")
    unlinked_sorted = sorted(
        unlinked,
        key=lambda item: (final_priority_score(item), item_relevance(item), prefilter_score(item), item["row"]["published_at"] or ""),
        reverse=True,
    )
    if not unlinked_sorted:
        lines.append("- None")
    for item in unlinked_sorted[:10]:
        row = item["row"]
        path = article_paths[row["id"]]
        lines.append(f"- [{row['title']}](articles/{path.name}) - priority `{final_priority_score(item)}/100`, relevance `{item_relevance(item)}/100`, rule score `{row['score']}`")
    lines.append("")
    return "\n".join(lines)


def suggested_belief_effect(items: list[dict[str, Any]]) -> dict[str, str]:
    polarities = [suggested_item_polarity(item) for item in items]
    for_count = polarities.count("for")
    against_count = polarities.count("against")
    uncertain_count = polarities.count("uncertain")
    max_relevance = max(item_relevance(item) for item in items)
    if for_count and not against_count:
        effect = "likely_for"
    elif against_count and not for_count:
        effect = "likely_against"
    elif for_count and against_count:
        effect = "mixed"
    else:
        effect = "uncertain"

    strength = "manual_review_required"

    reason = f"{for_count} for, {against_count} against, {uncertain_count} uncertain across {len(items)} linked dossier(s)."
    return {"effect": effect, "strength": strength, "reason": reason}


def suggested_item_polarity(item: dict[str, Any]) -> str:
    # Claim links are produced by topic and keyword routing. Without comparing
    # the article against the exact claim wording, lexical sentiment is not a
    # defensible evidence polarity.
    return "uncertain"


def belief_update_checks(items: list[dict[str, Any]]) -> list[str]:
    labels = {topic["label"] for item in items for topic in item["topics"]}
    checks = [
        "Open the original source before adding evidence.",
        "Separate source claims from Telos interpretation.",
        "Add evidence with explicit reliability and polarity only after review.",
    ]
    if "Frontier AI" in labels:
        checks.append("For model releases: compare against previous model benchmarks, task horizon, tool calls, token use, cost, safety routing, and deployment limits.")
    if "Agents / Memory" in labels:
        checks.append("For agent claims: check whether the result shows real task completion, not only demo behavior or benchmark framing.")
    if "RSI / AI for Science" in labels:
        checks.append("For AI-for-Science/RSI: do not raise RSI confidence without closed-loop research, experiment, or model-improvement evidence.")
    if "Compute / Energy / Chips" in labels:
        checks.append("For compute claims: distinguish demand narrative from measurable capacity, utilization, cost, power, and supply-chain evidence.")
    if "Robotics / Physical AI" in labels:
        checks.append("For robotics claims: separate simulation/benchmark progress from deployed real-world performance.")
    return checks


def render_research_index(
    analyzed: list[dict[str, Any]],
    article_paths: dict[str, Path],
    topic_paths: dict[str, Path],
    queue_path: Path,
    belief_queue_path: Path,
    synthesis_path: Path,
    date: str,
    run_id: str,
    config: dict[str, Any],
    llm_enabled: bool,
    triage_enabled: bool,
) -> str:
    lines: list[str] = []
    lines.append(f"# Telos Research Pack - {date}")
    lines.append("")
    lines.append(f"- Run: `{run_id}`")
    lines.append(f"- Important article dossiers: `{len(analyzed)}`")
    lines.append(f"- Deep candidates read: `{config.get('max_report_candidates')}`")
    lines.append(f"- Local LLM: `{config.get('llm_report', {}).get('model') if llm_enabled else 'disabled'}`")
    lines.append(f"- LLM triage: `{triage_enabled}`")
    if llm_enabled:
        llm_config = config.get("llm_report", {})
        lines.append(f"- Triage thinking: `{bool(llm_config.get('triage_thinking', False))}`")
        lines.append(f"- Analysis thinking: `{bool(llm_config.get('analysis_thinking', False))}`")
    lines.append(f"- Deep research queue: [{queue_path.name}]({queue_path.name})")
    lines.append(f"- Belief update queue: [{belief_queue_path.name}]({belief_queue_path.name})")
    lines.append(f"- Daily synthesis: [{synthesis_path.name}]({synthesis_path.name})")
    lines.append("")
    lines.append("## Topic Indexes")
    lines.append("")
    if topic_paths:
        for label, path in sorted(topic_paths.items()):
            lines.append(f"- [{label}](topics/{path.name})")
    else:
        lines.append("- None")
    lines.append("")
    lines.append("## Article Dossiers")
    lines.append("")
    for index, item in enumerate(analyzed, start=1):
        row = item["row"]
        article_path = article_paths[row["id"]]
        topic_labels = ", ".join(topic["label"] for topic in item["topics"]) or "Unclassified"
        lines.append(
            f"- {index}. [{row['title']}](articles/{article_path.name}) "
            f"- priority `{final_priority_score(item)}/100`, relevance `{item_relevance(item)}/100`, rule score `{row['score']}`, {topic_labels}"
        )
    lines.append("")
    return "\n".join(lines)


def research_queries(item: dict[str, Any]) -> list[str]:
    row = item["row"]
    title = clean_text(row["title"])
    queries = [
        f'"{title}"',
        f'"{title}" benchmark results limitations',
    ]
    labels = {topic["label"] for topic in item["topics"]}
    if "Robotics / Physical AI" in labels:
        queries.append(f'"{title}" robot real-world evaluation')
    if "Agents / Memory" in labels:
        queries.append(f'"{title}" agent memory long horizon')
    if "RSI / AI for Science" in labels:
        queries.append(f'"{title}" AI for science reproducibility')
    if "Compute / Energy / Chips" in labels:
        queries.append(f'"{title}" compute cost latency scaling')
    if row["source_name"]:
        queries.append(f'{row["source_name"]} "{title}"')
    seen: set[str] = set()
    unique = []
    for query in queries:
        if query not in seen:
            seen.add(query)
            unique.append(query)
    return unique[:5]


def get_or_create_daily_synthesis(
    con: sqlite3.Connection,
    analyzed: list[dict[str, Any]],
    article_paths: dict[str, Path],
    date: str,
    run_id: str,
    synthesis_config: dict[str, Any],
) -> dict[str, str]:
    model = str(synthesis_config.get("model", "qwen3.5:9b"))
    thinking = bool(synthesis_config.get("thinking", True))
    prompt, included_count = build_daily_synthesis_prompt(
        analyzed=analyzed,
        article_paths=article_paths,
        date=date,
        max_dossiers=int(synthesis_config.get("max_dossiers", 25)),
        max_input_chars=int(synthesis_config.get("max_input_chars", 90000)),
    )
    prompt_hash = hashlib.sha256(f"synthesis_v12_quarantined_thesis_impact\nthinking={thinking}\n{prompt}".encode("utf-8")).hexdigest()[:24]
    synthesis_id = stable_id("daily_synthesis", date, model, f"thinking={thinking}", prompt_hash)

    cached = con.execute(
        """
        SELECT synthesis, status, error
        FROM radar_daily_syntheses
        WHERE id = ? AND status = 'ok'
        """,
        (synthesis_id,),
    ).fetchone()
    if cached and valid_daily_synthesis(str(cached["synthesis"] or "")):
        return {
            "synthesis": cached["synthesis"],
            "status": cached["status"],
            "error": cached["error"] or "",
        }

    try:
        raw_body = call_ollama(
            model=model,
            prompt=prompt,
            timeout=int(synthesis_config.get("timeout_seconds", 1800)),
            temperature=float(synthesis_config.get("temperature", 0.2)),
            num_ctx=int(synthesis_config.get("num_ctx", 32768)),
            num_predict=int(synthesis_config.get("num_predict", 2200)),
            thinking=thinking,
        )
        body = extract_synthesis_core(raw_body)
        critic_prompt = textwrap.dedent(
            f"""
            You are the final grounding critic for a Telos daily synthesis.
            Rewrite the draft using only the dossier context embedded in the
            original task. Preserve the required Markdown headings.

            Mandatory corrections:
            - Attribute secondary-source claims as reported and do not present
              exact legal scope, causal triggers, or benchmark validity as verified.
            - Replace hype terms such as breakthrough, proves, confirms, definitive,
              ends an era, or severs global access with precise scoped language.
            - Keep model capability separate from access policy, regulation,
              deployment, adoption, and market movement.
            - A benchmark result applies only to its tested task and baselines.
            - SWE-Explore measures code-region localization, not patch execution;
              do not describe its target lines as lines required for fixes.
            - Do not connect simulation/video results to robotics deployment unless
              the supplied source directly tests robotics.
            - Do not infer support for a Telos claim from a linked claim ID.
            - Never say an item validates or confirms a broad Telos thesis. Use
              scoped language about what the reported observation may support.
            - Access policy or regulation must not be listed as weakening or
              strengthening the technical capability curve.
            - Preserve qualifiers including reported, claimed, up to, benchmark-only,
              preview, and limited access.
            - Avoid hype adjectives such as massive, sharp, critical, major, and
              breakthrough unless the source scope itself justifies them.
            - Every required section must contain substantive text. Under Thesis
              Impact, give at least one grounded item under Stronger,
              Weaker/uncertain, and New open questions. If no claim-level update is
              justified, say so explicitly rather than leaving the subsection empty.

            Return only the corrected synthesis beginning with:
            # Daily Synthesis Core

            ORIGINAL TASK AND DOSSIERS:
            {prompt}

            DRAFT TO CORRECT:
            {body}
            """
        ).strip()
        criticised = call_ollama(
            model=model,
            prompt=critic_prompt,
            timeout=int(synthesis_config.get("timeout_seconds", 1800)),
            temperature=0.0,
            num_ctx=int(synthesis_config.get("num_ctx", 32768)),
            num_predict=max(1800, int(synthesis_config.get("num_predict", 2200))),
            thinking=False,
        )
        body = extract_synthesis_core(criticised)
        if not valid_daily_synthesis(body):
            raise ValueError("Ollama synthesis omitted required sections or was too short")
        hits = synthesis_overclaim_flags(body)
        if hits:
            repair_prompt = textwrap.dedent(
                f"""
                Repair the Telos synthesis below. Return only the complete
                corrected synthesis with every required heading and substantive
                section. The previous grounding critic left these prohibited
                overclaims: {', '.join(hits)}.

                Apply these exact corrections without adding facts:
                - SWE-Explore measures ranked code-region localization, not patch
                  execution or lines required to implement a fix.
                - Do not use validate, confirm, or prove for broad Telos theses.
                - Access restrictions are deployment evidence and must not change
                  the technical capability-curve assessment.
                - Do not connect Mirage to physical AI or deployed robotics; the
                  supplied item concerns video-world-model generation.
                - Remove hype and keep legal/access scope attributed when the
                  underlying dossier is secondary reporting.
                - Keep every numeric and qualitative claim inside the scope of
                  the supplied dossier task.

                ORIGINAL TASK AND DOSSIERS:
                {prompt}

                SYNTHESIS TO REPAIR:
                {body}
                """
            ).strip()
            repaired = call_ollama(
                model=model,
                prompt=repair_prompt,
                timeout=int(synthesis_config.get("timeout_seconds", 1800)),
                temperature=0.0,
                num_ctx=int(synthesis_config.get("num_ctx", 32768)),
                num_predict=max(1800, int(synthesis_config.get("num_predict", 2200))),
                thinking=False,
            )
            body = extract_synthesis_core(repaired)
            if not valid_daily_synthesis(body):
                raise ValueError("Grounding repair produced an incomplete synthesis")
            hits = synthesis_overclaim_flags(body)
            if hits:
                body = sanitize_synthesis_overclaims(body)
                if not valid_daily_synthesis(body):
                    raise ValueError("Deterministic grounding sanitizer produced an incomplete synthesis")
                hits = synthesis_overclaim_flags(body)
                if hits:
                    raise ValueError(f"Grounding sanitizer left prohibited overclaims: {', '.join(hits)}")
        synthesis = render_synthesis_document(date, run_id, model, thinking, included_count, body)
        status = "ok"
        error = None
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as exc:
        error = str(exc)
        synthesis = render_synthesis_document(
            date=date,
            run_id=run_id,
            model=model,
            thinking=thinking,
            included_count=included_count,
            body=f"Synthesis unavailable: {error}",
        )
        status = "error"

    con.execute(
        """
        INSERT INTO radar_daily_syntheses(id, date, run_id, created_at, model, prompt_hash, synthesis, status, error)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            run_id = excluded.run_id,
            created_at = excluded.created_at,
            synthesis = excluded.synthesis,
            status = excluded.status,
            error = excluded.error
        """,
        (synthesis_id, date, run_id, iso_now(), model, prompt_hash, synthesis, status, error),
    )
    con.commit()
    return {"synthesis": synthesis, "status": status, "error": error or ""}


def valid_daily_synthesis(text: str) -> bool:
    headings = (
        "## Bottom Line", "## Relevance Ranking", "## What Happened Today",
        "## Thesis Impact", "## What I Would Watch Tomorrow",
    )
    if len(text.strip()) < 800 or not all(heading in text for heading in headings):
        return False
    positions = [text.find(heading) for heading in headings]
    for index, start in enumerate(positions):
        end = positions[index + 1] if index + 1 < len(positions) else len(text)
        section = text[start + len(headings[index]):end].strip()
        minimum = 120 if headings[index] == "## Thesis Impact" else 160
        if len(section) < minimum:
            return False
    return True


def synthesis_overclaim_flags(text: str) -> list[str]:
    patterns = {
        "prove/confirm/validate thesis language": r"\b(?:proves?|confirms?|validat(?:e|es|ed|ing))\b",
        "era-ending or global-severance language": r"definitive end|ends the era|sever(?:s|ing) global",
        "non-US entity scope": r"for non-u\.s\. entities",
        "hype language": r"\bmassive (?:gain|gains|improvement|improvements)\b|capability breakthrough",
        "SWE-Explore patch-execution overreach": r"lines? (?:of code )?required (?:to implement |for )?(?:a )?fix(?:es)?",
        "access confused with capability curve": r"capability curve.{0,100}(?:weaken|strengthen).{0,140}(?:access|regulat|restrict)|(?:access|regulat|restrict).{0,140}(?:weaken|strengthen).{0,100}capability curve",
        "Mirage connected to physical AI": r"mirage.{0,800}physical ai|physical ai.{0,800}mirage",
    }
    lowered = text.lower().replace("\n", " ")
    return [label for label, pattern in patterns.items() if re.search(pattern, lowered)]


def sanitize_synthesis_overclaims(text: str) -> str:
    text = re.sub(
        r"(?is)## Thesis Impact\s*.*?(?=\n## What I Would Watch Tomorrow)",
        """## Thesis Impact
- Stronger: No broad Telos claim is automatically strengthened by this generated synthesis. Candidate links require comparison with the exact claim wording and reviewed source evidence.
- Weaker/uncertain: No technical capability claim is automatically weakened by access policy, regulation, deployment limits, or market movement. Dossier-specific limitations remain open for review.
- New open questions: Which exact claims are directly tested by primary evidence, which observations are independent, and what evidence would falsify the proposed link?
""",
        text,
    )
    replacements = (
        (r"\b(?:directly )?validat(?:e|es|ed|ing)\b", "is relevant to"),
        (r"\bconfirms?\b", "reports"),
        (r"\bproves?\b", "reports"),
        (r"\bmassive (?:gain|gains|improvement|improvements)\b", "reported gains"),
        (r"lines? (?:of code )?required (?:to implement |for )?(?:a )?fix(?:es)?", "relevant code regions"),
        (r"for physical ai", "for video-world-model generation"),
        (r"\bphysical ai\b", "video-world-model research"),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.I)
    return text


def build_daily_synthesis_prompt(
    analyzed: list[dict[str, Any]],
    article_paths: dict[str, Path],
    date: str,
    max_dossiers: int,
    max_input_chars: int,
) -> tuple[str, int]:
    chunks: list[str] = []
    used_chars = 0
    included_count = 0
    for index, item in enumerate(analyzed[:max_dossiers], start=1):
        row = item["row"]
        path = article_paths[row["id"]]
        text = compact_dossier_for_synthesis(item, path)
        header = f"\n\n===== DOSSIER {index}: {row['title']} =====\n"
        chunk = header + text
        if used_chars + len(chunk) > max_input_chars:
            remaining = max_input_chars - used_chars
            if remaining > 2000:
                chunks.append(chunk[:remaining])
                included_count += 1
            break
        chunks.append(chunk)
        included_count += 1
        used_chars += len(chunk)

    prompt = textwrap.dedent(
        f"""
        You are a new, separate Telos synthesis instance.
        You read the finished daily dossiers and produce a second-order view of the day.
        Use only information from the dossiers. Do not invent external facts.
        Work in English only. Do not write German.
        You may reason internally, but return no thinking trace, no analysis plan,
        no input summary and no <think> blocks.
        Your answer must start directly with this line:
        # Daily Synthesis Core

        Goal:
        1. Sort the signals by real strategic relevance, not just keyword score.
        2. Explain briefly what happened today in AI, robotics and compute.
        3. Mark which Telos theses were strengthened or weakened.
        4. Mark uncertainty, hype risk and open checks.
        5. If there was a major frontier model release, treat it as a top-level event: compare it to prior models/benchmarks when the dossiers contain that information, infer the capability trend, and state which Telos theses it affects.

        Grounding rules:
        - Preserve qualifiers such as "up to", "reported", "in this benchmark", and "against these baselines".
        - Do not say an item proves, confirms, solves, or ends a broad trend unless the dossiers directly establish that exact scope.
        - Separate technical capability, product availability, regulation, adoption, market prices, and long-run interpretation.
        - A restriction on model access is not evidence that the technical capability curve slowed.
        - A secondary article cannot establish exact legal scope, affected population, causal trigger, or benchmark validity; attribute it as reported and request the primary source.
        - Do not call a research result a breakthrough, critical for robotics, or a capability-curve event unless the dossier contains primary comparative evidence for that exact conclusion.
        - Do not describe a vendor-specific restriction as severing global frontier access or affecting all non-US entities unless a primary source states that scope.
        - A benchmark supports only what it directly measures; localization is not patch execution or task horizon.
        - One market move or company announcement cannot validate a broad scientific or civilizational thesis.
        - State missing primary sources, comparison baselines, and corroboration prominently.

        Output format in Markdown:
        # Daily Synthesis Core

        ## Bottom Line
        3-6 sentences, direct and concrete.

        ## Relevance Ranking
        1. Title - Relevance 0-10 - 1 sentence explaining why.

        ## What Happened Today
        A short report on the most important movements of the day.

        ## Thesis Impact
        - Stronger:
        - Weaker/uncertain:
        - New open questions:

        ## What I Would Watch Tomorrow
        5-10 concrete watchpoints.

        Date: {date}
        Dossiers in context: {included_count}

        Dossiers:
        {''.join(chunks)}
        """
    ).strip()
    return prompt, included_count


def compact_dossier_for_synthesis(item: dict[str, Any], path: Path) -> str:
    row = item["row"]
    topics = ", ".join(topic["label"] for topic in item["topics"]) or "Unclassified"
    lines: list[str] = []
    lines.append(f"Title: {row['title']}")
    lines.append(f"Dossier file: {path.name}")
    lines.append(f"Source: {row['source_name']}")
    lines.append(f"URL: {row['url']}")
    lines.append(f"Final priority: {final_priority_score(item)}/100")
    lines.append(f"Local relevance: {item_relevance(item)}/100")
    lines.append(f"Rule score: {row['score']}")
    lines.append(f"Topics: {topics}")
    if item["keywords"]:
        lines.append(f"Keyword hits: {', '.join(item['keywords'][:16])}")
    if item["claims"]:
        lines.append(f"Claim touchpoints: {', '.join(item['claims'])}")
    if item.get("triage"):
        triage = item["triage"]
        lines.append(f"Local triage: {item_relevance(item)}/100 {triage['decision']} - {triage['reason']}")
    lines.append("")
    lines.append("Why it matters:")
    lines.append(why_it_matters(item["topics"], item["claims"]))
    lines.append("")
    lines.append("Local model analysis:")
    if item.get("llm_analysis") and item["llm_analysis"]["status"] == "ok":
        lines.append(item["llm_analysis"]["analysis"])
    else:
        lines.append("No local model analysis available.")
    lines.append("")
    lines.append("Extractive notes:")
    if item["sentences"]:
        for sentence in item["sentences"]:
            lines.append(f"- {sentence}")
    else:
        lines.append("- No extractive notes.")
    return "\n".join(lines)


def extract_synthesis_core(text: str) -> str:
    marker = "# Daily Synthesis Core"
    match = re.search(r"(?m)^# Daily Synthesis Core\s*$", text)
    if match:
        return text[match.start() :].strip()
    fallback_markers = ("## Bottom Line", "Bottom Line", "## Kurzfazit", "Kurzfazit")
    for fallback in fallback_markers:
        index = text.find(fallback)
        if index >= 0:
            return ("# Daily Synthesis Core\n\n" + text[index:]).strip()
    return text.strip()


def render_synthesis_document(
    date: str,
    run_id: str,
    model: str,
    thinking: bool,
    included_count: int,
    body: str,
) -> str:
    return "\n".join(
        [
            f"# Daily Synthesis - {date}",
            "",
            f"- Run: `{run_id}`",
            f"- Model: `{model}`",
            f"- Thinking: `{thinking}`",
            f"- Dossiers in context: `{included_count}`",
            "",
            body.strip(),
            "",
        ]
    )


def item_relevance(item: dict[str, Any]) -> int:
    triage = item.get("triage")
    if triage and triage.get("status") == "ok":
        return normalize_relevance(triage.get("relevance", 0))
    return min(100, max(1, int(item["row"]["score"]) * 4))


def normalize_relevance(value: Any) -> int:
    try:
        relevance = int(value)
    except (TypeError, ValueError):
        return 0
    if 0 <= relevance <= 10:
        relevance *= 10
    return max(0, min(100, relevance))


def prefilter_score(item: dict[str, Any]) -> int:
    pref = item.get("prefilter")
    if pref and pref.get("status") == "ok":
        try:
            return max(0, min(100, int(pref.get("score", 0))))
        except (TypeError, ValueError):
            return 0
    row_score = int(item["row"]["score"])
    return min(100, max(0, row_score * 4))


def thesis_match_score(item: dict[str, Any]) -> int:
    topic_score = min(45, len(item.get("topics", [])) * 12)
    claim_score = min(45, len(item.get("claims", [])) * 9)
    keyword_score = min(10, len(item.get("keywords", [])))
    return min(100, topic_score + claim_score + keyword_score)


def final_priority_score(item: dict[str, Any]) -> int:
    local = item_relevance(item)
    pref = prefilter_score(item)
    rule = min(100, max(0, int(item["row"]["score"]) * 4))
    thesis = thesis_match_score(item)
    return round((0.50 * local) + (0.30 * pref) + (0.12 * rule) + (0.08 * thesis))


def get_or_fetch_article_text(
    con: sqlite3.Connection,
    row: sqlite3.Row,
    max_chars: int,
    timeout: int,
) -> tuple[str, str, str | None]:
    cached = con.execute(
        "SELECT text, status, error FROM radar_article_reads WHERE item_id = ?",
        (row["id"],),
    ).fetchone()
    if (
        cached
        and cached["status"] == "ok"
        and article_text_is_usable(cached["text"], row["title"])
        and article_is_current(cached["text"], row["published_at"])
    ):
        return cached["text"], cached["status"], cached["error"]

    try:
        resolved_url = resolve_article_url(row["url"], timeout=timeout)
        payload = fetch_url(resolved_url, timeout=timeout)
        text = extract_article_text(payload, resolved_url)
        status = "ok"
        error = None
        if not article_is_current(text, row["published_at"]):
            embedded = embedded_date_from_text(text[:3_000])
            text = ""
            status = "stale" if embedded else "undated"
            error = (
                f"Embedded publication date is outside daily window: {embedded}"
                if embedded else "Article has no trustworthy publication date"
            )
        if not article_text_is_usable(text, row["title"]):
            text = row["summary"] or ""
        text = text[:max_chars]
        if status == "ok" and not article_text_is_usable(text, row["title"]):
            status = "fallback_summary" if text else "empty"
            error = "No sufficiently grounded article text"
    except (urllib.error.URLError, TimeoutError, UnicodeDecodeError, ValueError) as exc:
        text = row["summary"] or ""
        status = "fallback_summary" if text else "error"
        error = str(exc)

    con.execute(
        """
        INSERT INTO radar_article_reads(item_id, fetched_at, status, url, title, text, error)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(item_id) DO UPDATE SET
            fetched_at = excluded.fetched_at,
            status = excluded.status,
            text = excluded.text,
            error = excluded.error
        """,
        (row["id"], iso_now(), status, row["url"], row["title"], text, error),
    )
    con.commit()
    return text, status, error


def extract_article_text(payload: bytes, url: str) -> str:
    content = payload.decode("utf-8", errors="replace")
    if url.lower().endswith(".pdf") or content[:20].startswith("%PDF"):
        return ""
    content = re.sub(r"(?is)<(script|style|noscript|svg|nav|footer|header).*?</\1>", " ", content)
    blocks = re.findall(r"(?is)<(?:p|li|h1|h2|h3|blockquote)[^>]*>(.*?)</(?:p|li|h1|h2|h3|blockquote)>", content)
    if not blocks:
        body = re.sub(r"(?is)<[^>]+>", " ", content)
        return clean_text(body)
    text = " ".join(clean_text(block) for block in blocks)
    return clean_text(text)


def article_text_is_usable(text: str, title: str, min_chars: int = 500) -> bool:
    cleaned = clean_text(text)
    if len(cleaned) < min_chars:
        return False
    lower = cleaned.lower()
    if "google news" in lower[:500] and "sign in" in lower[:1500]:
        return False
    title_tokens = {
        token for token in re.findall(r"[a-z0-9]+", title.lower())
        if len(token) >= 4 and token not in {"with", "from", "that", "this", "after", "says", "will"}
    }
    matched = {token for token in title_tokens if token in lower}
    return not title_tokens or len(matched) >= min(2, len(title_tokens))


def article_is_current(text: str, published_at: str | None, max_age_hours: int = 72) -> bool:
    published = parse_time(published_at) if published_at else None
    if not published:
        embedded = embedded_date_from_text(text[:3_000])
        published = parse_time(embedded) if embedded else None
    return bool(published and published >= utc_now() - dt.timedelta(hours=max_age_hours))


def require_quality_gates(date: str, domains: tuple[str, ...] = ("radar", "geopolitics", "finance")) -> list[dict[str, Any]]:
    gates = []
    for domain in domains:
        path = TELOS_DIR / domain / date / "quality-gate.json"
        if not path.is_file():
            raise RuntimeError(f"Missing quality gate: {path.relative_to(ROOT)}")
        gate = json.loads(path.read_text(encoding="utf-8"))
        if not gate.get("passed"):
            raise RuntimeError(
                f"Quality gate failed for {domain}: "
                f"{gate.get('grounded_dossiers', 0)}/{gate.get('minimum_grounded_dossiers', '?')} grounded dossiers"
            )
        gates.append(gate)
    return gates


def extract_relevant_sentences(text: str, keywords: list[str], limit: int = 5) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", clean_text(text))
    scored: list[tuple[int, int, str]] = []
    for index, sentence in enumerate(sentences):
        if len(sentence) < 55:
            continue
        low = sentence.lower()
        if is_boilerplate_sentence(low):
            continue
        score = 0
        for keyword in keywords:
            if keyword.lower() in low:
                score += 3
        for strategic in ("agent", "robot", "compute", "benchmark", "memory", "infrastructure", "model", "energy", "data"):
            if strategic in low:
                score += 1
        if score:
            scored.append((score, -index, clip(sentence, 320)))
    scored.sort(reverse=True)
    return [sentence for _, _, sentence in scored[:limit]]


def is_boilerplate_sentence(sentence_lower: str) -> bool:
    boilerplate = (
        "raven.config",
        "sentry.io",
        "sign in",
        "join ieee",
        "ieee xplore",
        "ieee standards",
        "job site",
        "more sites",
        "rss 2026",
        "please send us your events",
        "weekly selection of awesome robotics videos",
        "the june issue of ieee spectrum is here",
    )
    return any(marker in sentence_lower for marker in boilerplate)


def why_it_matters(topics: list[dict[str, Any]], claims: list[str]) -> str:
    labels = {topic["label"] for topic in topics}
    reasons: list[str] = []
    if "Robotics / Physical AI" in labels:
        reasons.append("Touches the physical-AI thesis: robotics is a path from models into real-world data, labor and infrastructure.")
    if "Agents / Memory" in labels:
        reasons.append("Touches the agent-layer thesis: value shifts from chat output toward tools, workflows, permissions and memory.")
    if "Compute / Energy / Chips" in labels:
        reasons.append("Touches the bottleneck thesis: compute, power and cooling constrain AI scaling.")
    if "RSI / AI for Science" in labels:
        reasons.append("Touches the AI-for-science thesis: closed research loops matter more than isolated demos.")
    if "Useful Data Advantage" in labels:
        reasons.append("Touches the useful-data thesis: workflow, first-person and physical-world data may matter more than raw volume.")
    if "Crypto / Agent Infra" in labels:
        reasons.append("Touches the agent-infra thesis: payments, markets and decentralized compute need real usage, not just narrative.")
    if "Frontier AI" in labels:
        reasons.append("Touches the frontier-model thesis: releases and evals are signals for whether the capability curve is still compounding.")
    if claims:
        reasons.append(f"Linked Telos claims: {', '.join(claims[:6])}.")
    return " ".join(reasons) if reasons else "Relevant because it crossed the configured Telos signal threshold."


def get_or_create_llm_analysis(
    con: sqlite3.Connection,
    row: sqlite3.Row,
    article_text: str,
    topics: list[dict[str, Any]],
    keywords: list[str],
    claims: list[str],
    llm_config: dict[str, Any],
) -> dict[str, str]:
    model = str(llm_config.get("model", "gpt-oss:20b"))
    thinking = bool(llm_config.get("analysis_thinking", False))
    prompt = build_llm_prompt(
        title=row["title"],
        source=row["source_name"],
        url=row["url"],
        topics=topics,
        keywords=keywords,
        claims=claims,
        article_text=article_text[: int(llm_config.get("max_input_chars", 6000))],
    )
    prompt_hash = hashlib.sha256(f"analysis_v5_single_block\nthinking={thinking}\n{prompt}".encode("utf-8")).hexdigest()[:24]
    analysis_id = stable_id(row["id"], model, f"thinking={thinking}", prompt_hash)

    cached = con.execute(
        """
        SELECT analysis, status, error
        FROM radar_llm_analyses
        WHERE id = ? AND status = 'ok'
        """,
        (analysis_id,),
    ).fetchone()
    if cached and valid_ai_analysis(str(cached["analysis"] or "")):
        analysis = compact_ai_analysis(str(cached["analysis"] or ""))
        if analysis != str(cached["analysis"] or ""):
            con.execute(
                "UPDATE radar_llm_analyses SET analysis = ? WHERE id = ?",
                (analysis, analysis_id),
            )
            con.commit()
        return {
            "analysis": analysis,
            "status": cached["status"],
            "error": cached["error"] or "",
        }

    try:
        analysis = call_ollama(
            model=model,
            prompt=prompt,
            timeout=int(llm_config.get("timeout_seconds", 180)),
            temperature=float(llm_config.get("temperature", 0.2)),
            num_ctx=int(llm_config.get("num_ctx", 4096)),
            num_predict=int(llm_config.get("num_predict", 450)),
            thinking=thinking,
        )
        analysis = compact_ai_analysis(analysis)
        if not valid_ai_analysis(analysis):
            raise ValueError("Deep analysis omitted required fields or was too short")
        status = "ok"
        error = None
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as exc:
        analysis = ""
        status = "error"
        error = str(exc)

    con.execute(
        """
        INSERT INTO radar_llm_analyses(id, item_id, created_at, model, prompt_hash, analysis, status, error)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            created_at = excluded.created_at,
            analysis = excluded.analysis,
            status = excluded.status,
            error = excluded.error
        """,
        (analysis_id, row["id"], iso_now(), model, prompt_hash, analysis, status, error),
    )
    con.commit()
    return {"analysis": analysis, "status": status, "error": error or ""}


def valid_ai_analysis(text: str) -> bool:
    required = ("Core claim:", "Why it matters:", "Strengthens:", "Weakens/Limit:", "Next watchpoint:")
    return len(text.strip()) >= 180 and all(label.lower() in text.lower() for label in required)


def compact_ai_analysis(text: str) -> str:
    labels = ("Core claim:", "Why it matters:", "Strengthens:", "Weakens/Limit:", "Next watchpoint:")
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    selected: list[str] = []
    seen: set[str] = set()
    for raw in lines:
        normalized = raw.lstrip("- ").strip()
        for label in labels:
            if normalized.lower().startswith(label.lower()) and label not in seen:
                selected.append("- " + normalized)
                seen.add(label)
                break
        if len(seen) == len(labels):
            break
    if len(seen) != len(labels):
        return text.strip()
    return "\n".join(selected)


def get_or_create_llm_triage(
    con: sqlite3.Connection,
    row: sqlite3.Row,
    article_text: str,
    topics: list[dict[str, Any]],
    keywords: list[str],
    claims: list[str],
    llm_config: dict[str, Any],
) -> dict[str, Any]:
    model = str(llm_config.get("model", "qwen2.5:3b"))
    thinking = bool(llm_config.get("triage_thinking", False))
    prompt = build_triage_prompt(
        title=row["title"],
        source=row["source_name"],
        url=row["url"],
        topics=topics,
        keywords=keywords,
        claims=claims,
        article_text=article_text[: int(llm_config.get("max_input_chars", 6500))],
    )
    prompt_hash = hashlib.sha256(f"triage_v4_priority_100\nthinking={thinking}\n{prompt}".encode("utf-8")).hexdigest()[:24]
    triage_id = stable_id("triage", row["id"], model, f"thinking={thinking}", prompt_hash)

    cached = con.execute(
        """
        SELECT relevance, decision, reason, status, error
        FROM radar_llm_triage
        WHERE id = ? AND status = 'ok'
        """,
        (triage_id,),
    ).fetchone()
    if cached:
        return {
            "relevance": int(cached["relevance"]),
            "decision": cached["decision"],
            "reason": cached["reason"],
            "status": cached["status"],
            "error": cached["error"] or "",
        }

    try:
        raw = call_ollama(
            model=model,
            prompt=prompt,
            timeout=int(llm_config.get("timeout_seconds", 180)),
            temperature=0.0,
            num_ctx=int(llm_config.get("num_ctx", 8192)),
            num_predict=180,
            thinking=thinking,
        )
        relevance, decision, reason = parse_triage_response(raw)
        status = "ok"
        error = None
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as exc:
        relevance = 0
        decision = "error"
        reason = ""
        status = "error"
        error = str(exc)

    con.execute(
        """
        INSERT INTO radar_llm_triage(
            id, item_id, created_at, model, prompt_hash, relevance, decision, reason, status, error
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            created_at = excluded.created_at,
            relevance = excluded.relevance,
            decision = excluded.decision,
            reason = excluded.reason,
            status = excluded.status,
            error = excluded.error
        """,
        (triage_id, row["id"], iso_now(), model, prompt_hash, relevance, decision, reason, status, error),
    )
    con.commit()
    return {
        "relevance": relevance,
        "decision": decision,
        "reason": reason,
        "status": status,
        "error": error or "",
    }


def build_triage_prompt(
    title: str,
    source: str,
    url: str,
    topics: list[dict[str, Any]],
    keywords: list[str],
    claims: list[str],
    article_text: str,
) -> str:
    topic_labels = ", ".join(topic["label"] for topic in topics) or "None"
    claim_text = ", ".join(claims) or "None"
    keyword_text = ", ".join(keywords[:20]) or "None"
    return textwrap.dedent(
        f"""
        Decide whether this signal belongs in the Telos Daily Report.
        Work in English only. Do not write German.
        Return no thinking trace and no <think> blocks.

        Telos is interested in:
        major frontier model releases and benchmark shifts from leading AI labs,
        AI agents, personal assistants, memory, task horizon, research agents,
        robotics, world models, physical AI, compute/energy/chips, useful data,
        AI for Science, agent infrastructure, crypto only when there is real utility.

        Return exactly this format:
        relevance: <0-100>
        decision: include|skip
        reason: <one short English sentence>

        Rules:
        0-34 = noise, marketing, event listing, coupon, no durable signal.
        35-54 = weak or indirect signal.
        55-69 = relevant, but probably not a top dossier unless the day is quiet.
        70-84 = important signal with clear relation to Telos theses.
        85-94 = high-priority signal for core theses or watchlist.
        95-100 = day-defining signal: major model release, benchmark shift, real deployment, infrastructure bottleneck, or direct evidence for/against a core thesis.
        Use the full 0-100 range. Do not cluster everything at 70, 80, or 90.
        A major frontier model release from Anthropic, OpenAI, Google DeepMind, Meta, xAI or Mistral should usually be 90-100 unless it has no capability or benchmark substance.
        Skip sponsorship, coupons, and events without technical substance.

        Title: {title}
        Source: {source}
        URL: {url}
        Topics: {topic_labels}
        Keywords: {keyword_text}
        Linked Claims: {claim_text}

        Text:
        {article_text}
        """
    ).strip()


def parse_triage_response(text: str) -> tuple[int, str, str]:
    relevance_match = re.search(r"relevance\s*:\s*(\d+)", text, re.IGNORECASE)
    decision_match = re.search(r"decision\s*:\s*(include|skip)", text, re.IGNORECASE)
    reason_match = re.search(r"reason\s*:\s*(.+)", text, re.IGNORECASE | re.DOTALL)
    if not relevance_match:
        raise ValueError(f"Missing relevance in triage response: {text[:200]}")
    relevance = normalize_relevance(relevance_match.group(1))
    decision = decision_match.group(1).lower() if decision_match else ("include" if relevance >= 60 else "skip")
    reason = clean_text(reason_match.group(1)) if reason_match else ""
    return relevance, decision, reason[:500]


def build_llm_prompt(
    title: str,
    source: str,
    url: str,
    topics: list[dict[str, Any]],
    keywords: list[str],
    claims: list[str],
    article_text: str,
) -> str:
    topic_labels = ", ".join(topic["label"] for topic in topics) or "None"
    claim_text = ", ".join(claims) or "None"
    keyword_text = ", ".join(keywords[:20]) or "None"
    return textwrap.dedent(
        f"""
        You are the local analysis layer for Telos.

        Task:
        Analyze the signal for a daily AI/Robotics/Compute report.
        Work in English only. Do not write German.
        Write briefly, concretely, without hype and with uncertainty.
        Separate what the text actually says from interpretation.
        If this is a frontier model release, compare claimed capability gains against prior models or benchmarks when the text provides enough information, then state whether the capability trend appears to continue, accelerate, flatten, or remain unproven.
        Return no thinking trace and no <think> blocks, only the result.
        No Markdown table.

        Format:
        Write exactly five bullets, one per label. Do not repeat labels and do
        not split the article into multiple separate claim blocks.
        Write each point on its own line:
        - Core claim: 1 sentence.
        - Why it matters: 1-2 sentences connected to the Telos theses.
        - Strengthens: Which claim direction is strengthened?
        - Weakens/Limit: What remains uncertain or pushes against it?
        - Next watchpoint: Which concrete follow-up signal should be watched?

        Metadata:
        Title: {title}
        Source: {source}
        URL: {url}
        Topics: {topic_labels}
        Keywords: {keyword_text}
        Linked Claims: {claim_text}

        The linked claim IDs are routing metadata only. You do not have their
        exact wording. Do not infer support merely because an ID is linked. In
        the Strengthens field, state only the narrow evidence direction shown
        by the supplied text, or write "None from this source alone".

        Text:
        {article_text}
        """
    ).strip()


def call_ollama(
    model: str,
    prompt: str,
    timeout: int,
    temperature: float,
    num_ctx: int,
    num_predict: int,
    thinking: bool = False,
) -> str:
    data = ollama_chat(
        model=model,
        prompt=prompt,
        timeout=timeout,
        temperature=temperature,
        num_ctx=num_ctx,
        num_predict=num_predict,
        thinking=thinking,
    )
    message = data.get("message", {})
    content = strip_thinking(str(message.get("content", ""))).strip()
    if not content and thinking:
        scratch = str(message.get("thinking", "")).strip()
        if scratch:
            final_prompt = textwrap.dedent(
                f"""
                Produce the final answer for the original research task below.
                A previous thinking pass produced private analysis notes. Use
                them only as a draft, verify every statement against the source
                text in the original task, and do not mention or quote the notes.
                Follow the original output format exactly. Return no thinking
                trace and no preamble.

                ORIGINAL TASK:
                {prompt}

                PRIVATE ANALYSIS NOTES:
                {scratch[:12_000]}
                """
            ).strip()
            final_data = ollama_chat(
                model=model,
                prompt=final_prompt,
                timeout=timeout,
                temperature=min(temperature, 0.15),
                num_ctx=max(num_ctx, 8192),
                num_predict=max(900, min(1800, num_predict)),
                thinking=False,
            )
            content = strip_thinking(str(final_data.get("message", {}).get("content", ""))).strip()
    if not content:
        reason = str(data.get("done_reason", "unknown"))
        thinking_chars = len(str(message.get("thinking", "")))
        raise ValueError(
            f"Ollama returned no final content (done_reason={reason}, thinking_chars={thinking_chars})"
        )
    lines = [clean_text(line) for line in content.splitlines()]
    result = "\n".join(line for line in lines if line).strip()
    if not result:
        raise ValueError("Ollama final content became empty after normalization")
    return result


def ollama_chat(
    model: str,
    prompt: str,
    timeout: int,
    temperature: float,
    num_ctx: int,
    num_predict: int,
    thinking: bool,
) -> dict[str, Any]:
    user_prompt = prompt
    if (model.startswith("qwen3:") or model.startswith("qwen3.5:")) and "instruct" not in model and not thinking:
        user_prompt = "/no_think\n\n" + prompt
    payload = {
        "model": model,
        "think": thinking,
        "messages": [
            {
                "role": "system",
                "content": "You are a careful research analyst. Work in English only. Do not invent facts and mark uncertainty.",
            },
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_ctx": num_ctx,
            "num_predict": num_predict,
        },
    }
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def strip_thinking(text: str) -> str:
    text = re.sub(r"(?is)<think>.*?</think>", "", text)
    return text.strip()


def clip(text: str, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def list_items(args: argparse.Namespace) -> None:
    con = connect()
    init_db(con)
    rows = con.execute(
        """
        SELECT id, score, source_name, title, url, published_at, topic_hits
        FROM radar_items
        ORDER BY last_seen_at DESC, score DESC
        LIMIT ?
        """,
        (args.limit,),
    ).fetchall()
    con.close()
    for row in rows:
        topics = ", ".join(topic["label"] for topic in json.loads(row["topic_hits"]))
        print(f"{row['id']} score={row['score']} [{row['source_name']}] {row['title']}")
        if topics:
            print(f"  topics: {topics}")
        print(f"  url: {row['url']}")


def show_item(args: argparse.Namespace) -> None:
    con = connect()
    init_db(con)
    row = con.execute("SELECT * FROM radar_items WHERE id = ?", (args.id,)).fetchone()
    con.close()
    if not row:
        raise SystemExit(f"No radar item found: {args.id}")
    print(json.dumps(dict(row), ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="telos-radar",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent(
            """
            Telos Radar

            Examples:
              python telos_radar.py run
              python telos_radar.py run --lookback-hours 24 --min-score 8
              python telos_radar.py list --limit 20
            """
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Fetch sources, score signals, and optionally write deep reports.")
    p_run.add_argument("--config", default=str(CONFIG_PATH))
    p_run.add_argument("--lookback-hours", type=int)
    p_run.add_argument("--min-score", type=int)
    p_run.add_argument("--timeout", type=int, default=25)
    p_run.add_argument(
        "--stage",
        choices=("scan", "deep", "all"),
        default="all",
        help="scan = fetch/digest/prefilter/triage, deep = dossiers/synthesis from cached candidates, all = old combined behavior.",
    )
    p_run.add_argument("--no-llm", action="store_true", help="Disable local Ollama analysis for this run.")
    p_run.set_defaults(func=run_pipeline)

    p_list = sub.add_parser("list", help="List recent radar items.")
    p_list.add_argument("--limit", type=int, default=20)
    p_list.set_defaults(func=list_items)

    p_show = sub.add_parser("show", help="Show one radar item as JSON.")
    p_show.add_argument("id")
    p_show.set_defaults(func=show_item)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
