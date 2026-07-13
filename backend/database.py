import os
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from config import Config

config = Config()
os.makedirs(os.path.dirname(config.db_path), exist_ok=True)

# The watcher and the api run as two separate processes sharing this one
# SQLite file — the watcher writes events continuously, the api reads them
# for every dashboard poll. With SQLite's default busy timeout of 0, a read
# that lands while the watcher holds the write lock fails instantly with
# "database is locked", which the dashboard sees as a flickering failed fetch.
#   - timeout=30: wait up to 30s for a lock instead of erroring immediately.
#   - WAL journal mode (set below): lets readers proceed WITHOUT blocking on
#     an in-progress write, which is exactly our watcher-writes/api-reads
#     access pattern.
engine = create_engine(
    f"sqlite:///{config.db_path}",
    connect_args={"check_same_thread": False, "timeout": 30},
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_conn, _connection_record):
    # Applied to every new connection. WAL is persisted on the DB file once
    # set, but re-issuing it per-connection is harmless and covers a fresh DB.
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()


SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    activity = Column(String, nullable=False)
    confidence = Column(Float, default=1.0)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))


Base.metadata.create_all(bind=engine)


def log_event(db: Session, activity: str, confidence: float = 1.0) -> Event:
    event = Event(activity=activity, confidence=confidence, timestamp=datetime.now(timezone.utc))
    db.add(event)
    db.commit()
    db.refresh(event)
    return event
