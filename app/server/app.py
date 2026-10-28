"""FastAPI 应用（阶段 4）。前端只通过这里的 HTTP / SSE 与后端交互（M22），不走 Tauri IPC。

接口（除 /health 和前端静态文件外都要 Authorization: Bearer <token>；图表另可用 ?token=，方便 <img>）：
    GET    /health
    POST   /shutdown                     桌面壳退出前请求后端自行退出（202；未挂退出钩子时 503）
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
    POST   /messages/{id}/cancel         停止正在分析的消息：CAS running→cancelled（已结束 409），置位取消信号（阶段 5 F2）
    DELETE /messages/{id}                 删一轮（助手消息 + 前一条用户消息）、级联事件 / 反馈、删图（阶段 6.6 M0，204；用户消息 400；分析中 409）
    PUT    /messages/{id}/feedback       {"rating": "up"|"down"|null, "note"?}（只限已结束的助手消息）
    GET    /  、/assets/*                前端（ui/web 构建产物）。不要 token——页面本身不含机密，token 由
                                         URL fragment 交给前端；index.html 带 CSP（阶段 5 F0）
    GET    /settings  PUT /settings      非机密设置：model、base_url、timeout（单次请求超时，秒）；
                                         sources 给出每项当前生效值的来源 settings | env | default（阶段 6 收尾）
    POST   /exports/png?filename=        桌面模式（--desktop）：请求体是 PNG 字节，写进「下载」文件夹，返回 {"path"}；
                                         浏览器模式 404（前端走 <a download>）。见 app/server/exports.py
    GET    /settings/api-key             {"configured", "source"}——从不返回 Key 本身
    PUT    /settings/api-key             {"api_key"} → 存进系统钥匙串
    DELETE /settings/api-key
    POST   /settings/test                用已保存的设置发一次最小请求（阶段 5 收尾 C）：200 {"ok": true, "latency_ms", "model"}
                                         或 {"ok": false, "llm_kind", "message", "latency_ms"}；同时只许一个，第二个 409
    阶段 6.5（多服务商，docs/roadmap/phase65-models.md）：/settings、/settings/api-key、/settings/test 保留一个版本，
    作用于当前生效的连接；没有任何连接时作用于「环境变量」虚拟连接（行为同阶段 6.5 之前）。
    GET    /providers                    服务商预设（app/core/providers.json）
    GET    /connections                  {"active", "items"}；没有连接时 items 只有只读的「环境变量」（id=env）
    POST   /connections  PUT/DELETE /connections/{id}
    PUT/DELETE /connections/{id}/api-key Key 存钥匙串 ACCOUNT=conn:<id>，只回 {needed, configured}
    POST   /connections/{id}/activate
    POST   /connections/{id}/test        两步：连接 + 工具调用；结果存进 probe；和 /settings/test 同一把锁（409）
    GET    /connections/{id}/models      服务商的模型列表（10 秒超时）；失败时返回预设模型 + reason
    见 app/server/connections.py 与 docs/sidecar-contract.md。

安全（docs/THREAT_MODEL.md）：只监听 127.0.0.1；TrustedHost 只认 localhost / 127.0.0.1（挡 DNS rebinding）；
每次启动随机 token（挡本机网页对 localhost 的跨站请求）；不开 CORS，阶段 6 外壳确定后只放行外壳的源。
"""
from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import re
import secrets
import shutil
import sys
import threading
import time
from typing import Literal, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.core.errors import user_error
from app.core.text import BIDI_CONTROLS as _BIDI_CONTROLS, CONTROL_CHARS as _CONTROL_CHARS
from app.core.events import CANCELLED_MESSAGE, DISCONNECTED_MESSAGE, INTERRUPTED_MESSAGE, STREAM_ABORTED_MESSAGE
from app.server import connections as conns
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
# 去掉控制字符（保留 \t \n）和双向文本控制符：note 会原样回显到前端（THREAT_MODEL T9）。
# 字符集只有一份，在 app/core/text.py（T11 起错误文案也用它）
# index.html 的内容安全策略（阶段 5 方案 §1）。构建产物里不能有内联 <script>（CI 检查），所以 script-src 只要 'self'；
# ECharts / React 会写行内 style，故 style-src 带 'unsafe-inline'；图表导出用 data: / blob:。
CSP = ("default-src 'self'; img-src 'self' data: blob:; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; object-src 'none'")

logger = logging.getLogger("datachat.server")


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
    memory_mode: Optional[Literal["off", "state"]] = None    # 阶段 6.6：会话记忆（实验），默认 off


class FeedbackIn(BaseModel):
    rating: Optional[Literal["up", "down"]] = None
    note: str = Field("", max_length=FEEDBACK_NOTE_MAX)


class ApiKeyIn(BaseModel):
    api_key: str = Field(min_length=1, max_length=512)


# 前端产物用到的扩展名 → 固定 MIME，不信任平台注册表（见 create_app 里挂 /assets 处）。
ASSET_MIME_TYPES = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
                    ".svg": "image/svg+xml", ".json": "application/json", ".woff2": "font/woff2"}


def _pin_asset_mime_types() -> None:
    for ext, mime in ASSET_MIME_TYPES.items():
        mimetypes.add_type(mime, ext)


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
    persist.CHART_DIR = chart_dir = os.path.join(home, "charts")
    Session = make_sessionmaker(os.path.join(home, "datachat.db"))
    from app.server import retention
    token = token or secrets.token_urlsafe(32)

    # 上次进程被杀时还在跑的消息，标成 interrupted（不是 cancelled：用户没点过停止）
    with Session() as db:
        for m in db.scalars(select(Message).where(Message.status == "running")):
            m.status, m.content = "interrupted", INTERRUPTED_MESSAGE
            logger.warning("后端重启，消息 %s 的分析中断，标成 interrupted", m.id)
        db.commit()
    conns.migrate_legacy(Session)     # 阶段 6.5 §4：旧设置 → 连接，只跑一次

    app = FastAPI(title="datachat", version="0.4")
    cancels: dict[str, threading.Event] = {}     # 正在分析的助手消息 id → 取消信号（只在本进程内有意义）
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
            out["error"] = user_error("dataset", e, trace_id=secrets.token_hex(16),   # T11：编号对应 server.log
                                      context=f"dataset={ds.id}")
            return out
        multi = tp is not None
        cols, parts, errors, previews = {}, [], [], []
        for name, path in tp or [("df", target)]:
            filename = os.path.basename(path)
            try:
                df, enc = read_csv_with_encoding(path)
            except Exception as e:  # noqa: BLE001
                msg = user_error("dataset", e, trace_id=secrets.token_hex(16),
                                 context=f"dataset={ds.id} file={filename}")
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

    def turn_snapshots(messages):
        """阶段 6.6 state 模式的历史：全部轮次（含失败 / 取消 / 中断，M5），每对 (user, 紧跟的 assistant) 一个快照。
        正在跑的（running）不算：它就是本轮。"""
        from app.memory.snapshots import from_row
        out = []
        for q, a in zip(messages, messages[1:]):
            if q.role == "user" and a.role == "assistant" and a.status != "running":
                r = None
                if a.result_json:
                    try:
                        r = json.loads(a.result_json)
                    except ValueError:
                        r = None
                out.append(from_row(q.content, q.created_at, a.status, a.content, r))
        return out

    def turn_history(messages):
        """ReAct 多轮上下文从 messages 表重建（重启不丢）：只取成功的轮次（user + 紧跟的 ok 助手消息）；
        失败 / 取消的轮次不进上下文——用户通常会换个说法重问。"""
        out = []
        for q, a in zip(messages, messages[1:]):
            if q.role == "user" and a.role == "assistant" and a.status == "ok":
                out.append((q.content, a.content))
        return out

    def llm_config():
        """生效连接的配置（阶段 6.5）；没有任何连接时是环境变量 DEEPSEEK_* + 旧 settings 覆盖（同阶段 6.5 之前）。"""
        with Session() as db:
            return conns.active_config(db)[0]

    def llm_config_meta():
        with Session() as db:
            cfg, who = conns.active_config(db)
        return cfg, {"connection_id": who["id"], "connection_name": who["name"], "model": cfg.model}

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

    # 阶段 6 D1：桌面壳正常退出时先请求后端自己退（SQLite 收尾、worker 清理），等 3 s 再靠 Job Object 强杀。
    # app.state.request_shutdown 由 app.server.__main__ 挂上（uvicorn.Server.should_exit）；
    # 没挂时（TestClient、被别的程序嵌入）返回 503，不假装成功。
    app.state.request_shutdown = None

    @app.post("/shutdown", dependencies=[Depends(auth)], status_code=202)
    def shutdown():
        fn = app.state.request_shutdown
        if fn is None:
            raise HTTPException(503, "shutdown not available")
        retention.incremental_vacuum(Session.kw["bind"])     # 阶段 6.6 M0：有上限的回收，不跑全量 VACUUM
        fn()
        return {"ok": True}

    # 阶段 6 收尾：桌面端导出 PNG。export_dir 由 app.server.__main__ 在 --desktop 时挂上；None（浏览器模式、TestClient
    # 默认）时 404，前端在浏览器里本来也不会调它。先看 Content-Length 再读体，超限不读进内存。
    app.state.export_dir = None

    @app.post("/exports/png", dependencies=[Depends(auth)])
    async def export_png(request: Request, filename: str = Query("", max_length=500)):
        from app.server.exports import MAX_PNG_BYTES, ExportError, save_png
        if app.state.export_dir is None:
            raise HTTPException(404, "仅桌面版可用")
        try:
            declared = int(request.headers.get("content-length", "0"))
        except ValueError:
            declared = 0
        if declared > MAX_PNG_BYTES:
            raise HTTPException(413, "图片太大")
        data = await request.body()
        try:
            path = save_png(app.state.export_dir, filename, data)
        except ExportError as e:
            raise HTTPException(400, str(e)) from None
        except OSError as e:
            logger.warning("导出 PNG 写盘失败：%s", type(e).__name__)
            raise HTTPException(500, "写入下载文件夹失败") from None
        logger.info("导出 PNG：%s（%d 字节）", os.path.basename(path), len(data))
        return {"path": path}

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
        pngs = []
        for s in db.scalars(select(ChatSession).where(ChatSession.dataset_id == dataset_id)):
            pngs += retention.message_chart_files(s.messages, chart_dir)
        db.delete(ds)
        db.commit()
        shutil.rmtree(os.path.join(home, "datasets", dataset_id), ignore_errors=True)
        retention.remove_files(pngs)
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
        s = get_or_404(db, ChatSession, session_id)
        pngs = retention.message_chart_files(s.messages, chart_dir)    # 阶段 6.6 M0：先收集，删库后删文件
        db.delete(s)
        db.commit()
        retention.remove_files(pngs)
        return {"ok": True}

    @app.delete("/messages/{message_id}", dependencies=[Depends(auth)], status_code=204)
    def delete_message(message_id: str, db=Depends(db_dep)):
        """阶段 6.6 M0：删一轮（助手消息 + 紧挨着的前一条用户消息），事件 / 反馈级联，图表文件一并删。
        只接受助手消息（传用户消息会把一问一答拆成两半）；会话里有正在分析的轮次 → 409。"""
        m = get_or_404(db, Message, message_id)
        if m.role != "assistant":
            raise HTTPException(400, "只能按助手消息删除一轮问答")
        if db.scalar(select(Message).where(Message.session_id == m.session_id, Message.status == "running")):
            raise HTTPException(409, "这个会话还有一条消息在分析中")
        # 与 turn_history 同一个顺序（relationship 的 order_by=created_at，同毫秒时靠插入顺序）；
        # 不能再按 id 排：问与答常在同一毫秒落库，按随机 id 排会把答排到问前面（§1.4 第 3 条）
        msgs = list(m.session.messages)
        i = next(k for k, x in enumerate(msgs) if x.id == m.id)
        pair = [m] + ([msgs[i - 1]] if i > 0 and msgs[i - 1].role == "user" else [])
        pngs = retention.message_chart_files(pair, chart_dir)
        for x in pair:
            db.delete(x)
        db.commit()
        retention.remove_files(pngs)
        db.expire_all()
        roles = [x.role for x in db.get(ChatSession, m.session_id).messages]
        if any(a == b for a, b in zip(roles, roles[1:])):      # §1.4 第 3 条：删完复核一问一答仍相邻
            logger.warning("会话 %s 删除消息后出现相邻同角色消息：%s", m.session_id, roles)
        return Response(status_code=204)

    @app.post("/sessions/{session_id}/messages", dependencies=[Depends(auth)])
    def post_message(session_id: str, body: MessageIn, db=Depends(db_dep)):
        s = get_or_404(db, ChatSession, session_id)
        if db.scalar(select(Message).where(Message.session_id == session_id, Message.status == "running")):
            raise HTTPException(409, "这个会话还有一条消息在分析中")
        target = dataset_target(get_or_404(db, Dataset, s.dataset_id))
        agent = s.agent
        from app.memory.config import SETTING_KEY, resolve_memory_mode
        row = db.get(Setting, SETTING_KEY)
        mem_setting = row.value if row else None
        if resolve_memory_mode(mem_setting) == "state":
            history = turn_snapshots(s.messages)          # 阶段 6.6：两种 agent 都带（workflow 只用来折叠工作状态）
        else:
            history = turn_history(s.messages) if agent == "react" else None
        q = Message(session_id=session_id, role="user", content=body.content, created_at=now())
        a = Message(session_id=session_id, role="assistant", status="running", created_at=now())
        db.add_all([q, a])
        if not s.title:
            s.title = body.content[:60]
        s.updated_at = now()
        db.commit()
        msg_id = a.id

        kwargs = dict(agent=agent, trace_id=msg_id, log=False, memory_mode=mem_setting, **(analyze_kwargs or {}))
        cfg, meta = llm_config_meta()     # 阶段 6.5：每条分析消息记下当时的连接名和模型（result.meta）
        if chat_model_factory is not None:
            kwargs["chat_model"] = chat_model_factory()
        else:
            kwargs["llm_config"] = cfg
        if history:
            kwargs["history"] = history

        cancel = threading.Event()
        cancels[msg_id] = cancel
        kwargs["cancel"] = cancel

        def stream():
            # 状态写库只有两处，都用 CAS（WHERE status='running'）：这里的 finally，和 POST /messages/{id}/cancel。
            # 先到者生效；已被 cancel 的轮次这里不再覆盖（result_json 留空，前端按 status=cancelled 合成 done）。
            # 判据是显式的：只有 except GeneratorExit（客户端断开）才落 interrupted；不是用户点停止，所以不用 cancelled。
            # 前端点停止必须先等 POST /cancel 返回、再断开 fetch，这样 cancel 的 CAS 先落库，这里的 CAS 命中 0 行。
            # 默认兜底是 error + STREAM_ABORTED_MESSAGE：任何没预料到的结局（异常、生成器正常结束却没有 done）都算后端问题，
            # 不能显示成"连接已断开"把排查方向指向网络。
            # 真 TCP 断开时：分析就跑在这个生成器里，下一个事件 yield 写失败 → 生成器被关闭 → 分析在下一个事件边界停下
            # （最多晚一次模型调用）。分析真的停了，所以落 interrupted，不留 running——留 running 会让会话 409 到重启
            # （tests/test_web_f2.py::test_real_tcp_disconnect_is_interrupted，真 uvicorn + 真 socket）。
            status, content, result_json = "error", STREAM_ABORTED_MESSAGE, None
            done_seen = False
            try:
                with Session() as wdb:
                    for ev in analyze_stream(target, body.content, **kwargs):
                        d = ev.to_dict()
                        if ev.type == "done":
                            done_seen = True
                            d["data"]["result"]["meta"] = meta
                            r = ev.result
                            if r.error_kind == "cancelled":
                                status, content = "cancelled", CANCELLED_MESSAGE
                            else:
                                status = "ok" if r.ok else "error"
                                content = r.answer if r.ok else (r.error or "")
                                result_json = json.dumps(d["data"]["result"], ensure_ascii=False, default=str)
                        else:
                            wdb.add(EventRow(message_id=msg_id, seq=ev.seq, type=ev.type, ts=str(ev.ts),
                                             data_json=json.dumps(d["data"], ensure_ascii=False, default=str)))
                            wdb.commit()
                        yield (f"id: {ev.seq}\nevent: {ev.type}\n"
                               f"data: {json.dumps(public_event(d), ensure_ascii=False, default=str)}\n\n")
            except GeneratorExit:
                if not done_seen:
                    status, content = "interrupted", DISCONNECTED_MESSAGE
                raise
            except Exception:  # —— 没收到 done 又不是断开：保持默认 error，异常详情只进日志
                if not done_seen:
                    logger.exception("消息 %s 的分析流异常中断", msg_id)
                raise
            finally:
                cancels.pop(msg_id, None)
                with Session() as fdb:
                    fdb.execute(update(Message).where(Message.id == msg_id, Message.status == "running")
                                .values(status=status, content=content, result_json=result_json))
                    fdb.commit()

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Message-Id": msg_id,
                                          "X-User-Message-Id": q.id})

    @app.post("/messages/{message_id}/cancel", dependencies=[Depends(auth)])
    def cancel_message(message_id: str, db=Depends(db_dep)):
        """停止按钮。CAS 写库：只把仍在 running 的轮次改成 cancelled（命中 0 行 → 409，已完成的轮次不动）；
        落库后同一会话立刻可以再问，不撞 409。正在进行的那次 LLM 调用或代码执行会跑完（粒度与断开连接相同），
        之后 analyze_stream 看到信号提前收尾；它的 finally 也是 CAS，不会把 cancelled 覆盖回去。"""
        m = get_or_404(db, Message, message_id)
        if m.role != "assistant":
            raise HTTPException(400, "只能停止助手消息")
        hit = db.execute(update(Message).where(Message.id == message_id, Message.status == "running")
                         .values(status="cancelled", content=CANCELLED_MESSAGE)).rowcount
        db.commit()
        if not hit:
            raise HTTPException(409, "这条消息已经结束")
        ev = cancels.get(message_id)
        if ev is not None:
            ev.set()
        return {"id": message_id, "status": "cancelled"}

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

    # sources（阶段 6 收尾，S 10-27）：桌面端不读仓库里的 .env，没在设置页填时会回退到默认的 api.deepseek.com，
    # 用户看不出"现在用的是哪一份"。每项标出当前生效值来自 设置页 / 环境变量 / 默认值。
    @app.get("/settings", dependencies=[Depends(auth)])
    def get_settings(db=Depends(db_dep)):
        """阶段 6.5：有生效连接时 model / base_url 来自连接（sources 写 connection），超时仍是全局设置；
        没有连接时同阶段 6.5 之前（settings | env | default）。connection 给出生效连接的 id 和名字。"""
        st = {r.key: r.value for r in db.scalars(select(Setting))}
        cfg, who = conns.active_config(db)
        over = {k for k, v in st.items() if k in SETTING_KEYS and v}
        if "timeout" in over:
            try:
                float(st["timeout"])
            except ValueError:
                over.discard("timeout")      # 同 llm_config：坏值不生效
        sources = {k: "settings" if k in over else "env" if conns.legacy_env_source(k) else "default"
                   for k in SETTING_KEYS}
        from app.memory.config import SETTING_KEY, env_override, normalize, resolve_memory_mode
        memory = {"mode": resolve_memory_mode(st.get(SETTING_KEY)), "setting": normalize(st.get(SETTING_KEY)) or "off",
                  "env": env_override()}        # 阶段 6.6：mode 是实际生效值；env 非空时设置页提示被环境变量覆盖
        if who["id"] != conns.ENV_ID:
            sources["model"] = sources["base_url"] = "connection"
            return {"model": cfg.model, "base_url": cfg.base_url, "timeout": cfg.timeout, "sources": sources,
                    "connection": who, "memory": memory}
        return {"model": st.get("model") or cfg.model, "base_url": st.get("base_url") or cfg.base_url,
                "timeout": cfg.timeout, "sources": sources, "connection": who, "memory": memory}

    @app.put("/settings", dependencies=[Depends(auth)])
    def put_settings(body: SettingsIn, db=Depends(db_dep)):
        """旧接口保留一个版本：有生效连接时 model / base_url 写到那个连接上（timeout 照旧是全局设置）；
        没有连接时同阶段 6.5 之前，写 settings 行（空串 = 清除，回到环境变量 / 默认）。"""
        vals = body.model_dump(exclude_none=True)
        row = conns.active_row(db)
        if row is not None:
            if vals.get("base_url") is not None:
                url = str(vals.pop("base_url")).strip()
                row.base_url = conns.base_url_for(conns.provider_or_400(row.provider), url)
                row.probe = None
            if vals.get("model") is not None:
                m = str(vals.pop("model")).strip()
                if not m:
                    raise HTTPException(400, "模型名不能为空")
                row.model = m
            row.updated_at = now()
        for k, v in vals.items():
            conns.put_setting(db, k, str(v).strip())
        db.commit()
        return get_settings(db)

    def legacy_key_status(db) -> dict:
        row = conns.active_row(db)
        if row is not None:
            on = conns.conn_key(row) is not None
            return {"configured": on or not conns.needs_key(row.provider), "source": "keyring" if on else None}
        _, src = keystore.resolve_api_key()
        return {"configured": src is not None, "source": src}

    @app.get("/settings/api-key", dependencies=[Depends(auth)])
    def get_api_key_status(db=Depends(db_dep)):
        return legacy_key_status(db)

    @app.put("/settings/api-key", dependencies=[Depends(auth)])
    def put_api_key(body: ApiKeyIn, db=Depends(db_dep)):
        row = conns.active_row(db)
        try:
            if row is not None:
                keystore.set_api_key(body.api_key, keystore.conn_account(row.id))
            else:
                keystore.set_api_key(body.api_key)
        except keystore.KeyStoreError as e:
            raise HTTPException(400, str(e)) from None
        return legacy_key_status(db)

    @app.delete("/settings/api-key", dependencies=[Depends(auth)])
    def delete_api_key(db=Depends(db_dep)):
        row = conns.active_row(db)
        try:
            if row is not None:
                keystore.delete_api_key(keystore.conn_account(row.id))
            else:
                keystore.delete_api_key()
        except keystore.KeyStoreError as e:
            raise HTTPException(400, str(e)) from None
        return legacy_key_status(db)

    # 设置页「测试连接」（phase5「阶段 5 收尾」C）：用**已保存**的设置（llm_config：生效连接；没有连接时是库里的
    # model / base_url / timeout + resolve_api_key）发一次最小请求，不重试，超时 min(timeout, 15)。没 Key 不发请求，直接 no_key。
    # message 走 T11 user_error（同 llm 错误卡的文案，不带上游原文以外的东西，Key 打码）；不落库、不写 events。
    # 同一时间只允许一个测试在跑：第二个 409（非阻塞抢锁）。阶段 6.5 的 /connections/{id}/test 共用这把锁。
    # 旧接口保留一个版本（两步测试见 /connections/{id}/test）。
    test_lock = threading.Lock()

    @app.post("/settings/test", dependencies=[Depends(auth)])
    def test_settings():
        from app.core.errors import NO_KEY_MESSAGE
        from app.core.llm import LLMError, ping
        if not test_lock.acquire(blocking=False):
            raise HTTPException(409, "已有一个测试连接在进行")
        try:
            cfg = llm_config()
            trace_id = secrets.token_hex(16)
            if not cfg.api_key:
                return {"ok": False, "llm_kind": "no_key", "latency_ms": 0,
                        "message": user_error("text", NO_KEY_MESSAGE, trace_id=trace_id)}
            t0 = time.monotonic()
            try:
                ping(cfg)
            except LLMError as e:
                return {"ok": False, "llm_kind": e.kind, "latency_ms": round((time.monotonic() - t0) * 1000),
                        "message": user_error("llm", e, trace_id=trace_id)}
            return {"ok": True, "latency_ms": round((time.monotonic() - t0) * 1000), "model": cfg.model}
        finally:
            test_lock.release()

    conns.register(app, Session, auth, db_dep, test_lock)

    # ------------------------------------------------------------------ 前端静态文件（不要 token）
    # 边界：只有 / 和 /assets/* 免 token。页面和 JS 不含机密；token 只经 URL fragment（不发给服务器、
    # 不进访问日志）交给前端，之后所有 API 照旧要 Bearer。/charts/* 仍要 token（图里是用户数据）。
    web_dist = os.path.abspath(web_dist or default_web_dist())
    app.state.web_dist = web_dist
    # Windows 上 mimetypes 会读注册表 HKCR\.js 的 Content Type，常被编辑器改成 text/plain；
    # module 脚本的 MIME 不是 JavaScript 时浏览器拒绝执行 → 白屏（S 10-23 本机实测）。启动时钉死。
    _pin_asset_mime_types()
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
