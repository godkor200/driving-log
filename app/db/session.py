import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./driving_log.db")

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=_connect_args, echo=False)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """테이블 생성 — 앱 시작 시 1회 호출"""
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI Depends용 DB 세션 제너레이터"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
