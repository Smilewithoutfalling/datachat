"""FastAPI 应用（阶段 4）。前端只通过这里的 HTTP / SSE 与后端交互（M22），不走 Tauri IPC。

接口（除 /health 外都要 Authorization: Bearer <token>；图表另可用 ?token=，方便 <img>）：
    GET    /health
    POST   /datasets                     multipart：files（一个或多个 CSV，可含 *.dict.csv 字典）、name
    GET    /datasets                     列表
    GET    /datasets/{id}                详情（含文件与每张表的列）
    DELETE /datasets/{id}
    POST   /sessions                     {"dataset_id", "agent": "workflow"|"react", "title"?}
    GET    /sessions                     列表（按更新时间倒序）
    GET    /sessions/{id}                会话 + 全部消息（每条助手消息带事件与结果）——"历史可查"
    DELETE /sessions/{id}
    POST   /sessions/{id}/messages       {"content"} → text/event-stream，逐条转发 analyze_stream 事件
    GET    /charts/{name}                图表 png
    GET    /settings  PUT /settings      非机密设置：model、base_url
    GET    /settings/api-key             {"configured", "source"}——从不返回 Key 本身
    PUT    /settings/api-key             {"api_key"} → 存进系统钥匙串
    DELETE /settings/api-key

安全（docs/THREAT_MODEL.md）：只监听 127.0.0.1；TrustedHost 只认 localhost / 127.0.0.1（挡 DNS rebinding）；
每次启动随机 token（挡本机网页对 localhost 的跨站请求）；不开 CORS，阶段 6 外壳确定后只放行外壳的源。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.server.db import ChatSession, Dataset, DatasetFile, EventRow, Message, Setting, make_sessionmaker, now

MAX_FILE_BYTES = 1024 * 1024 * 1024        # 单个文件 1 GB
MAX_FILES = 50
SETTING_KEYS = ("model", "base_url")
CHART_NAME = re.compile(r"^chart_[0-9_]+_[0-9a-f]{6}\.png$")


def default_home() -> str:
    """数据目录：DATACHAT_HOME；否则 Windows 用 %LOCALAPPDATA%\\datachat，其他系统 ~/.local/share/datachat。"""
    if os.getenv("DATACHAT_HOME"):
        return os.getenv("DATACHAT_HOME")
    base = os.getenv("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "datachat")


class SessionIn(BaseModel):
    dataset_id: str
    agent: str = "workflow"
    title: str = ""


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class SettingsIn(BaseModel):
    model: Optional[str] = None
    base_url: Optional[str] = None


class ApiKeyIn(BaseModel):
    api_key: str = Field(min_length=1, max_length=512)


def create_app(home: str | None = None, token: str | None = None, *, chat_model_factory=None,
               analyze_kwargs: dict | None = None) -> FastAPI:
    """home：数据目录（SQLite、上传文件、图表）。token：None 时随机生成，见 app.state.token。
    chat_model_factory：测试用，() -> ChatModel；None 时按设置和钥匙串构造真实模型。
    analyze_kwargs：透传给 analyze_stream 的额外参数（测试用，如 recursion_limit）。"""
    from app.core import AGENTS, LLMConfig, analyze_stream
    from app.core import keystore
    from app.tools import persist

    home = os.path.abspath(home or default_home())
    for d in ("datasets", "charts"):
        os.makedirs(os.path.join(home, d), exist_ok=True)
    persist.CHART_DIR = os.path.join(home, "charts")
    Session = make_sessionmaker(os.path.join(home, "datachat.db"))
    token = token or secrets.token_urlsafe(32)

    # 上次进程被杀时还在跑的消息，标成 cancelled
    with Session() as db:
        for m in db.scalars(select(Message).where(Message.status == "running")):
            m.status, m.content = "cancelled", m.content or "后端重启，分析中断"
        db.commit()

    app = FastAPI(title="datachat", version="0.4")
    app.state.token, app.state.home = token, home
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    def auth(request: Request):
        h = request.headers.get("authorization", "")
        if h.lower().startswith("bearer "):
            given = h[7:]
        elif request.url.path.startswith("/charts/"):
            # 只有图表接受 ?token=（<img src> 带不了请求头）；其他接口一律要请求头，
            # 免得 token 跟着 URL 进浏览器历史、Referer 和访问日志
            given = request.query_params.get("token", "")
        else:
            given = ""
        if not secrets.compare_digest(given.encode(), token.encode()):
            raise HTTPException(401, "token 无效")

    def db_dep():
        with Session() as db:
            yield db

    def get_or_404(db, model, id_):
        obj = db.get(model, id_)
        if obj is None:
            raise HTTPException(404, f"{model.__name__} 不存在：{id_}")
        return obj

    def chart_url(path):
        return f"/charts/{os.path.basename(path)}" if path else None

    def public_event(d: dict) -> dict:
        """事件对外：图表本地路径换成 URL。"""
        data = d["data"]
        if data.get("chart"):
            data["chart"] = chart_url(data["chart"])
        if d["type"] == "done" and "result" in data:
            data["result"] = public_result(data["result"])
        return d

    def public_result(r: dict) -> dict:
        r = dict(r)
        r["chart_path"] = chart_url(r.get("chart_path"))
        r["charts"] = [chart_url(p) for p in r.get("charts") or []]
        r.pop("dataset", None)          # 本地绝对路径不外发
        return r

    def dataset_out(ds: Dataset, detail=False):
        out = {"id": ds.id, "name": ds.name, "created_at": ds.created_at,
               "files": [{"filename": f.filename, "size": f.size, "sha256": f.sha256} for f in ds.files]}
        if detail:
            from app.tools.dataset import load_data
            try:
                data, desc = load_data(dataset_target(ds))
                tables = data if isinstance(data, dict) else {"df": data}
                out["tables"] = {k: [str(c) for c in v.columns] for k, v in tables.items()}
                out["summary"] = desc
            except Exception as e:  # noqa: BLE001
                out["error"] = f"{type(e).__name__}: {e}"
        return out

    def dataset_target(ds: Dataset) -> str:
        """单表 → CSV 路径（同目录的同名 .dict.csv 自动作字典）；多表 → 目录。"""
        tables = [f for f in ds.files if not f.filename.lower().endswith(".dict.csv")]
        return tables[0].path if len(tables) == 1 else os.path.dirname(ds.files[0].path)

    def message_out(m: Message):
        out = {"id": m.id, "role": m.role, "content": m.content, "status": m.status, "created_at": m.created_at}
        if m.role == "assistant":
            out["events"] = [public_event({"type": e.type, "trace_id": m.id, "seq": e.seq, "ts": e.ts,
                                           "data": json.loads(e.data_json)}) for e in m.events]
            out["result"] = public_result(json.loads(m.result_json)) if m.result_json else None
        return out

    def session_out(s: ChatSession):
        return {"id": s.id, "dataset_id": s.dataset_id, "agent": s.agent, "title": s.title,
                "created_at": s.created_at, "updated_at": s.updated_at}

    def turn_history(messages):
        """ReAct 多轮上下文从 messages 表重建（重启不丢）：只取成功的轮次（user + 紧跟的 ok 助手消息）；
        失败 / 取消的轮次不进上下文——用户通常会换个说法重问。"""
        out = []
        for q, a in zip(messages, messages[1:]):
            if q.role == "user" and a.role == "assistant" and a.status == "ok":
                out.append((q.content, a.content))
        return out

    def llm_config():
        with Session() as db:
            st = {r.key: r.value for r in db.scalars(select(Setting))}
        return LLMConfig.from_env(**{k: v for k, v in st.items() if k in SETTING_KEYS and v})

    # ------------------------------------------------------------------ 路由
    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/datasets", dependencies=[Depends(auth)])
    def create_dataset(files: list[UploadFile] = File(...), name: str = Form(""), db=Depends(db_dep)):
        if not files or len(files) > MAX_FILES:
            raise HTTPException(400, f"需要 1–{MAX_FILES} 个文件")
        names = []
        for f in files:
            fn = os.path.basename((f.filename or "").replace("\\", "/"))
            if not fn or fn.startswith(".") or not fn.lower().endswith(".csv"):
                raise HTTPException(400, f"只支持 CSV 文件：{f.filename!r}")
            if fn.lower() in {n.lower() for n in names}:
                raise HTTPException(400, f"文件名重复：{fn}")
            names.append(fn)
        if all(n.lower().endswith(".dict.csv") for n in names):
            raise HTTPException(400, "只有字典文件，没有数据表")
        ds = Dataset(name=name.strip() or names[0])
        db.add(ds)
        db.flush()
        folder = os.path.join(home, "datasets", ds.id)
        os.makedirs(folder)
        try:
            for f, fn in zip(files, names):
                path, h, size = os.path.join(folder, fn), hashlib.sha256(), 0
                with open(path, "wb") as out:
                    while chunk := f.file.read(1024 * 1024):
                        size += len(chunk)
                        if size > MAX_FILE_BYTES:
                            raise HTTPException(413, f"文件超过 {MAX_FILE_BYTES // 1024 ** 2} MB：{fn}")
                        h.update(chunk)
                        out.write(chunk)
                ds.files.append(DatasetFile(filename=fn, path=path, size=size, sha256=h.hexdigest()))
            db.commit()
        except BaseException:
            db.rollback()
            shutil.rmtree(folder, ignore_errors=True)
            raise
        return dataset_out(ds, detail=True)

    @app.get("/datasets", dependencies=[Depends(auth)])
    def list_datasets(db=Depends(db_dep)):
        return [dataset_out(d) for d in db.scalars(select(Dataset).order_by(Dataset.created_at.desc()))]

    @app.get("/datasets/{dataset_id}", dependencies=[Depends(auth)])
    def get_dataset(dataset_id: str, db=Depends(db_dep)):
        return dataset_out(get_or_404(db, Dataset, dataset_id), detail=True)

    @app.delete("/datasets/{dataset_id}", dependencies=[Depends(auth)])
    def delete_dataset(dataset_id: str, db=Depends(db_dep)):
        ds = get_or_404(db, Dataset, dataset_id)
        db.delete(ds)
        db.commit()
        shutil.rmtree(os.path.join(home, "datasets", dataset_id), ignore_errors=True)
        return {"ok": True}

    @app.post("/sessions", dependencies=[Depends(auth)])
    def create_session(body: SessionIn, db=Depends(db_dep)):
        if body.agent not in AGENTS:
            raise HTTPException(400, f"agent 只能是 {AGENTS}")
        get_or_404(db, Dataset, body.dataset_id)
        s = ChatSession(dataset_id=body.dataset_id, agent=body.agent, title=body.title)
        db.add(s)
        db.commit()
        return session_out(s)

    @app.get("/sessions", dependencies=[Depends(auth)])
    def list_sessions(db=Depends(db_dep)):
        return [session_out(s) for s in db.scalars(select(ChatSession).order_by(ChatSession.updated_at.desc()))]

    @app.get("/sessions/{session_id}", dependencies=[Depends(auth)])
    def get_session(session_id: str, db=Depends(db_dep)):
        s = get_or_404(db, ChatSession, session_id)
        return {**session_out(s), "messages": [message_out(m) for m in s.messages]}

    @app.delete("/sessions/{session_id}", dependencies=[Depends(auth)])
    def delete_session(session_id: str, db=Depends(db_dep)):
        db.delete(get_or_404(db, ChatSession, session_id))
        db.commit()
        return {"ok": True}

    @app.post("/sessions/{session_id}/messages", dependencies=[Depends(auth)])
    def post_message(session_id: str, body: MessageIn, db=Depends(db_dep)):
        s = get_or_404(db, ChatSession, session_id)
        if db.scalar(select(Message).where(Message.session_id == session_id, Message.status == "running")):
            raise HTTPException(409, "这个会话还有一条消息在分析中")
        target = dataset_target(get_or_404(db, Dataset, s.dataset_id))
        agent = s.agent
        history = turn_history(s.messages) if agent == "react" else None
        q = Message(session_id=session_id, role="user", content=body.content, created_at=now())
        a = Message(session_id=session_id, role="assistant", status="running", created_at=now())
        db.add_all([q, a])
        if not s.title:
            s.title = body.content[:60]
        s.updated_at = now()
        db.commit()
        msg_id = a.id

        kwargs = dict(agent=agent, trace_id=msg_id, log=False, **(analyze_kwargs or {}))
        if chat_model_factory is not None:
            kwargs["chat_model"] = chat_model_factory()
        else:
            kwargs["llm_config"] = llm_config()
        if history:
            kwargs["history"] = history

        def stream():
            status, content, result_json = "cancelled", "已取消", None
            try:
                with Session() as wdb:
                    for ev in analyze_stream(target, body.content, **kwargs):
                        d = ev.to_dict()
                        if ev.type == "done":
                            r = ev.result
                            status = "ok" if r.ok else "error"
                            content = r.answer if r.ok else (r.error or "")
                            result_json = json.dumps(d["data"]["result"], ensure_ascii=False, default=str)
                        else:
                            wdb.add(EventRow(message_id=msg_id, seq=ev.seq, type=ev.type, ts=str(ev.ts),
                                             data_json=json.dumps(d["data"], ensure_ascii=False, default=str)))
                            wdb.commit()
                        yield (f"id: {ev.seq}\nevent: {ev.type}\n"
                               f"data: {json.dumps(public_event(d), ensure_ascii=False, default=str)}\n\n")
            finally:
                with Session() as fdb:
                    m = fdb.get(Message, msg_id)
                    if m is not None:
                        m.status, m.content, m.result_json = status, content, result_json
                        fdb.commit()

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Message-Id": msg_id,
                                          "X-User-Message-Id": q.id})

    @app.get("/charts/{name}", dependencies=[Depends(auth)])
    def get_chart(name: str):
        path = os.path.join(persist.CHART_DIR, name)
        if not CHART_NAME.match(name) or not os.path.isfile(path):
            raise HTTPException(404, "图表不存在")
        return FileResponse(path, media_type="image/png")

    @app.get("/settings", dependencies=[Depends(auth)])
    def get_settings(db=Depends(db_dep)):
        st = {r.key: r.value for r in db.scalars(select(Setting))}
        cfg = llm_config()
        return {"model": st.get("model") or cfg.model, "base_url": st.get("base_url") or cfg.base_url}

    @app.put("/settings", dependencies=[Depends(auth)])
    def put_settings(body: SettingsIn, db=Depends(db_dep)):
        for k, v in body.model_dump(exclude_none=True).items():
            row = db.get(Setting, k)
            if row is None:
                db.add(Setting(key=k, value=v.strip()))
            else:
                row.value = v.strip()
        db.commit()
        return get_settings(db)

    @app.get("/settings/api-key", dependencies=[Depends(auth)])
    def get_api_key_status():
        _, src = keystore.resolve_api_key()
        return {"configured": src is not None, "source": src}

    @app.put("/settings/api-key", dependencies=[Depends(auth)])
    def put_api_key(body: ApiKeyIn):
        try:
            keystore.set_api_key(body.api_key)
        except keystore.KeyStoreError as e:
            raise HTTPException(400, str(e)) from None
        return get_api_key_status()

    @app.delete("/settings/api-key", dependencies=[Depends(auth)])
    def delete_api_key():
        try:
            keystore.delete_api_key()
        except keystore.KeyStoreError as e:
            raise HTTPException(400, str(e)) from None
        return get_api_key_status()

    return app
