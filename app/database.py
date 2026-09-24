from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Float
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
from config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(50), default="user")  # admin / user / readonly
    created_at = Column(DateTime, default=datetime.utcnow)


class ChatHistory(Base):
    __tablename__ = "chat_history"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), nullable=False)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    tokens_used = Column(Integer, default=0)
    latency_ms = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)


def init_db():
    """Create tables if they don't exist yet.

    `create_all` checks information_schema first, but that check-then-create
    is not atomic across processes: with multiple Uvicorn workers (each
    running this at startup), two workers can both see "table missing" and
    race to CREATE TABLE, and the loser hits a Postgres unique-violation on
    its own catalog sequence rather than a clean "already exists". Since the
    only possible cause of that specific error here is a concurrent sibling
    worker that's already creating the same schema, it's safe to swallow.
    """
    try:
        Base.metadata.create_all(bind=engine)
    except (IntegrityError, ProgrammingError):
        pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
