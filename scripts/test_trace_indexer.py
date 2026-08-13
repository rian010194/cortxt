#!/usr/bin/env python3
"""Tests for trace indexer."""

import tempfile
import os
import json
from pathlib import Path

# Add parent directory to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from schemas.trace_db import init_db, get_session_factory, TraceEvent
from scripts.trace_indexer import index_jsonl, reindex_all


def test_indexer_creates_tables_and_inserts():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test.db")
        jsonl_path = os.path.join(tmp, "runs.jsonl")
        
        # Write test JSONL
        with open(jsonl_path, "w") as f:
            f.write('{"ts":"2026-08-04T10:00:00Z","run_id":"TEST-1","profile":"coordinator","phase":"plan","status":"start","model":"nemotron","tokens_in":0,"tokens_out":0,"cost_usd":0.0,"artifacts":[],"gates_passed":[]}\n')
            f.write('{"ts":"2026-08-04T10:00:05Z","run_id":"TEST-1","profile":"coordinator","phase":"plan","status":"success","model":"nemotron","tokens_in":100,"tokens_out":50,"cost_usd":0.0001,"artifacts":["plan.md"],"gates_passed":["artifacts_exist"]}\n')
        
        init_db(db_path)
        count = index_jsonl(jsonl_path, db_path)
        
        assert count == 2, f"Expected 2 indexed, got {count}"
        
        Session = get_session_factory(db_path)
        with Session() as session:
            events = session.query(TraceEvent).filter_by(run_id="TEST-1").all()
            assert len(events) == 2
            assert events[0].status == "start"
            assert events[1].status == "success"
            assert events[1].tokens_in == 100
            assert "plan.md" in json.loads(events[1].artifacts)
            assert events[0].line_number == 1
            assert events[1].line_number == 2


def test_incremental_indexing():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test.db")
        jsonl_path = os.path.join(tmp, "runs.jsonl")
        
        # Write initial JSONL
        with open(jsonl_path, "w") as f:
            f.write('{"ts":"2026-08-04T10:00:00Z","run_id":"TEST-1","profile":"coordinator","phase":"plan","status":"start","model":"nemotron","tokens_in":0,"tokens_out":0,"cost_usd":0.0,"artifacts":[],"gates_passed":[]}\n')
        
        init_db(db_path)
        count1 = index_jsonl(jsonl_path, db_path)
        assert count1 == 1
        
        # Append more lines
        with open(jsonl_path, "a") as f:
            f.write('{"ts":"2026-08-04T10:00:05Z","run_id":"TEST-1","profile":"coordinator","phase":"plan","status":"success","model":"nemotron","tokens_in":100,"tokens_out":50,"cost_usd":0.0001,"artifacts":["plan.md"],"gates_passed":["artifacts_exist"]}\n')
            f.write('{"ts":"2026-08-04T10:00:10Z","run_id":"TEST-1","profile":"researcher","phase":"research","status":"start","model":"kimi","tokens_in":0,"tokens_out":0,"cost_usd":0.0,"artifacts":[],"gates_passed":[]}\n')
        
        count2 = index_jsonl(jsonl_path, db_path)
        assert count2 == 2, f"Expected 2 new, got {count2}"
        
        Session = get_session_factory(db_path)
        with Session() as session:
            events = session.query(TraceEvent).filter_by(run_id="TEST-1").all()
            assert len(events) == 3


def test_issue_number_extraction():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test.db")
        jsonl_path = os.path.join(tmp, "runs.jsonl")
        
        with open(jsonl_path, "w") as f:
            f.write('{"ts":"2026-08-04T10:00:00Z","run_id":"GH-42-abc123","profile":"coordinator","phase":"plan","status":"start","model":"nemotron","tokens_in":0,"tokens_out":0,"cost_usd":0.0,"artifacts":[],"gates_passed":[]}\n')
            f.write('{"ts":"2026-08-04T10:00:00Z","run_id":"GH-100-xyz789","profile":"coordinator","phase":"plan","status":"start","model":"nemotron","tokens_in":0,"tokens_out":0,"cost_usd":0.0,"artifacts":[],"gates_passed":[]}\n')
            f.write('{"ts":"2026-08-04T10:00:00Z","run_id":"OTHER-123","profile":"coordinator","phase":"plan","status":"start","model":"nemotron","tokens_in":0,"tokens_out":0,"cost_usd":0.0,"artifacts":[],"gates_passed":[]}\n')
        
        init_db(db_path)
        index_jsonl(jsonl_path, db_path)
        
        Session = get_session_factory(db_path)
        with Session() as session:
            e1 = session.query(TraceEvent).filter_by(run_id="GH-42-abc123").first()
            assert e1.issue_number == 42
            
            e2 = session.query(TraceEvent).filter_by(run_id="GH-100-xyz789").first()
            assert e2.issue_number == 100
            
            e3 = session.query(TraceEvent).filter_by(run_id="OTHER-123").first()
            assert e3.issue_number is None


def test_reindex_all():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test.db")
        jsonl_path = os.path.join(tmp, "runs.jsonl")
        
        with open(jsonl_path, "w") as f:
            f.write('{"ts":"2026-08-04T10:00:00Z","run_id":"TEST-1","profile":"coordinator","phase":"plan","status":"start","model":"nemotron","tokens_in":0,"tokens_out":0,"cost_usd":0.0,"artifacts":[],"gates_passed":[]}\n')
        
        init_db(db_path)
        index_jsonl(jsonl_path, db_path)
        
        # Modify JSONL
        with open(jsonl_path, "w") as f:
            f.write('{"ts":"2026-08-04T10:00:00Z","run_id":"TEST-1","profile":"coordinator","phase":"plan","status":"start","model":"nemotron","tokens_in":0,"tokens_out":0,"cost_usd":0.0,"artifacts":[],"gates_passed":[]}\n')
            f.write('{"ts":"2026-08-04T10:00:05Z","run_id":"TEST-1","profile":"coordinator","phase":"plan","status":"success","model":"nemotron","tokens_in":100,"tokens_out":50,"cost_usd":0.0001,"artifacts":["plan.md"],"gates_passed":["artifacts_exist"]}\n')
        
        count = reindex_all(jsonl_path, db_path)
        assert count == 2
        
        Session = get_session_factory(db_path)
        with Session() as session:
            events = session.query(TraceEvent).filter_by(run_id="TEST-1").all()
            assert len(events) == 2


if __name__ == "__main__":
    test_indexer_creates_tables_and_inserts()
    print("✓ test_indexer_creates_tables_and_inserts")
    
    test_incremental_indexing()
    print("✓ test_incremental_indexing")
    
    test_issue_number_extraction()
    print("✓ test_issue_number_extraction")
    
    test_reindex_all()
    print("✓ test_reindex_all")
    
    print("\nAll tests passed!")