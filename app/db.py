"""
Veritabanı katmanı.

Varsayılan: SQLite (dosya tabanlı, sıfır kurulum).
PostgreSQL'e geçmek için DATABASE_URL ortam değişkenini şu şekilde ayarlayın:
    postgresql+asyncpg://user:password@localhost:5432/subrecon
ve requirements.txt'ye `asyncpg` ekleyin.
"""
import os
from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, DateTime, ForeignKey, Text, Boolean
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite+aiosqlite:///./data/subrecon.db",
)

engine = create_async_engine(DATABASE_URL, echo=False, future=True)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

Base = declarative_base()


class Scan(Base):
    __tablename__ = "scans"

    id = Column(Integer, primary_key=True, index=True)
    domain = Column(String, index=True, nullable=False)
    wordlist_size = Column(Integer, default=0)
    concurrency = Column(Integer, default=50)
    qps = Column(Integer, default=20)
    wildcard_detected = Column(Boolean, default=False)
    wildcard_ip = Column(String, nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    total_checked = Column(Integer, default=0)
    total_found = Column(Integer, default=0)

    results = relationship("SubdomainResult", back_populates="scan", cascade="all, delete-orphan")


class SubdomainResult(Base):
    __tablename__ = "subdomain_results"

    id = Column(Integer, primary_key=True, index=True)
    scan_id = Column(Integer, ForeignKey("scans.id"), nullable=False)
    subdomain = Column(String, index=True, nullable=False)
    record_type = Column(String, nullable=False)  # A / AAAA / CNAME
    ip_or_target = Column(String, nullable=False)
    cname_chain = Column(Text, nullable=True)      # virgülle ayrılmış zincir
    is_wildcard_match = Column(Boolean, default=False)
    is_new = Column(Boolean, default=False)         # önceki taramaya göre yeni mi
    discovered_at = Column(DateTime, default=datetime.utcnow)

    scan = relationship("Scan", back_populates="results")


async def init_db():
    os.makedirs("./data", exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session
