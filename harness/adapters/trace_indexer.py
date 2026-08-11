#!/usr/bin/env python3
"""Incremental indexer: reads .trace/runs.jsonl → SQLite with WAL mode."""

from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime
from trace_db import (
    TraceEvent, init_db, get_session_factory, extract_issue_number, session_scope
)

DEFAULT_JSONL = Path(".trace/runs.jsonl")
DEFAULT_DB = Path(".trace/runs.db")


def index_jsonl(jsonl_path: Path | str = DEFAULT_JSONL, db_path: Path | str = DEFAULT_DB) -> int:
    """Index new lines from JSONL into SQLite. Returns count of new events indexed."""
    jsonl_path = Path(jsonl_path)
    db_path = Path(db_path)
    
    if not jsonl_path.exists():
        print(f"JSONL not found: {jsonl_path}")
        return 0
    
    Session = get_session_factory(str(db_path))
    
    # Get last indexed line_number for this JSONL file
    with Session() as session:
        last_line = session.query(TraceEvent.line_number).order_by(TraceEvent.line_number.desc()).first()
        last_line_num = last_line[0] if last_line else 0
    
    new_count = 0
    with Session() as session:
        with jsonl_path.open("r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                if line_num <= last_line_num:
                    continue
                try:
                    data = json.loads(line.strip())
                    
                    # Validate required fields
                    required = ["ts", "run_id", "profile", "phase", "status"]
                    if not all(k in data for k in required):
                        continue
                    
                    event = TraceEvent(
                        ts=datetime.fromisoformat(data["ts"].replace("Z", "+00:00")),
                        run_id=data["run_id"],
                        profile=data["profile"],
                        phase=data["phase"],
                        status=data["status"],
                        model=data.get("model", ""),
                        tokens_in=data.get("tokens_in", 0),
                        tokens_out=data.get("tokens_out", 0),
                        cost_usd=data.get("cost_usd", 0.0),
                        artifacts=json.dumps(data.get("artifacts", [])),
                        gates_passed=json.dumps(data.get("gates_passed", [])),
                        error=data.get("error"),
                        issue_number=extract_issue_number(data["run_id"]),
                        line_number=line_num,
                    )
                    session.add(event)
                    new_count += 1
                except (json.JSONDecodeError, KeyError, ValueError) as e:
                    print(f"Skipping line {line_num}: {e}")
                    continue
        
        if new_count > 0:
            session.commit()
            print(f"Indexed {new_count} new events from {jsonl_path}")
    
    return new_count


def reindex_all(jsonl_path: Path | str = DEFAULT_JSONL, db_path: Path | str = DEFAULT_DB) -> int:
    """Full rebuild of the index (use after schema changes)."""
    db_path = Path(db_path)
    if db_path.exists():
        db_path.unlink()
    
    init_db(str(db_path))
    return index_jsonl(jsonl_path, db_path)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--reindex":
        reindex_all()
    else:
        index_jsonl()
