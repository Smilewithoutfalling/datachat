"""FastAPI 应用（阶段 4）。前端只通过这里的 HTTP / SSE 与后端交互（M22），不走 Tauri IPC。

接口（除 /health 和前端静态文件外都要 Authorization: Bearer <token>；图表另可用 ?token=，方便 <img>）：
    GET    /health
    POST   /datasets                     multipart：files（一个或多个 CSV，可含 *.dict.csv 字典）、name
    GET    /datasets                     列表
    GET    /datasets/{id}?rows=20        详情（文件、每张表的列与概要）；带 rows（1–100）时加每张表前 N 行预览，
                                         单元格一律字符串或 null（阶段 5 F1.1：预览与详情合并，每个文件只读一遍）
    DELETE /datasets/{id}
    POST   /sessions                     {"dataset_id", "agent": "workflow"|"react", "title"?}
    GET    /sessions                     列表（按更新时间倒序）
    PATCH  /sessions/{id}                {"title"} 改名（阶段 5 F1）
    GET    /sessions/{id}                会话 + 全部消息（每条助手消息带事件与结果）——"历史可查"
    DELETE /sessions/{id}
    POST   /sessions/{id}/messages       {"content"} → text/event-stream，逐条转发 analyze_stream 事件
    GET    /charts/{name}                图表 png
    PUT    /messages/{id}/feedback       {"rating": "up"|"down"|null, "note"?}（只限已结束的助手消息）
    GET    /  、/assets/*                前端（ui/web 构建产物）。不要 token——页面本身不含机密，token 由
                                         URL fragment 交给前端；index.html 带 CSP（阶段 5 F0）
    GET    /settings  PUT /settings      非机密设置：model、base_url、timeout（单次请求超时，秒）
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
import sys
from typing import Literal, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.server.db import ChatSession, Dataset, DatasetFile, EventRow, Feedback, Message, Setting, make_sessionmaker, now

MAX_FILE_BYTES = 1024 * 1024 * 1024        # 单个文件 1 GB
MAX_FILES = 50
SETTING_KEYS = ("model", "base_url", "timeout")
TIMEOUT_RANGE = (5.0, 600.0)
PREVIEW_MAX_ROWS = 100
PREVIEW_DEFAULT_ROWS = 20    # 上传后随响应带回的预览行数
PREVIEW_CELL_MAX = 200       # 单元格超长截断（按文本渲染，T9）
CHART_NAME = re.compile(r"^chart_[0-9_]+_[0-9a-f]{6}\.png$")
FEEDBACK_NOTE_MAX = 1000
# 去掉控制字符（保留 \t \n）和双向文本控制符：note 会原样回显到前端（THREAT_MODEL T9）
# 方向控制符（LRM/RLM、嵌入 / 覆盖、隔离）：数据里没有合法用途，却能让后面的文本视觉重排（THREAT_MODEL §2.3）
_BIDI = "\u200e\u200f\u202a-\u202e\u2066-\u2069"
_BIDI_CONTROLS = re.compile(f"[{_BIDI}]")
# 标题、note：C0/C1 控制字符（保留 \t \n）+ 方向控制符。预览只用 _BIDI_CONTROLS（数据里 \r \t \n 合法）
_CONTROL_CHARS = re.compile(f"[\x00-\x08\x0b-\x1f\x7f-\x9f{_BIDI}]")
# index.html 的内容安全策略（阶段 5 方案 §1）。构建产物里不能有内联 <script>（CI 检查），所以 script-src 只要 'self'；
# ECharts / React 会写行内 style，故 style-src 带 'unsafe-inline'；图表导出用 data: / blob:。
CSP = ("default-src 'self'; img-src 'self' data: blob:; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; object-src 'none'")


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


class SessionPatch(BaseModel):
    title: str = Field(max_length=200)


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class SettingsIn(BaseModel):
    model: Optional[str] = Field(None, max_length=200)
    base_url: Optional[str] = Field(None, max_length=500)
    timeout: Optional[float] = Field(None, ge=TIMEOUT_RANGE[0], le=TIMEOUT_RANGE[1])


class FeedbackIn(BaseModel):
    rating: Optional[Literal["up", "down"]] = None
    note: str = Field("", max_length=FEEDBACK_NOTE_MAX)


class ApiKeyIn(BaseModel):
    api_key: str = Field(min_length=1, max_length=512)


def default_web_dist() -> str:
    """前端构建产物目录：DATACHAT_WEB_DIST；PyInstaller 打包后是 _internal/web；源码环境是 ui/web/dist。"""
    if os.getenv("DATACHAT_WEB_DIST"):
        return os.getenv("DATACHAT_WEB_DIST")
    if getattr(sys, "frozen", False):
        return os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)), "web")
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, "ui", "web", "dist")


def create_app(home: str | None = None, token: str | None = None, *, chat_model_factory=None,
               analyze_kwargs: dict | None = None, web_dist: str | None = None) -> FastAPI:
    """home：数据目录（SQLite、上传文件、图表）。token：None 时随机生成，见 app.state.token。
    web_dist：前端构建产物目录，默认 default_web_dist()；目录不存在时 / 返回 503 提示先构建。
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

    def public_chart(c) -> dict:
        """图表条目对外：{"png": URL 或 None, "option": spec 或 None}。[26] 之前存的记录是 PNG 路径字符串，按 PNG 处理。"""
        if isinstance(c, str):
            return {"png": chart_url(c), "option": None}
        return {"png": chart_url(c.get("png")), "option": c.get("option")}

    def public_result(r: dict) -> dict:
        r = dict(r)
        r["chart_path"] = chart_url(r.get("chart_path"))
        r["charts"] = [public_chart(c) for c in r.get("charts") or []]
        r.pop("dataset", None)          # 本地绝对路径不外发
        return r

    def dataset_out(ds: Dataset, detail=False, rows: int | None = None):
        """detail：读每张表，给出列名、概要；rows 不为 None 时再带每张表前 rows 行预览。
        表的枚举直接用分析路径的 table_paths（表名、排序、字典过滤、重名检查与 load_data 结构性一致），
        但逐表 try：一张读坏只在该表报 error，不影响其他表的列名和预览。每个文件只读一遍。"""
        out = {"id": ds.id, "name": ds.name, "created_at": ds.created_at,
               "files": [{"filename": f.filename, "size": f.size, "sha256": f.sha256} for f in ds.files]}
        if not detail:
            return out
        from app.tools.csv_io import read_csv_with_encoding
        from app.tools.dataset import is_dict_file, table_paths
        target = dataset_target(ds)
        try:
            tp = table_paths(target)
        except Exception as e:  # noqa: BLE001 —— 目录空、表名重复：分析同样会失败
            out["error"] = f"{type(e).__name__}: {e}"
            return out
        multi = tp is not None
        cols, parts, errors, previews = {}, [], [], []
        for name, path in tp or [("df", target)]:
            filename = os.path.basename(path)
            try:
                df, enc = read_csv_with_encoding(path)
            except Exception as e:  # noqa: BLE001
                msg = f"{type(e).__name__}: {e}"
                errors.append(f"{filename}：{msg}")
                parts.append(f"{name} 读取失败")
                previews.append({"name": name, "filename": filename, "error": msg})
                continue
            cols[name] = [str(c) for c in df.columns]
            parts.append(f"{name} {len(df)}×{len(df.columns)}（{enc}）" if multi
                         else f"{len(df)} 行 × {len(df.columns)} 列，编码 {enc}")
            if rows is not None:
                previews.append(preview_table(name, filename, df, enc, rows))
            del df
        out["tables"] = cols
        out["summary"] = (f"{len(parts)} 张表：" + "，".join(parts)) if multi else parts[0]
        if errors:                       # 任一张读坏，分析（load_data）整体会失败，所以在顶层也报
            out["error"] = "；".join(errors)
        if rows is not None:
            out["preview"] = {"rows": rows, "tables": previews,
                              "dicts": sorted(f.filename for f in ds.files if is_dict_file(f.filename))}
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
            out["feedback"] = {"rating": m.feedback.rating, "note": m.feedback.note} if m.feedback else None
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
        over = {k: v for k, v in st.items() if k in SETTING_KEYS and v}
        if "timeout" in over:
            try:
                over["timeout"] = float(over["timeout"])
            except ValueError:
                over.pop("timeout")          # 库里的坏值不让分析整个起不来，退回环境变量 / 默认
        return LLMConfig.from_env(**over)

    def preview_cell(v, stats):
        """预览单元格：缺失 → None；其余转字符串，去掉方向控制符（只影响显示，模型拿到的仍是原数据），
        超长截断。计数记进 stats，前端在提示行告诉用户。前端按文本渲染（THREAT_MODEL T9）。"""
        import pandas as pd
        try:
            if pd.isna(v):
                return None
        except (TypeError, ValueError):     # 列表之类的非标量
            pass
        s, n = _BIDI_CONTROLS.subn("", str(v))
        stats["bidi_stripped"] += n
        if len(s) > PREVIEW_CELL_MAX:
            stats["truncated_cells"] += 1
            s = s[:PREVIEW_CELL_MAX] + "…"
        return s

    def preview_table(name, filename, df, enc, rows):
        stats = {"bidi_stripped": 0, "truncated_cells": 0}
        columns = [preview_cell(c, stats) or "" for c in df.columns]
        body = [[preview_cell(v, stats) for v in r] for r in df.head(rows).itertuples(index=False, name=None)]
        return {"name": name, "filename": filename, "encoding": enc,
                "total_rows": int(len(df)), "total_columns": int(len(df.columns)),
                "columns": columns, "dtypes": [str(t) for t in df.dtypes], "rows": body, **stats}

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
        return dataset_out(ds, detail=True, rows=PREVIEW_DEFAULT_ROWS)

    @app.get("/datasets", dependencies=[Depends(auth)])
    def list_datasets(db=Depends(db_dep)):
        return [dataset_out(d) for d in db.scalars(select(Dataset).order_by(Dataset.created_at.desc()))]

    @app.get("/datasets/{dataset_id}", dependencies=[Depends(auth)])
    def get_dataset(dataset_id: str, rows: int | None = Query(None, ge=1, le=PREVIEW_MAX_ROWS), db=Depends(db_dep)):
        """rows：带上就附每张表前 rows 行预览（越界、非整数都是 422）。"""
        return dataset_out(get_or_404(db, Dataset, dataset_id), detail=True, rows=rows)

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

    @app.patch("/sessions/{session_id}", dependencies=[Depends(auth)])
    def rename_session(session_id: str, body: SessionPatch, db=Depends(db_dep)):
        s = get_or_404(db, ChatSession, session_id)
        s.title = _CONTROL_CHARS.sub("", body.title).strip()[:120]
        db.commit()
        return session_out(s)

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

    @app.put("/messages/{message_id}/feedback", dependencies=[Depends(auth)])
    def put_feedback(message_id: str, body: FeedbackIn, db=Depends(db_dep)):
        m = get_or_404(db, Message, message_id)
        if m.role != "assistant":
            raise HTTPException(400, "只能评价助手消息")
        if m.status == "running":
            raise HTTPException(409, "这条消息还在分析中")
        note = _CONTROL_CHARS.sub("", body.note).strip()
        fb = m.feedback or Feedback(message_id=m.id)
        fb.rating, fb.note, fb.updated_at = body.rating, note, now()
        m.feedback = fb
        db.commit()
        return {"message_id": m.id, "rating": fb.rating, "note": fb.note}

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
        return {"model": st.get("model") or cfg.model, "base_url": st.get("base_url") or cfg.base_url,
                "timeout": cfg.timeout}

    @app.put("/settings", dependencies=[Depends(auth)])
    def put_settings(body: SettingsIn, db=Depends(db_dep)):
        for k, v in body.model_dump(exclude_none=True).items():
            v = str(v).strip()               # 空串 = 清除，回到环境变量 / 默认
            row = db.get(Setting, k)
            if row is None:
                db.add(Setting(key=k, value=v))
            else:
                row.value = v
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

    # ------------------------------------------------------------------ 前端静态文件（不要 token）
    # 边界：只有 / 和 /assets/* 免 token。页面和 JS 不含机密；token 只经 URL fragment（不发给服务器、
    # 不进访问日志）交给前端，之后所有 API 照旧要 Bearer。/charts/* 仍要 token（图里是用户数据）。
    web_dist = os.path.abspath(web_dist or default_web_dist())
    app.state.web_dist = web_dist
    app.mount("/assets", StaticFiles(directory=os.path.join(web_dist, "assets"), check_dir=False), name="assets")

    @app.get("/", include_in_schema=False)
    def index():
        path = os.path.join(web_dist, "index.html")
        if not os.path.isfile(path):
            return HTMLResponse("<p>前端未构建：在 ui/web 目录运行 npm ci &amp;&amp; npm run build。</p>", status_code=503,
                                headers={"Content-Security-Policy": CSP})
        with open(path, encoding="utf-8") as f:
            html = f.read()
        return HTMLResponse(html, headers={"Content-Security-Policy": CSP, "Cache-Control": "no-store",
                                           "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"})

    return app
