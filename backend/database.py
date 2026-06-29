import os
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from config import Config

config = Config()
os.makedirs(os.path.dirname(config.db_path), exist_ok=True)

engine = create_engine(f"sqlite:///{config.db_path}", connect_args={"check_same_thread": False})
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
