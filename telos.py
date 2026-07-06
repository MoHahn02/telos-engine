#!/usr/bin/env python3
"""
Telos Engine v0.1

Local memory, claim, and belief store for a chat-driven second brain.
Uses only the Python standard library.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sqlite3
import textwrap
import uuid
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parent
TELOS_DIR = ROOT / "telos"
DB_PATH = TELOS_DIR / "telos.db"
DIRS = {
    "inbox": TELOS_DIR / "inbox",
    "memories": TELOS_DIR / "memories",
    "claims": TELOS_DIR / "claims",
    "beliefs": TELOS_DIR / "beliefs",
    "sources": TELOS_DIR / "sources",
    "reviews": TELOS_DIR / "reviews",
}

CLAIM_MARKERS = (
    "i believe",
    "i think",
    "i assume",
    "my thesis",
    "hypothesis",
    "thesis",
    "probably",
    "likely",
    "should",
    "ich glaube",
    "ich denke",
    "ich vermute",
    "meine these",
    "hypothese",
    "wahrscheinlich",
    "vermutlich",
    "sollte",
    "these:",
    "claim:",
)

NORMATIVE_MARKERS = (
    "should",
    "must",
    "ought",
    "valuable",
    "important",
    "sollte",
    "muss",
    "wertvoll",
    "wichtig",
    "schuetzenswert",
    "schützenswert",
)

THEORY_MARKERS = (
    "because",
    "causes",
    "leads to",
    "mechanism",
    "explains",
    "weil",
    "fuehrt zu",
    "führt zu",
    "mechanismus",
    "erklaert",
    "erklärt",
)


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def slug(text: str, limit: int = 54) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return (cleaned[:limit].strip("-") or "item")


def short_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def ensure_initialized() -> None:
    if not DB_PATH.exists():
        raise SystemExit("Telos is not initialized. Run: python telos.py init")


def init_db() -> None:
    TELOS_DIR.mkdir(exist_ok=True)
    for directory in DIRS.values():
        directory.mkdir(parents=True, exist_ok=True)

    con = connect()
    try:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                kind TEXT NOT NULL,
                text TEXT NOT NULL,
                source TEXT,
                tags TEXT NOT NULL DEFAULT '[]',
                file_path TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS claims (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                text TEXT NOT NULL,
                type TEXT NOT NULL,
                confidence REAL NOT NULL,
                importance REAL NOT NULL,
                stability REAL NOT NULL,
                status TEXT NOT NULL,
                source_memory_id TEXT,
                file_path TEXT NOT NULL,
                FOREIGN KEY(source_memory_id) REFERENCES memories(id)
            );

            CREATE TABLE IF NOT EXISTS beliefs (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                claim_id TEXT,
                text TEXT NOT NULL,
                type TEXT NOT NULL,
                confidence REAL NOT NULL,
                priority REAL NOT NULL,
                stability REAL NOT NULL,
                status TEXT NOT NULL,
                file_path TEXT NOT NULL,
                FOREIGN KEY(claim_id) REFERENCES claims(id)
            );

            CREATE TABLE IF NOT EXISTS evidence (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                target_type TEXT NOT NULL,
                target_id TEXT NOT NULL,
                polarity TEXT NOT NULL,
                text TEXT NOT NULL,
                source TEXT,
                reliability REAL NOT NULL DEFAULT 0.5
            );

            CREATE TABLE IF NOT EXISTS links (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                from_type TEXT NOT NULL,
                from_id TEXT NOT NULL,
                relation TEXT NOT NULL,
                to_type TEXT NOT NULL,
                to_id TEXT NOT NULL,
                note TEXT
            );

            CREATE TABLE IF NOT EXISTS reviews (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                target_type TEXT,
                target_id TEXT,
                text TEXT NOT NULL,
                file_path TEXT NOT NULL
            );
            """
        )
        try:
            con.executescript(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS telos_fts USING fts5(
                    item_type,
                    item_id UNINDEXED,
                    text
                );
                """
            )
        except sqlite3.OperationalError:
            pass
        con.commit()
    finally:
        con.close()


def sync_fts(con: sqlite3.Connection, item_type: str, item_id: str, text: str) -> None:
    try:
        con.execute(
            "DELETE FROM telos_fts WHERE item_type = ? AND item_id = ?",
            (item_type, item_id),
        )
        con.execute(
            "INSERT INTO telos_fts(item_type, item_id, text) VALUES (?, ?, ?)",
            (item_type, item_id, text),
        )
    except sqlite3.OperationalError:
        return


def frontmatter(metadata: dict[str, object]) -> str:
    return "---\n" + json.dumps(metadata, ensure_ascii=False, indent=2) + "\n---\n\n"


def write_markdown(directory: Path, item_id: str, title: str, metadata: dict[str, object], body: str) -> Path:
    path = directory / f"{item_id}-{slug(title)}.md"
    path.write_text(frontmatter(metadata) + body.strip() + "\n", encoding="utf-8")
    return path


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
    return [part.strip(" \t-") for part in parts if part.strip(" \t-")]


def classify_claim(text: str) -> str:
    low = text.lower()
    if any(marker in low for marker in NORMATIVE_MARKERS):
        return "normative"
    if any(marker in low for marker in THEORY_MARKERS):
        return "theory"
    if "?" in text:
        return "question"
    return "descriptive"


def estimate_confidence(text: str) -> float:
    low = text.lower()
    if any(word in low for word in ("vielleicht", "maybe", "speculative", "spekulativ")):
        return 0.35
    if any(word in low for word in ("wahrscheinlich", "probably", "likely", "vermutlich")):
        return 0.55
    if any(word in low for word in ("ich glaube", "i believe", "i think", "ich denke")):
        return 0.50
    return 0.45


def extract_claim_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    for sentence in split_sentences(text):
        low = sentence.lower()
        if any(marker in low for marker in CLAIM_MARKERS):
            candidates.append(sentence)
        elif len(sentence) > 35 and any(verb in low for verb in (" ist ", " sind ", " is ", " are ")):
            candidates.append(sentence)
    seen: set[str] = set()
    unique = []
    for candidate in candidates:
        normalized = re.sub(r"\s+", " ", candidate).strip()
        key = normalized.lower()
        if key not in seen:
            unique.append(normalized)
            seen.add(key)
    return unique[:8]


def add_memory(args: argparse.Namespace) -> None:
    ensure_initialized()
    created = now_iso()
    memory_id = short_id("mem")
    tags = parse_csv(args.tags)
    metadata = {
        "id": memory_id,
        "type": "memory",
        "kind": args.kind,
        "created_at": created,
        "source": args.source,
        "tags": tags,
    }
    path = write_markdown(
        DIRS["memories"],
        memory_id,
        args.text,
        metadata,
        f"# Memory\n\n{args.text}",
    )

    con = connect()
    try:
        con.execute(
            """
            INSERT INTO memories(id, created_at, kind, text, source, tags, file_path)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (memory_id, created, args.kind, args.text, args.source, json.dumps(tags), str(path.relative_to(ROOT))),
        )
        sync_fts(con, "memory", memory_id, args.text)

        claim_ids = []
        if not args.no_extract:
            for candidate in extract_claim_candidates(args.text):
                claim_ids.append(
                    create_claim(
                        con=con,
                        text=candidate,
                        claim_type=classify_claim(candidate),
                        confidence=estimate_confidence(candidate),
                        importance=args.importance,
                        stability=0.35,
                        status="active",
                        source_memory_id=memory_id,
                    )
                )

        belief_id = None
        if args.belief:
            belief_id = create_belief(
                con=con,
                text=args.text,
                belief_type=args.belief_type,
                confidence=args.confidence,
                priority=args.priority,
                stability=args.stability,
                status="core" if args.core else "active",
                claim_id=None,
            )
        con.commit()
    finally:
        con.close()

    print(f"memory: {memory_id}")
    print(f"file: {path.relative_to(ROOT)}")
    if claim_ids:
        print("claims: " + ", ".join(claim_ids))
    if belief_id:
        print(f"belief: {belief_id}")


def create_claim(
    con: sqlite3.Connection,
    text: str,
    claim_type: str,
    confidence: float,
    importance: float,
    stability: float,
    status: str,
    source_memory_id: str | None,
) -> str:
    created = now_iso()
    claim_id = short_id("clm")
    metadata = {
        "id": claim_id,
        "type": "claim",
        "claim_type": claim_type,
        "confidence": confidence,
        "importance": importance,
        "stability": stability,
        "status": status,
        "source_memory_id": source_memory_id,
        "created_at": created,
        "updated_at": created,
    }
    body = f"""# Claim

{text}

## Evidence For

- TBD

## Evidence Against

- TBD

## Falsifiers

- TBD
"""
    path = write_markdown(DIRS["claims"], claim_id, text, metadata, body)
    con.execute(
        """
        INSERT INTO claims(
            id, created_at, updated_at, text, type, confidence, importance,
            stability, status, source_memory_id, file_path
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            claim_id,
            created,
            created,
            text,
            claim_type,
            confidence,
            importance,
            stability,
            status,
            source_memory_id,
            str(path.relative_to(ROOT)),
        ),
    )
    sync_fts(con, "claim", claim_id, text)
    return claim_id


def add_claim(args: argparse.Namespace) -> None:
    ensure_initialized()
    con = connect()
    try:
        claim_id = create_claim(
            con=con,
            text=args.text,
            claim_type=args.type,
            confidence=args.confidence,
            importance=args.importance,
            stability=args.stability,
            status=args.status,
            source_memory_id=None,
        )
        if args.belief:
            belief_id = create_belief(
                con=con,
                text=args.text,
                belief_type=args.type,
                confidence=args.confidence,
                priority=args.importance,
                stability=args.stability,
                status="active",
                claim_id=claim_id,
            )
        else:
            belief_id = None
        con.commit()
    finally:
        con.close()
    print(f"claim: {claim_id}")
    if belief_id:
        print(f"belief: {belief_id}")


def create_belief(
    con: sqlite3.Connection,
    text: str,
    belief_type: str,
    confidence: float,
    priority: float,
    stability: float,
    status: str,
    claim_id: str | None,
) -> str:
    created = now_iso()
    belief_id = short_id("blf")
    metadata = {
        "id": belief_id,
        "type": "belief",
        "belief_type": belief_type,
        "confidence": confidence,
        "priority": priority,
        "stability": stability,
        "status": status,
        "claim_id": claim_id,
        "created_at": created,
        "updated_at": created,
    }
    body = f"""# Belief

{text}

## Operational Meaning

- TBD

## Update Rule

- Strengthen with reliable confirming evidence.
- Weaken with reliable counterevidence or failed predictions.

## Doubt Notes

- TBD
"""
    path = write_markdown(DIRS["beliefs"], belief_id, text, metadata, body)
    con.execute(
        """
        INSERT INTO beliefs(
            id, created_at, updated_at, claim_id, text, type, confidence,
            priority, stability, status, file_path
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            belief_id,
            created,
            created,
            claim_id,
            text,
            belief_type,
            confidence,
            priority,
            stability,
            status,
            str(path.relative_to(ROOT)),
        ),
    )
    sync_fts(con, "belief", belief_id, text)
    return belief_id


def add_belief(args: argparse.Namespace) -> None:
    ensure_initialized()
    con = connect()
    try:
        belief_id = create_belief(
            con=con,
            text=args.text,
            belief_type=args.type,
            confidence=args.confidence,
            priority=args.priority,
            stability=args.stability,
            status=args.status,
            claim_id=args.claim_id,
        )
        con.commit()
    finally:
        con.close()
    print(f"belief: {belief_id}")


def parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def clamp_probability(value: float) -> float:
    return max(0.0, min(1.0, value))


def add_evidence(args: argparse.Namespace) -> None:
    ensure_initialized()
    evidence_id = short_id("evd")
    created = now_iso()
    con = connect()
    try:
        con.execute(
            """
            INSERT INTO evidence(
                id, created_at, target_type, target_id, polarity, text, source, reliability
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evidence_id,
                created,
                args.target_type,
                args.target_id,
                args.polarity,
                args.text,
                args.source,
                args.reliability,
            ),
        )
        maybe_update_target_confidence(con, args.target_type, args.target_id, args.polarity, args.reliability)
        con.commit()
    finally:
        con.close()
    print(f"evidence: {evidence_id}")


def maybe_update_target_confidence(
    con: sqlite3.Connection,
    target_type: str,
    target_id: str,
    polarity: str,
    reliability: float,
) -> None:
    table = "claims" if target_type == "claim" else "beliefs" if target_type == "belief" else None
    if not table:
        return
    row = con.execute(f"SELECT confidence, stability FROM {table} WHERE id = ?", (target_id,)).fetchone()
    if not row:
        return
    confidence = float(row["confidence"])
    stability = float(row["stability"])
    direction = 1.0 if polarity == "for" else -1.0
    delta = direction * 0.04 * reliability * (1.0 - stability)
    new_confidence = clamp_probability(confidence + delta)
    con.execute(
        f"UPDATE {table} SET confidence = ?, updated_at = ? WHERE id = ?",
        (new_confidence, now_iso(), target_id),
    )


def list_items(args: argparse.Namespace) -> None:
    ensure_initialized()
    table = args.kind
    allowed = {"memories", "claims", "beliefs", "reviews"}
    if table not in allowed:
        raise SystemExit(f"Unknown list kind: {table}")
    con = connect()
    try:
        if table in {"claims", "beliefs"} and args.status != "all":
            if table == "beliefs" and args.status == "active":
                rows = con.execute(
                    """
                    SELECT * FROM beliefs
                    WHERE status IN ('core', 'active')
                    ORDER BY priority DESC, confidence DESC, created_at DESC
                    LIMIT ?
                    """,
                    (args.limit,),
                ).fetchall()
            else:
                score_column = "importance" if table == "claims" else "priority"
                rows = con.execute(
                    f"""
                    SELECT * FROM {table}
                    WHERE status = ?
                    ORDER BY {score_column} DESC, confidence DESC, created_at DESC
                    LIMIT ?
                    """,
                    (args.status, args.limit),
                ).fetchall()
        else:
            rows = con.execute(f"SELECT * FROM {table} ORDER BY created_at DESC LIMIT ?", (args.limit,)).fetchall()
    finally:
        con.close()
    for row in rows:
        print(format_row(table, row))


def format_row(table: str, row: sqlite3.Row) -> str:
    if table == "memories":
        return f"{row['id']} [{row['kind']}] {row['created_at']} :: {clip(row['text'])}"
    if table == "claims":
        return (
            f"{row['id']} [{row['type']}] p={row['confidence']:.2f} "
            f"imp={row['importance']:.2f} {row['status']} :: {clip(row['text'])}"
        )
    if table == "beliefs":
        return (
            f"{row['id']} [{row['type']}] p={row['confidence']:.2f} "
            f"prio={row['priority']:.2f} {row['status']} :: {clip(row['text'])}"
        )
    return f"{row['id']} {row['created_at']} :: {clip(row['text'])}"


def clip(text: str, limit: int = 120) -> str:
    one_line = re.sub(r"\s+", " ", text).strip()
    if len(one_line) <= limit:
        return one_line
    return one_line[: limit - 3] + "..."


def search(args: argparse.Namespace) -> None:
    ensure_initialized()
    con = connect()
    try:
        rows = search_rows(con, args.query, args.limit)
    finally:
        con.close()
    for row in rows:
        print(f"{row['item_type']}:{row['item_id']} :: {clip(row['text'], 180)}")


def search_rows(con: sqlite3.Connection, query: str, limit: int) -> list[sqlite3.Row]:
    try:
        safe_query = " OR ".join(token for token in re.findall(r"[\w-]+", query) if token)
        if safe_query:
            fts_rows = con.execute(
                """
                SELECT item_type, item_id, text
                FROM telos_fts
                WHERE telos_fts MATCH ?
                LIMIT ?
                """,
                (safe_query, limit * 3),
            ).fetchall()
            rows = [row for row in fts_rows if is_visible_search_hit(con, row["item_type"], row["item_id"])]
            if rows:
                return rows[:limit]
    except sqlite3.OperationalError:
        pass

    pattern = f"%{query}%"
    rows: list[sqlite3.Row] = []
    rows.extend(
        con.execute(
            """
            SELECT 'belief' AS item_type, id AS item_id, text
            FROM beliefs
            WHERE status IN ('core', 'active') AND text LIKE ?
            LIMIT ?
            """,
            (pattern, limit),
        ).fetchall()
    )
    rows.extend(
        con.execute(
            """
            SELECT 'claim' AS item_type, id AS item_id, text
            FROM claims
            WHERE status = 'active' AND text LIKE ?
            LIMIT ?
            """,
            (pattern, limit),
        ).fetchall()
    )
    rows.extend(
        con.execute(
            "SELECT 'memory' AS item_type, id AS item_id, text FROM memories WHERE text LIKE ? LIMIT ?",
            (pattern, limit),
        ).fetchall()
    )
    return rows[:limit]


def is_visible_search_hit(con: sqlite3.Connection, item_type: str, item_id: str) -> bool:
    if item_type == "claim":
        row = con.execute("SELECT status FROM claims WHERE id = ?", (item_id,)).fetchone()
        return bool(row and row["status"] == "active")
    if item_type == "belief":
        row = con.execute("SELECT status FROM beliefs WHERE id = ?", (item_id,)).fetchone()
        return bool(row and row["status"] in ("core", "active"))
    return True


def show(args: argparse.Namespace) -> None:
    ensure_initialized()
    con = connect()
    try:
        for table in ("memories", "claims", "beliefs", "reviews"):
            row = con.execute(f"SELECT * FROM {table} WHERE id = ?", (args.id,)).fetchone()
            if row:
                print(format_row(table, row))
                file_path = ROOT / row["file_path"]
                if file_path.exists():
                    print()
                    print(file_path.read_text(encoding="utf-8"))
                return
    finally:
        con.close()
    raise SystemExit(f"No item found for id: {args.id}")


def context(args: argparse.Namespace) -> None:
    ensure_initialized()
    con = connect()
    try:
        hits = search_rows(con, args.query, args.limit)
        beliefs = con.execute(
            """
            SELECT id, text, type, confidence, priority, stability, status
            FROM beliefs
            WHERE status IN ('core', 'active')
            ORDER BY priority DESC, confidence DESC
            LIMIT 8
            """
        ).fetchall()
        claims = con.execute(
            """
            SELECT id, text, type, confidence, importance, stability, status
            FROM claims
            WHERE status = 'active'
            ORDER BY importance DESC, confidence DESC
            LIMIT 8
            """
        ).fetchall()
    finally:
        con.close()

    print("# Telos Context")
    print()
    print("## Query")
    print(args.query)
    print()
    print("## Relevant Search Hits")
    if hits:
        for hit in hits:
            print(f"- {hit['item_type']}:{hit['item_id']} - {clip(hit['text'], 220)}")
    else:
        print("- None")
    print()
    print("## Active Beliefs")
    if beliefs:
        for belief in beliefs:
            print(
                f"- {belief['id']} p={belief['confidence']:.2f} "
                f"prio={belief['priority']:.2f} stable={belief['stability']:.2f}: {belief['text']}"
            )
    else:
        print("- None")
    print()
    print("## Active Claims")
    if claims:
        for claim in claims:
            print(
                f"- {claim['id']} p={claim['confidence']:.2f} "
                f"imp={claim['importance']:.2f}: {claim['text']}"
            )
    else:
        print("- None")
    print()
    print("## Reasoning Contract")
    print("- Separate sourced knowledge, belief, thesis, speculation, and value judgment.")
    print("- Use confidence values as provisional, not as certainty.")
    print("- Surface conflicts and falsifiers before increasing confidence.")
    print("- Do not promote a memory into a belief without explicit reason.")


def review(args: argparse.Namespace) -> None:
    ensure_initialized()
    con = connect()
    try:
        weak_claims = con.execute(
            """
            SELECT id, text, confidence, importance, stability
            FROM claims
            WHERE status = 'active'
            ORDER BY confidence ASC, importance DESC
            LIMIT ?
            """,
            (args.limit,),
        ).fetchall()
        stale_beliefs = con.execute(
            """
            SELECT id, text, confidence, priority, stability, updated_at
            FROM beliefs
            WHERE status IN ('core', 'active')
            ORDER BY updated_at ASC
            LIMIT ?
            """,
            (args.limit,),
        ).fetchall()
        missing_evidence = con.execute(
            """
            SELECT c.id, c.text, c.confidence
            FROM claims c
            LEFT JOIN evidence e ON e.target_type = 'claim' AND e.target_id = c.id
            WHERE e.id IS NULL
            ORDER BY c.importance DESC, c.created_at ASC
            LIMIT ?
            """,
            (args.limit,),
        ).fetchall()
    finally:
        con.close()

    print("# Telos Review")
    print()
    print("## Weak Or Uncertain Claims")
    print_rows_for_review(weak_claims, "claim")
    print()
    print("## Beliefs Due For Review")
    print_rows_for_review(stale_beliefs, "belief")
    print()
    print("## Claims Missing Evidence")
    print_rows_for_review(missing_evidence, "claim")


def print_rows_for_review(rows: Iterable[sqlite3.Row], label: str) -> None:
    found = False
    for row in rows:
        found = True
        confidence = row["confidence"] if "confidence" in row.keys() else 0.0
        print(f"- {label}:{row['id']} p={confidence:.2f} - {clip(row['text'], 180)}")
    if not found:
        print("- None")


def create_review(args: argparse.Namespace) -> None:
    ensure_initialized()
    review_id = short_id("rev")
    created = now_iso()
    metadata = {
        "id": review_id,
        "type": "review",
        "created_at": created,
        "target_type": args.target_type,
        "target_id": args.target_id,
    }
    path = write_markdown(DIRS["reviews"], review_id, args.text, metadata, f"# Review\n\n{args.text}")
    con = connect()
    try:
        con.execute(
            """
            INSERT INTO reviews(id, created_at, target_type, target_id, text, file_path)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (review_id, created, args.target_type, args.target_id, args.text, str(path.relative_to(ROOT))),
        )
        sync_fts(con, "review", review_id, args.text)
        con.commit()
    finally:
        con.close()
    print(f"review: {review_id}")


def seed(args: argparse.Namespace) -> None:
    init_db()
    con = connect()
    try:
        existing = con.execute("SELECT COUNT(*) AS count FROM beliefs").fetchone()["count"]
        if existing:
            print("Seed skipped: beliefs already exist.")
            return
        seeds = [
            ("Truth is more valuable than comforting falsehood.", "normative", 0.95, 0.98, 0.80, "core"),
            ("Uncertainty should be represented as uncertainty, not invented certainty.", "method", 0.95, 0.96, 0.85, "core"),
            ("New evidence may change beliefs, but updates must be explicit and auditable.", "method", 0.90, 0.94, 0.80, "core"),
            ("Technology should expand human agency rather than quietly replace it.", "normative", 0.80, 0.90, 0.70, "core"),
            ("A useful belief system needs a doubt engine to avoid becoming dogma.", "method", 0.88, 0.92, 0.75, "core"),
        ]
        for text, belief_type, confidence, priority, stability, status in seeds:
            create_belief(
                con=con,
                text=text,
                belief_type=belief_type,
                confidence=confidence,
                priority=priority,
                stability=stability,
                status=status,
                claim_id=None,
            )
        con.commit()
    finally:
        con.close()
    print("Seeded core beliefs.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="telos",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent(
            """
            Telos Engine v0.1

            Examples:
              python telos.py init
              python telos.py seed
              python telos.py add "Merke: humanoid robots may scale after 2027" --tags robotics,future
              python telos.py claim "Compute is a bottleneck for embodied AI" --type theory --confidence 0.55
              python telos.py belief "Truth beats comfortable illusion" --type normative --status core
              python telos.py context "robotics investment thesis"
            """
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Create telos folders and database.")
    p_init.set_defaults(func=lambda args: (init_db(), print(f"Initialized: {TELOS_DIR.relative_to(ROOT)}")))

    p_seed = sub.add_parser("seed", help="Create initial core beliefs.")
    p_seed.set_defaults(func=seed)

    p_add = sub.add_parser("add", help="Add raw memory and optionally extract claims.")
    p_add.add_argument("text")
    p_add.add_argument("--kind", default="note")
    p_add.add_argument("--source")
    p_add.add_argument("--tags")
    p_add.add_argument("--no-extract", action="store_true")
    p_add.add_argument("--importance", type=float, default=0.50)
    p_add.add_argument("--belief", action="store_true", help="Also store the text as a belief.")
    p_add.add_argument("--belief-type", default="descriptive")
    p_add.add_argument("--confidence", type=float, default=0.50)
    p_add.add_argument("--priority", type=float, default=0.60)
    p_add.add_argument("--stability", type=float, default=0.40)
    p_add.add_argument("--core", action="store_true")
    p_add.set_defaults(func=add_memory)

    p_claim = sub.add_parser("claim", help="Add a claim directly.")
    p_claim.add_argument("text")
    p_claim.add_argument("--type", default="descriptive")
    p_claim.add_argument("--confidence", type=float, default=0.50)
    p_claim.add_argument("--importance", type=float, default=0.60)
    p_claim.add_argument("--stability", type=float, default=0.35)
    p_claim.add_argument("--status", default="active")
    p_claim.add_argument("--belief", action="store_true")
    p_claim.set_defaults(func=add_claim)

    p_belief = sub.add_parser("belief", help="Add a belief directly.")
    p_belief.add_argument("text")
    p_belief.add_argument("--type", default="descriptive")
    p_belief.add_argument("--confidence", type=float, default=0.60)
    p_belief.add_argument("--priority", type=float, default=0.70)
    p_belief.add_argument("--stability", type=float, default=0.55)
    p_belief.add_argument("--status", default="active")
    p_belief.add_argument("--claim-id")
    p_belief.set_defaults(func=add_belief)

    p_evd = sub.add_parser("evidence", help="Attach evidence and gently update confidence.")
    p_evd.add_argument("target_type", choices=("claim", "belief"))
    p_evd.add_argument("target_id")
    p_evd.add_argument("polarity", choices=("for", "against"))
    p_evd.add_argument("text")
    p_evd.add_argument("--source")
    p_evd.add_argument("--reliability", type=float, default=0.50)
    p_evd.set_defaults(func=add_evidence)

    p_list = sub.add_parser("list", help="List stored items.")
    p_list.add_argument("kind", choices=("memories", "claims", "beliefs", "reviews"))
    p_list.add_argument("--limit", type=int, default=20)
    p_list.add_argument(
        "--status",
        choices=("active", "archived", "core", "all"),
        default="active",
        help="For claims/beliefs, filter by status. Defaults to active.",
    )
    p_list.set_defaults(func=list_items)

    p_search = sub.add_parser("search", help="Search memories, claims, and beliefs.")
    p_search.add_argument("query")
    p_search.add_argument("--limit", type=int, default=10)
    p_search.set_defaults(func=search)

    p_show = sub.add_parser("show", help="Show one item by id.")
    p_show.add_argument("id")
    p_show.set_defaults(func=show)

    p_context = sub.add_parser("context", help="Print context block for chat reasoning.")
    p_context.add_argument("query")
    p_context.add_argument("--limit", type=int, default=10)
    p_context.set_defaults(func=context)

    p_review = sub.add_parser("review", help="Show weak, stale, and unsupported items.")
    p_review.add_argument("--limit", type=int, default=10)
    p_review.set_defaults(func=review)

    p_revadd = sub.add_parser("review-add", help="Add a reflection/review note.")
    p_revadd.add_argument("text")
    p_revadd.add_argument("--target-type")
    p_revadd.add_argument("--target-id")
    p_revadd.set_defaults(func=create_review)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
