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


# running 分析中；ok / error 分析结束；cancelled 用户点了停止；interrupted 非用户动作的终止（后端重启、客户端断开）（阶段 5 F2）
MESSAGE_STATUSES = ("running", "ok", "error", "cancelled", "interrupted")

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
    # 语义是"最后一次提问时间"：只在 post_message 里更新，会话列表按它倒序（界面写明"按最近分析时间排序"）。
    # 改名（PATCH /sessions/{id}）刻意不更新——否则改个名就顶到最前，"最近分析"排序失真。
    # 故意没有 onupdate；改字段名要迁移，先用这条注释钉住（tests/test_web_f1.py 有回归测试）。
    updated_at: Mapped[str] = mapped_column(String(40), default=now)
    messages: Mapped[list["Message"]] = relationship(back_populates="session", cascade="all, delete-orphan",
                                                     order_by="Message.created_at")


class Message(Base):
    """role=user：content 是问题。role=assistant：content 是结论（失败时为错误信息），
    status 见 MESSAGE_STATUSES，result_json 是 AnalysisResult.to_record()，id 即 trace_id。"""
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
    feedback: Mapped[Optional["Feedback"]] = relationship(back_populates="message", cascade="all, delete-orphan",
                                                          uselist=False)


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


class Feedback(Base):
    """助手消息的 👍👎（阶段 5 F0）。单独成表而不是给 messages 加列：create_all 只会建缺的表、
    不会给已有表加列，旧库启动后这张表自动出现，旧表不动（不需要迁移）。
    一条消息至多一行（message_id 即主键）；rating 取 up / down / None——撤销评价时保留这一行（note 可能还有用），
    不记改评价的历史。note 是用户输入，前端按纯文本渲染（THREAT_MODEL T9）。"""
    __tablename__ = "feedback"
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True)
    rating: Mapped[Optional[str]] = mapped_column(String(8), default=None)
    note: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[str] = mapped_column(String(40), default=now)
    message: Mapped[Message] = relationship(back_populates="feedback")


class Setting(Base):
    """非机密设置（模型名、base_url 等）。API Key 不在这里，在系统钥匙串（app/core/keystore.py）。
    阶段 6.5 起另有 active_connection（生效连接 id）、connections_migrated（§4 迁移只跑一次的标记）、
    env_probe（没有连接时「环境变量」虚拟连接的最近一次测试）。"""
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class Connection(Base):
    """模型连接（阶段 6.5 §3）：用户命名，同一服务商可以建多个；同一时间只有一个生效（settings.active_connection）。
    Key 不在这里，在系统钥匙串 ACCOUNT=conn:<id>（app/core/keystore.py conn_account）。新表：create_all 自动建，旧表不动。
    extra：JSON，Azure 的 deployment / api_version、怪癖覆盖 quirks、thinking 开关。
    probe：JSON，最近一次测试 {model, connect, tools, checked_at}；model 和当前 model 不同就算没测过。"""
    __tablename__ = "connections"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    provider: Mapped[str] = mapped_column(String(32))
    protocol: Mapped[str] = mapped_column(String(32))
    base_url: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(200), default="")
    extra: Mapped[str] = mapped_column(Text, default="{}")
    probe: Mapped[Optional[str]] = mapped_column(Text, default=None)
    created_at: Mapped[str] = mapped_column(String(40), default=now)
    updated_at: Mapped[str] = mapped_column(String(40), default=now)


def make_sessionmaker(db_path: str):
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        # 阶段 6.6 M0：必须在 journal_mode=WAL 之前——切 WAL 会写库头，之后新库的 auto_vacuum 就定成 NONE 了。
        # 对已有表的旧库这句是空操作（要配合一次 VACUUM 才生效，见 retention.prepare_auto_vacuum）。
        cur.execute("PRAGMA auto_vacuum=INCREMENTAL")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

    # 阶段 6.6 M0：旧库（auto_vacuum=NONE）按空闲页比例在这里转换一次——此时还没开始监听，没有并发写。
    # 结果记在 engine.info["auto_vacuum"]，测试与日志用。
    from app.server.retention import prepare_auto_vacuum
    with engine.connect() as c:
        engine.info = getattr(engine, "info", {})
        engine.info["auto_vacuum"] = prepare_auto_vacuum(c.connection.driver_connection, db_path)
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)
