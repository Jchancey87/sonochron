import os
import uuid
from datetime import datetime
from typing import List, Optional
from sqlmodel import SQLModel, Field, Relationship, Column, JSON, create_engine, Session, select
from sqlalchemy import UniqueConstraint, ForeignKey, CheckConstraint, event
from sqlalchemy.exc import IntegrityError, OperationalError

# Database connection details
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    DB_USER = os.getenv("DB_USER", "postgres")
    DB_PASS = os.getenv("DB_PASS", "postgres")
    DB_HOST = os.getenv("DB_HOST", "192.168.0.201")
    DB_PORT = os.getenv("DB_PORT", "5432")
    DB_NAME = os.getenv("DB_NAME", "sonochron")
    DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Setup database engine
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
    
    # Enable foreign key support for SQLite
    from sqlalchemy.engine import Engine
    @event.listens_for(Engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
else:
    engine = create_engine(DATABASE_URL, echo=True)

class YearArchive(SQLModel, table=True):
    """
    Groups diary entries by year.
    """
    __tablename__ = "year_archives"
    
    year: int = Field(primary_key=True, index=True)
    
    # Relationships
    months: List["MonthArchive"] = Relationship(
        back_populates="year_archive", 
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


class MonthArchive(SQLModel, table=True):
    """
    Groups diary entries by month under a specific year.
    Enforces uniqueness for the (year, month) combination.
    """
    __tablename__ = "month_archives"
    __table_args__ = (
        UniqueConstraint("year", "month", name="uq_year_month"),
        CheckConstraint("month >= 1 AND month <= 12", name="chk_month_range"),
    )
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    year: int = Field(
        sa_column_args=[ForeignKey("year_archives.year", ondelete="CASCADE")],
        index=True
    )
    month: int = Field(index=True)  # 1 to 12
    
    # Relationships
    year_archive: YearArchive = Relationship(back_populates="months")
    entries: List["DiaryEntry"] = Relationship(
        back_populates="month_archive",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


class DiaryEntry(SQLModel, table=True):
    """
    Canonical sound diary entry.
    """
    __tablename__ = "diary_entries"
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    local_capture_time: datetime = Field(index=True)
    utc_capture_time: Optional[datetime] = Field(default=None, index=True)
    title: Optional[str] = Field(default=None)
    stage: str = Field(default="uploaded", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    month_archive_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column_args=[ForeignKey("month_archives.id", ondelete="CASCADE")],
        index=True,
    )
    
    # Relationships
    month_archive: Optional[MonthArchive] = Relationship(back_populates="entries")
    context: Optional["EntryContext"] = Relationship(
        back_populates="entry",
        sa_relationship_kwargs={"uselist": False, "cascade": "all, delete-orphan"}
    )
    asset: Optional["SampleAsset"] = Relationship(
        back_populates="entry",
        sa_relationship_kwargs={"uselist": False, "cascade": "all, delete-orphan"}
    )
    idempotency_key: Optional["IdempotencyKey"] = Relationship(
        back_populates="entry",
        sa_relationship_kwargs={"uselist": False, "cascade": "all, delete-orphan"}
    )


class EntryContext(SQLModel, table=True):
    """
    Metadata associated with a diary entry.
    """
    __tablename__ = "entry_contexts"
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    entry_id: uuid.UUID = Field(
        sa_column_args=[ForeignKey("diary_entries.id", ondelete="CASCADE")],
        unique=True,
        index=True
    )
    
    mood: Optional[str] = Field(default=None)
    location: Optional[str] = Field(default=None)
    
    # Store lists as JSON
    companions: List[str] = Field(default=[], sa_column=Column(JSON))
    
    notes: Optional[str] = Field(default=None)
    
    # Relationships
    entry: DiaryEntry = Relationship(back_populates="context")


class SampleAsset(SQLModel, table=True):
    """
    Metadata about the stored audio sample.
    """
    __tablename__ = "sample_assets"
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    entry_id: uuid.UUID = Field(
        sa_column_args=[ForeignKey("diary_entries.id", ondelete="CASCADE")],
        unique=True,
        index=True
    )
    
    filename: str
    filepath: str
    checksum_sha256: Optional[str] = Field(default=None)
    byte_size: Optional[int] = Field(default=None)
    duration_ms: Optional[int] = Field(default=None)
    
    # Relationships
    entry: DiaryEntry = Relationship(back_populates="asset")


class IdempotencyKey(SQLModel, table=True):
    """
    Ensures API request idempotency.
    """
    __tablename__ = "idempotency_keys"
    
    key: str = Field(primary_key=True, index=True)
    entry_id: uuid.UUID = Field(
        sa_column_args=[ForeignKey("diary_entries.id", ondelete="CASCADE")],
        index=True
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    entry: DiaryEntry = Relationship(back_populates="idempotency_key")


def init_db():
    """Create all schema tables in database."""
    SQLModel.metadata.create_all(engine)


def get_session():
    """FastAPI Dependency for database sessions."""
    with Session(engine) as session:
        yield session


def get_or_create_month_archive(session: Session, dt: datetime) -> MonthArchive:
    """
    Resolves the month archive for the given date.
    Creates YearArchive and MonthArchive objects if they do not exist.
    """
    year_val = dt.year
    month_val = dt.month
    
    # Check or create YearArchive
    year_archive = session.get(YearArchive, year_val)
    if not year_archive:
        try:
            with session.begin_nested():
                year_archive = YearArchive(year=year_val)
                session.add(year_archive)
                session.flush()
        except (IntegrityError, OperationalError):
            # Resolve existing
            year_archive = session.get(YearArchive, year_val)
            if not year_archive:
                raise
        
    # Check or create MonthArchive
    statement = select(MonthArchive).where(
        MonthArchive.year == year_val,
        MonthArchive.month == month_val
    )
    month_archive = session.exec(statement).first()
    if not month_archive:
        try:
            with session.begin_nested():
                month_archive = MonthArchive(year=year_val, month=month_val)
                session.add(month_archive)
                session.flush()
        except (IntegrityError, OperationalError):
            # Resolve existing
            statement = select(MonthArchive).where(
                MonthArchive.year == year_val,
                MonthArchive.month == month_val
            )
            month_archive = session.exec(statement).first()
            if not month_archive:
                raise
        
    return month_archive
