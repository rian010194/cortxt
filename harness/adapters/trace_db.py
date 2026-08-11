"""SQLAlchemy models for trace database."""

from sqlalchemy import Column, String, Integer, Float, DateTime, Text, create_engine, Index
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
from contextlib import contextmanager
from pathlib import Path
import json

Base = declarative_base()

class TraceEvent(Base):
    __tablename__ = "trace_events"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    ts = Column(DateTime, nullable=False, index=True)
    run_id = Column(String(64), nullable=False, index=True)
    profile = Column(String(32), nullable=False, index=True)
    phase = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False)
    model = Column(String(64), default="")
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    artifacts = Column(Text, default="[]")
    gates_passed = Column(Text, default="[]")
    error = Column(Text, nullable=True)
    issue_number = Column(Integer, nullable=True, index=True)  # extracted from run_id GH-{issue}-{uuid}
    line_number = Column(Integer, default=0, nullable=False)  # for incremental indexing

    def to_dict(self):
        return {
            "id": self.id,
            "ts": self.ts.isoformat() + "Z" if self.ts else None,
            "run_id": self.run_id,
            "profile": self.profile,
            "phase": self.phase,
            "status": self.status,
            "model": self.model,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": self.cost_usd,
            "artifacts": json.loads(self.artifacts) if self.artifacts else [],
            "gates_passed": json.loads(self.gates_passed) if self.gates_passed else [],
            "error": self.error,
            "issue_number": self.issue_number,
        }

# Composite indexes for common queries
Index("ix_run_profile_phase", TraceEvent.run_id, TraceEvent.profile, TraceEvent.phase)
Index("ix_run_ts", TraceEvent.run_id, TraceEvent.ts)


def init_db(db_path: str):
    """Initialize database with WAL mode for concurrent reads."""
    # Ensure directory exists
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    
    engine = create_engine(
        f"sqlite:///{db_path}?check_same_thread=False",
        connect_args={"check_same_thread": False, "timeout": 30},
        pool_pre_ping=True,
    )
    
    # Enable WAL mode
    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
        conn.execute(text("PRAGMA busy_timeout=30000"))
        conn.commit()
    
    Base.metadata.create_all(engine)
    return engine


def get_session_factory(db_path: str):
    """Get a session factory for the database."""
    engine = init_db(db_path)
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope(db_path: str):
    """Provide a transactional scope around a series of operations."""
    Session = get_session_factory(db_path)
    session = Session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def extract_issue_number(run_id: str) -> int | None:
    """Extract issue number from run_id pattern GH-{issue}-{uuid}."""
    try:
        if run_id.startswith("GH-"):
            parts = run_id.split("-")
            if len(parts) >= 2:
                return int(parts[1])
    except (ValueError, IndexError):
        pass
    return None


# Need to import text for PRAGMA
from sqlalchemy import text