"""SQLite 持久化（SQLAlchemy 2.0）。表结构只用通用类型，以后换 PostgreSQL 不改模型；
各表预留 user_id（桌面端单用户，恒为 None），Web 阶段再启用。"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import ForeignKey, Integer, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


def new_id() -> str:
    return uuid.uuid4().hex


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Base(DeclarativeBase):
    pass


class Dataset(Base):
    __tablename__ = "datasets"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[Optional[str]] = mapped_column(String(64), index=True, default=None)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[str] = mapped_column(String(40), default=now)
    files: Mapped[list["DatasetFile"]] = relationship(back_populates="dataset", cascade="all, delete-orphan",
                                                       order_by="DatasetFile.filename")


class DatasetFile(Base):
    __tablename__ = "dataset_files"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    path: Mapped[str] = mapped_column(Text)
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(40), default=now)
    dataset: Mapped[Dataset] = relationship(back_populates="files")


class ChatSession(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[Optional[str]] = mapped_column(String(64), index=True, default=None)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    agent: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[str] = mapped_column(String(40), default=now)
    updated_at: Mapped[str] = mapped_column(String(40), default=now)
    messages: Mapped[list["Message"]] = relationship(back_populates="session", cascade="all, delete-orphan",
                                                     order_by="Message.created_at")


class Message(Base):
    """role=user：content 是问题。role=assistant：content 是结论（失败时为错误信息），
    status = running / ok / error / cancelled，result_json 是 AnalysisResult.to_record()，id 即 trace_id。"""
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="ok")
    result_json: Mapped[Optional[str]] = mapped_column(Text, default=None)
    created_at: Mapped[str] = mapped_column(String(40), default=now)
    session: Mapped[ChatSession] = relationship(back_populates="messages")
    events: Mapped[list["EventRow"]] = relationship(back_populates="message", cascade="all, delete-orphan",
                                                    order_by="EventRow.seq")


class EventRow(Base):
    """analyze_stream 的每个事件（done 除外：完整结果在 messages.result_json）。历史回放用。"""
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(16))
    ts: Mapped[str] = mapped_column(String(40))
    data_json: Mapped[str] = mapped_column(Text)
    message: Mapped[Message] = relationship(back_populates="events")


class Setting(Base):
    """非机密设置（模型名、base_url 等）。API Key 不在这里，在系统钥匙串（app/core/keystore.py）。"""
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


def make_sessionmaker(db_path: str):
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)
