"""FastAPI 应用（阶段 4）。前端只通过这里的 HTTP / SSE 与后端交互（M22），不走 Tauri IPC。

接口（除 /health 和前端静态文件外都要 Authorization: Bearer <token>；图表另可用 ?token=，方便 <img>）：
    GET    /health
    POST   /shutdown                     桌面壳退出前请求后端自行退出（202；未挂退出钩子时 503）
    POST   /datasets                     multipart：files（一个或多个 CSV / xlsx，可含 *.dict.csv 字典）、name；
                                         .xls 拒绝；xlsx 另按解压后体积限（app/tools/excel_io.py）
    GET    /datasets                     列表
    GET    /datasets/{id}?rows=20        详情（文件、每张表的列与概要）；带 rows（1–100）时加每张表前 N 行预览，
                                         单元格一律字符串或 null（阶段 5 F1.1：预览与详情合并，每个文件只读一遍）
                                         profile：数据资产卡的概要（表数、总行数、列数、缺失列数、时间范围，
                                         逐表明细在 profile.tables；阶段 7.6 U2，只加字段）
    DELETE /datasets/{id}                 口径（dataset_notes）随数据集级联删除（批 4b M10）
    GET    /datasets/{id}/notes?history=1 口径与规则（批 4b M2）：默认只给在用的；history=1 带上被取代 / 停用的版本
    POST   /datasets/{id}/notes          {"kind": "metric"|"rule", "name", "body", "unit"?, "synonyms"?}；在用的同名 409
    PUT    /datasets/{id}/notes/{nid}    改口径 = 新增一行（supersedes 指向旧行），旧行记 retired_at；内容没变时原样返回
    DELETE /datasets/{id}/notes/{nid}    停用（软遗忘，只写 retired_at），204
    POST   /datasets/{id}/notes/import   请求体是 CSV（列 kind,name,body,unit,synonyms，别名用 ; 分隔）或 JSON 数组
                                         （Content-Type: application/json）；整批校验，幂等（同名同 sha 跳过，sha 不同按版本取代）
    GET    /datasets/{id}/notes/export?format=csv|json  在用的口径，供重新上传的数据集导入（M10）
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
    PUT    /desktop/update  GET /desktop/update  桌面壳查到的新版本 {"version","notes"}；GET 返回 {"available": … | null}（#149）
    POST   /exports/png?filename=        桌面模式（--desktop）：请求体是 PNG 字节，写进「下载」文件夹，返回 {"path"}；
                                         浏览器模式 404（前端走 <a download>）。见 app/server/exports.py
    POST   /messages/{id}/export/code    把这一轮最终执行的代码导出成独立 .py（自带数据加载、chart()、savefig 落盘），
                                         写进下载文件夹，返回 {"path", "filename"}；代码含沙箱拦下的操作时 422
    POST   /messages/{id}/export/result?format=csv|xlsx  在沙箱里重跑同一段代码拿 result，导出 CSV（UTF-8 BOM）或 xlsx，
                                         返回 {"path", "filename", "rows", "columns", "matches_original"}。见 app/tools/export.py
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
from urllib.parse import quote

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
from app.server.key_numbers import attach_key_numbers
from app.server.titles import session_title, unique_title
from app.server.db import (ChatSession, Dataset, DatasetFile, DatasetNote, EventRow, Feedback, Message, Setting,
                           make_sessionmaker, now)

MAX_FILE_BYTES = 1024 * 1024 * 1024        # 单个文件 1 GB
# xlsx 另按解压后体积限（app/tools/excel_io.MAX_XLSX_UNCOMPRESSED_BYTES，默认 300 MB，可用 DATACHAT_MAX_XLSX_BYTES 改）
UPLOAD_SUFFIXES = (".csv", ".xlsx")
MAX_FILES = 50
SETTING_KEYS = ("model", "base_url", "timeout")
TIMEOUT_RANGE = (5.0, 600.0)
PREVIEW_MAX_ROWS = 100
PREVIEW_DEFAULT_ROWS = 20    # 上传后随响应带回的预览行数
PREVIEW_CELL_MAX = 200       # 单元格超长截断（按文本渲染，T9）
EXPORT_TIMEOUT = 60          # 导出结果表时在沙箱里重跑代码的超时（秒）；分析时默认 20，导出放宽
CHART_NAME = re.compile(r"^chart_[0-9_]+_[0-9a-f]{6}\.png$")
FEEDBACK_NOTE_MAX = 1000
# 去掉控制字符（保留 \t \n）和双向文本控制符：note 会原样回显到前端（THREAT_MODEL T9）。
# 字符集只有一份，在 app/core/text.py（T11 起错误文案也用它）
# index.html 的内容安全策略（阶段 5 方案 §1）。构建产物里不能有内联 <script>（CI 检查），所以 script-src 只要 'self'；
# ECharts / React 会写行内 style，故 style-src 带 'unsafe-inline'；图表导出用 data: / blob:。
CSP = ("default-src 'self'; img-src 'self' data: blob:; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; object-src 'none'")

logger = logging.getLogger("datachat.server")


# 桌面安装器记录「数据文件夹」的注册表位置（HKCU；desktop/src-tauri/installer.nsi 的 MANUPRODUCTKEY，值名 DataDir）。
# 与 desktop/src-tauri/src/sidecar.rs 的 DATA_DIR_REG_KEY 必须一致（tests/test_desktop_installer.py 核对）。
DATA_DIR_REG_KEY = r"Software\smilewithoutfalling\DataChat"
DATA_DIR_REG_VALUE = "DataDir"


def _registry_data_dir() -> str | None:
    """安装时选的数据文件夹；非 Windows、没装过桌面版、读不到都返回 None。"""
    if os.name != "nt":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, DATA_DIR_REG_KEY) as k:
            v, _ = winreg.QueryValueEx(k, DATA_DIR_REG_VALUE)
    except OSError:
        return None
    v = str(v).strip()
    return v or None


def default_home() -> str:
    """数据目录（phase6-desktop.md §3b 第 3 条）：DATACHAT_HOME → 桌面安装时选的数据文件夹（注册表 DataDir）
    → Windows 用 %LOCALAPPDATA%\\datachat，其他系统 ~/.local/share/datachat。与桌面壳 sidecar.rs home_dir 同一顺序。"""
    env = (os.getenv("DATACHAT_HOME") or "").strip()
    if env:
        return env
    reg = _registry_data_dir()
    if reg:
        return reg
    base = os.getenv("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "datachat")


class DesktopUpdateIn(BaseModel):
    version: str = Field(min_length=1, max_length=64, pattern=r"^[0-9A-Za-z.+-]+$")
    notes: str = Field("", max_length=4000)


class SessionIn(BaseModel):
    dataset_id: str
    agent: str = "workflow"
    title: str = ""


class ViewBody(BaseModel):
    """原型：预览表全表排序 / 筛选。"""
    table: str
    sort_col: int | None = None
    sort_dir: Literal["asc", "desc"] = "asc"
    filters: dict[str, list[str | None]] = Field(default_factory=dict)   # {列序号: 保留的值（与预览显示的文本一致，None = 空）}
    rows: int = Field(PREVIEW_DEFAULT_ROWS, ge=1, le=PREVIEW_MAX_ROWS)


class SessionExportBody(BaseModel):
    charts: dict[str, dict[str, str]] = Field(default_factory=dict)   # 原型：前端离屏渲染的 ECharts 图 {message_id: {序号: PNG data URL}}


class SessionPatch(BaseModel):
    title: str = Field(max_length=200)


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class SettingsIn(BaseModel):
    model: Optional[str] = Field(None, max_length=200)
    base_url: Optional[str] = Field(None, max_length=500)
    timeout: Optional[float] = Field(None, ge=TIMEOUT_RANGE[0], le=TIMEOUT_RANGE[1])
    memory_mode: Optional[Literal["off", "state", "full"]] = None    # 阶段 6.6：会话记忆（实验）；批 4a 起 full 是独立一档，2026-11-16 起默认档 state（C-021）
    memory_rewrite: Optional[bool] = None    # 批 4a M7：追问前先改写指代 / 相对时间（多一次模型调用），默认关


class NoteIn(BaseModel):
    """口径（批 4b M2）。长度与取值在 app/memory/metrics.clean 里校验（400，中文原因）；这里只给一个宽松的上限防超大请求。"""
    kind: str = Field(max_length=16)
    name: str = Field(max_length=1000)
    body: str = Field(max_length=10000)
    unit: str = Field("", max_length=1000)
    synonyms: str = Field("", max_length=2000)


NOTES_IMPORT_MAX_BYTES = 1024 * 1024       # 口径导入文件上限 1 MB
NOTES_IMPORT_MAX_ROWS = 1000


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
        from app.tools.dataset import excel_tables, is_dict_file, is_excel_file, load_warnings, table_paths
        from app.tools.schema import profile_dataset, profile_df
        target = dataset_target(ds)
        try:
            tp = table_paths(target)
        except Exception as e:  # noqa: BLE001 —— 目录空、表名重复：分析同样会失败
            out["error"] = user_error("dataset", e, trace_id=secrets.token_hex(16),   # T11：编号对应 server.log
                                      context=f"dataset={ds.id}")
            return out
        multi = tp is not None
        cols, parts, errors, previews, warns, profiles = {}, [], [], [], [], []

        def read_file(name, path):
            """→ [(表名, df, 编码说明)]。CSV 一个文件一张表；xlsx 每个读出的 sheet 一张表（阶段 7.5 第 2 步）。"""
            if not is_excel_file(path):
                df, enc = read_csv_with_encoding(path)
                return [(name, df, enc)]
            stem = os.path.splitext(os.path.basename(path))[0]
            named = excel_tables(name if multi else stem, path)
            if not multi and len(named) == 1:
                return [("df", named[0][1].df, "xlsx")]
            return [(t, st.df, "xlsx") for t, st in named]

        for name, path in tp or [("df", target)]:
            filename = os.path.basename(path)
            try:
                read = read_file(name, path)
            except Exception as e:  # noqa: BLE001
                msg = user_error("dataset", e, trace_id=secrets.token_hex(16),
                                 context=f"dataset={ds.id} file={filename}")
                errors.append(f"{filename}：{msg}")
                parts.append(f"{name} 读取失败")
                previews.append({"name": name, "filename": filename, "error": msg})
                continue
            if not multi and len(read) > 1:     # 单个 xlsx 读出多张表 = 多表数据集
                multi = True
            for tname, df, enc in read:
                cols[tname] = [str(c) for c in df.columns]
                profiles.append((tname, profile_df(df)))      # 阶段 7.6 U2：数据资产卡，同一个 df，不多读文件
                parts.append(f"{tname} {len(df)}×{len(df.columns)}（{enc}）" if multi
                             else f"{len(df)} 行 × {len(df.columns)} 列，编码 {enc}")
                w = load_warnings(df)
                if w:
                    warns += [f"{tname if multi else filename}：{x}" for x in w]
                if rows is not None:
                    previews.append(preview_table(tname, filename, df, enc, rows, w))
            del read
        out["tables"] = cols
        out["summary"] = (f"{len(parts)} 张表：" + "，".join(parts)) if multi else parts[0]
        out["profile"] = profile_dataset(profiles)   # 只算读成功的表；读坏的表在 error 里
        if warns:                        # 只有 xlsx 有读取提示；CSV 数据集的响应不多这个键
            out["warnings"] = warns
        if errors:                       # 任一张读坏，分析（load_data）整体会失败，所以在顶层也报
            out["error"] = "；".join(errors)
        if rows is not None:
            out["preview"] = {"rows": rows, "tables": previews,
                              "dicts": sorted(f.filename for f in ds.files if is_dict_file(f.filename))}
        return out

    def dataset_target(ds: Dataset) -> str:
        """单个数据文件 → 它的路径（CSV 或 xlsx；同目录的同名 .dict.csv 自动作字典）；多个 → 目录。"""
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

    def preview_table(name, filename, df, enc, rows, warnings=None):
        stats = {"bidi_stripped": 0, "truncated_cells": 0}
        columns = [preview_cell(c, stats) or "" for c in df.columns]
        body = [[preview_cell(v, stats) for v in r] for r in df.head(rows).itertuples(index=False, name=None)]
        out = {"name": name, "filename": filename, "encoding": enc,
               "total_rows": int(len(df)), "total_columns": int(len(df.columns)),
               "columns": columns, "dtypes": [str(t) for t in df.dtypes], "rows": body, **stats}
        if warnings:                     # xlsx 的读取提示（合并单元格、跳过的 sheet 等）；CSV 没有这个键
            out["warnings"] = [preview_cell(w, {"bidi_stripped": 0, "truncated_cells": 0}) for w in warnings]
        return out

    # ------------------------------------------------------------------ 原型：预览表全表排序 / 按值筛选
    VIEW_VALUES_MAX = 500        # 列菜单里最多列多少个不同值（按出现次数降序）

    from collections import OrderedDict
    _view_cache: OrderedDict = OrderedDict()     # (数据集 id, 表名, 各文件 mtime+size) → (filename, df, enc)
    _view_lock = threading.Lock()
    VIEW_CACHE_MAX = 4                           # 只缓存最近看的几张表；调用方不得原地修改 df

    def load_one_table(ds: Dataset, table: str):
        """带小缓存的 _load_one_table：列菜单和排序筛选会对同一张表连续请求，不必每次重读文件。
        键里带数据集目录下各文件的 mtime 和大小，文件变了自动失效。"""
        target = dataset_target(ds)
        try:
            files = sorted(os.scandir(target), key=lambda e: e.name) if os.path.isdir(target) else []
            stamp = tuple((e.name, e.stat().st_mtime_ns, e.stat().st_size) for e in files if e.is_file()) \
                or (os.stat(target).st_mtime_ns, os.stat(target).st_size)
        except OSError:
            stamp = None
        key = (ds.id, table, stamp)
        with _view_lock:
            if stamp is not None and key in _view_cache:
                _view_cache.move_to_end(key)
                return _view_cache[key]
        hit = _load_one_table(ds, table)
        if stamp is not None:
            with _view_lock:
                for k in [k for k in _view_cache if k[0] == ds.id and k[1] == table]:
                    _keys_cache.pop(id(_view_cache.pop(k)[1]), None)
                _view_cache[key] = hit
                while len(_view_cache) > VIEW_CACHE_MAX:
                    _keys_cache.pop(id(_view_cache.popitem(last=False)[1][1]), None)
        return hit

    def _load_one_table(ds: Dataset, table: str):
        """按 dataset_out 同样的规则枚举表，返回 (filename, df, enc)；找不到 404，读坏 409。"""
        from app.tools.csv_io import read_csv_with_encoding
        from app.tools.dataset import excel_tables, is_excel_file, table_paths
        target = dataset_target(ds)
        try:
            tp = table_paths(target)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(409, user_error("dataset", e, trace_id=secrets.token_hex(16), context=f"dataset={ds.id}")) from None
        multi = tp is not None
        for name, path in tp or [("df", target)]:
            fn = os.path.basename(path)
            try:
                if not is_excel_file(path):
                    if name == table:
                        df, enc = read_csv_with_encoding(path)
                        return fn, df, enc
                    continue
                stem = os.path.splitext(fn)[0]
                named = excel_tables(name if multi else stem, path)
                if not multi and len(named) == 1:
                    named = [("df", named[0][1])]
                for t, st in named:
                    if t == table:
                        return fn, st.df, "xlsx"
            except HTTPException:
                raise
            except Exception as e:  # noqa: BLE001
                raise HTTPException(409, user_error("dataset", e, trace_id=secrets.token_hex(16),
                                                    context=f"dataset={ds.id} file={fn}")) from None
        raise HTTPException(404, f"没有这张表：{table}")

    _keys_cache: dict = {}        # id(df) → {列序号: 比较键}；随 _view_cache 淘汰一起清

    def cell_keys(series, df=None, col: int | None = None) -> list:
        """单元格的比较键：与预览里显示的文本一致（preview_cell），缺失值为 None。传 df+col 时按列缓存（大表逐格转文本较慢）。"""
        if df is not None and col is not None:
            per = _keys_cache.get(id(df))
            if per is not None and col in per:
                return per[col]
        st = {"bidi_stripped": 0, "truncated_cells": 0}
        keys = [preview_cell(v, st) for v in series.tolist()]
        if df is not None and col is not None:
            with _view_lock:
                if any(v[1] is df for v in _view_cache.values()):
                    _keys_cache.setdefault(id(df), {})[col] = keys
        return keys

    def column_index(df, col: int):
        if not (0 <= col < len(df.columns)):
            raise HTTPException(422, f"列序号越界：{col}")
        return df.iloc[:, col]

    @app.get("/datasets/{dataset_id}/values", dependencies=[Depends(auth)])
    def column_values(dataset_id: str, table: str = Query(...), col: int = Query(..., ge=0), db=Depends(db_dep)):
        """列菜单：这一列在全表里的不同值和次数（按次数降序，最多 VIEW_VALUES_MAX 个）。"""
        _fn, df, _enc = load_one_table(get_or_404(db, Dataset, dataset_id), table)
        keys = cell_keys(column_index(df, col), df, col)
        counts: dict = {}
        for k in keys:
            counts[k] = counts.get(k, 0) + 1
        items = sorted(counts.items(), key=lambda kv: -kv[1])
        return {"rows": len(keys), "distinct": len(items), "truncated": len(items) > VIEW_VALUES_MAX,
                "values": [{"value": k, "count": n} for k, n in items[:VIEW_VALUES_MAX]]}

    @app.post("/datasets/{dataset_id}/view", dependencies=[Depends(auth)])
    def table_view(dataset_id: str, body: ViewBody, db=Depends(db_dep)):
        """全表排序 / 按值筛选后取前 rows 行，返回与 preview 同形的表，外加 matched_rows（筛选后的行数）。只读，不改数据集。"""
        import pandas as pd
        fn, df, enc = load_one_table(get_or_404(db, Dataset, dataset_id), body.table)
        mask = pd.Series(True, index=df.index)
        for c, keep in body.filters.items():
            try:
                ci = int(c)
            except ValueError:
                raise HTTPException(422, f"列序号不对：{c}") from None
            allowed = set(keep)
            mask &= pd.Series([k in allowed for k in cell_keys(column_index(df, ci), df, ci)], index=df.index)
        view = df[mask]
        if body.sort_col is not None:
            s = column_index(view, body.sort_col)
            num = pd.to_numeric(s, errors="coerce")
            key = num if num.notna().sum() == s.notna().sum() else s.astype("string")
            order = key.sort_values(ascending=body.sort_dir == "asc", na_position="last", kind="stable").index
            view = view.loc[order]
        out = preview_table(body.table, fn, view, enc, body.rows)
        out["total_rows"] = int(len(df))
        out["matched_rows"] = int(len(view))
        out["row_numbers"] = [int(df.index.get_loc(i)) + 1 for i in view.index[: body.rows]]
        return out

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

    # 阶段 6 D3（phase6-desktop.md §4，#149）：桌面壳启动 10 秒后查更新，查到就 PUT 过来；前端每分钟 GET 一次，
    # 有新版本就在顶部提示「更新并重启」。只存在内存里（重启即清），后端自己不联网。浏览器模式没人 PUT，永远是 null。
    app.state.desktop_update = None

    @app.put("/desktop/update", dependencies=[Depends(auth)])
    def put_desktop_update(body: DesktopUpdateIn):
        app.state.desktop_update = {"version": body.version, "notes": body.notes}
        return app.state.desktop_update

    @app.get("/desktop/update", dependencies=[Depends(auth)])
    def get_desktop_update():
        return {"available": app.state.desktop_update}

    # 阶段 7.5 第 2 步：代码导出（独立 .py）与结果表导出（CSV / xlsx），见 app/tools/export.py。
    # 鉴权与 /exports/png 相同（请求头 token）；写进 app.state.export_dir（桌面模式），没挂时写 default_export_dir()
    # ——内容由后端生成、不收前端字节，所以不像 PNG 那样只限桌面模式。文件名复用 clean_filename，重名编号、不覆盖。
    def export_source(db, message_id: str):
        """→ (消息, 会话, 数据集, 结果记录)。只有执行成功、带代码的助手消息能导出。"""
        m = get_or_404(db, Message, message_id)
        if m.role != "assistant":
            raise HTTPException(400, "只能导出助手消息")
        if m.status == "running":
            raise HTTPException(409, "这条消息还在分析中")
        try:
            rec = json.loads(m.result_json) if m.result_json else None
        except ValueError:
            rec = None
        if not rec or not rec.get("executed") or not (rec.get("code") or "").strip():
            raise HTTPException(409, "这一轮没有执行成功的代码，无法导出")
        s = get_or_404(db, ChatSession, m.session_id)
        ds = get_or_404(db, Dataset, s.dataset_id)
        return m, s, ds, rec

    def export_dir_now() -> str:
        from app.server.exports import default_export_dir
        return app.state.export_dir or default_export_dir()

    def export_stem(s: ChatSession, m: Message) -> str:
        return f"{s.title or 'DataChat 分析'}_{m.id[:6]}"

    def write_export(stem: str, data: bytes, suffix: str) -> str:
        from app.server.exports import ExportError, save_file
        try:
            return save_file(export_dir_now(), stem, data, suffix)
        except ExportError as e:
            raise HTTPException(400, str(e)) from None
        except OSError as e:
            logger.warning("导出写盘失败：%s", type(e).__name__)
            raise HTTPException(500, "写入下载文件夹失败") from None

    @app.post("/messages/{message_id}/export/code", dependencies=[Depends(auth)])
    def export_code(message_id: str, db=Depends(db_dep)):
        from app.tools.dataset import is_dict_file
        from app.tools.export import ExportError, build_script, unsafe_reasons
        m, s, ds, rec = export_source(db, message_id)
        code = rec["code"]
        bad = unsafe_reasons(code)
        if bad:
            raise HTTPException(422, "代码里有沙箱拦下的操作，导出后会在沙箱外执行，所以不导出：" + "；".join(bad[:5]))
        tables = [f for f in ds.files if not is_dict_file(f.filename)]
        msgs = list(s.messages)
        i = next((k for k, x in enumerate(msgs) if x.id == m.id), 0)
        q = msgs[i - 1] if i > 0 and msgs[i - 1].role == "user" else None      # 这一轮的提问（紧挨在前的用户消息）
        try:
            text = build_script(code, files=[(f.filename, f.sha256) for f in tables],
                                data_dir=os.path.dirname(tables[0].path) if tables else "",
                                multi_source=len(tables) > 1,
                                meta={"session_id": s.id, "session_title": s.title, "message_id": m.id,
                                      "question": q.content if q else "", "dataset_name": ds.name,
                                      "agent": rec.get("agent") or s.agent, "exported_at": now()})
        except ExportError as e:
            raise HTTPException(500, str(e)) from None
        path = write_export(export_stem(s, m), text.encode("utf-8"), ".py")
        logger.info("导出代码：%s", os.path.basename(path))
        return {"path": path, "filename": os.path.basename(path)}

    @app.post("/messages/{message_id}/export/result", dependencies=[Depends(auth)])
    def export_result(message_id: str, format: Literal["csv", "xlsx"] = Query("csv"), db=Depends(db_dep)):
        import tempfile
        from app.core.result import format_result
        from app.tools.dataset import load_data
        from app.tools.export import ExportError, result_table, to_csv_bytes, to_xlsx_bytes
        from app.tools.sandbox import run_code
        m, s, ds, rec = export_source(db, message_id)
        try:
            data, _ = load_data(dataset_target(ds))
        except Exception as e:  # noqa: BLE001
            raise HTTPException(409, user_error("dataset", e, trace_id=secrets.token_hex(16),
                                                context=f"export dataset={ds.id}")) from None
        # result 不存库（只存 result_text），用同一段代码、同一份数据在沙箱里重跑拿原对象
        with tempfile.TemporaryDirectory(prefix="datachat-export-") as tmp:
            result, _chart, err = run_code(rec["code"], data, os.path.join(tmp, "chart.png"), timeout=EXPORT_TIMEOUT)
        if err:
            logger.warning("导出结果表时重跑失败：%s", err.splitlines()[-1][:200] if err else "")
            raise HTTPException(409, "重新执行这段代码失败，无法导出结果表")
        try:
            payload = to_xlsx_bytes(result) if format == "xlsx" else to_csv_bytes(result)
        except ExportError as e:
            raise HTTPException(413, str(e)) from None
        frame, _ = result_table(result)
        path = write_export(export_stem(s, m), payload, "." + format)
        logger.info("导出结果表：%s（%d 字节）", os.path.basename(path), len(payload))
        return {"path": path, "filename": os.path.basename(path), "rows": int(frame.shape[0]),
                "columns": int(frame.shape[1]),
                "matches_original": format_result(result) == (rec.get("result_text") or "")}

    @app.post("/sessions/{session_id}/export", dependencies=[Depends(auth)])
    def export_session(session_id: str, body: SessionExportBody | None = None,
                       download: bool = Query(False), db=Depends(db_dep)):
        """整段会话导出为自包含 HTML（提问、回答、图表、结果数据）。download=1 直接回文件（浏览器模式），
        否则与代码 / 结果表导出一样写进「下载」文件夹，回 {path, filename}。"""
        from app.server.session_export import SessionExportError, build_html, decode_client_pngs, read_png
        s = get_or_404(db, ChatSession, session_id)
        ds = db.get(Dataset, s.dataset_id)
        try:
            client_pngs = decode_client_pngs(body.charts if body else None)
        except SessionExportError as e:
            raise HTTPException(400, str(e)) from None
        turns, q = [], None
        for m in s.messages:
            if m.role == "user":
                if q is not None:
                    turns.append({"question": q.content, "answer": "", "status": "none", "charts": [], "result_text": ""})
                q = m
                continue
            try:
                rec = json.loads(m.result_json) if m.result_json else {}
            except ValueError:
                rec = {}
            pngs = []
            for k, c in enumerate(rec.get("charts") or []):
                if isinstance(c, str):
                    c = {"png": c, "option": None}
                pngs.append(read_png(c.get("png"), chart_dir) if c.get("png") else client_pngs.get(m.id, {}).get(k))
            if not rec.get("charts") and rec.get("chart_path"):
                pngs.append(read_png(rec.get("chart_path"), chart_dir))
            turns.append({"question": q.content if q else "", "answer": m.content, "status": m.status,
                          "charts": pngs, "result_text": rec.get("result_text") or ""})
            q = None
        if q is not None:
            turns.append({"question": q.content, "answer": "", "status": "none", "charts": [], "result_text": ""})
        title = s.title or "DataChat 分析"
        page = build_html(title=title, dataset=ds.name if ds else "（已删除）", exported_at=now(), turns=turns)
        data = page.encode("utf-8")
        if download:
            from app.server.exports import clean_filename
            fn = clean_filename(title) + ".html"
            return Response(data, media_type="text/html; charset=utf-8",
                            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(fn)}"})
        path = write_export(title, data, ".html")
        logger.info("导出会话：%s（%d 轮）", os.path.basename(path), len(turns))
        return {"path": path, "filename": os.path.basename(path)}

    def check_xlsx(path, fn):
        """xlsx 上传后按解压后体积判（zip 头里各成员 file_size 之和）；坏文件 400，超限 413。"""
        from app.tools.excel_io import XlsxInvalidError, XlsxTooLargeError, check_size
        try:
            check_size(path)
        except XlsxTooLargeError as e:
            raise HTTPException(413, f"{e}：{fn}") from None
        except XlsxInvalidError as e:
            raise HTTPException(400, f"{e}：{fn}") from None

    @app.post("/datasets", dependencies=[Depends(auth)])
    def create_dataset(files: list[UploadFile] = File(...), name: str = Form(""), db=Depends(db_dep)):
        if not files or len(files) > MAX_FILES:
            raise HTTPException(400, f"需要 1–{MAX_FILES} 个文件")
        names = []
        for f in files:
            fn = os.path.basename((f.filename or "").replace("\\", "/"))
            if fn.lower().endswith(".xls"):
                raise HTTPException(400, f"不支持旧版 .xls 文件：{fn}。请在 Excel 里另存为 .xlsx 或 CSV 后上传")
            if not fn or fn.startswith(".") or not fn.lower().endswith(UPLOAD_SUFFIXES):
                raise HTTPException(400, f"只支持 CSV 或 xlsx 文件：{f.filename!r}")
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
                if fn.lower().endswith(".xlsx"):
                    check_xlsx(path, fn)
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

    # ---------------------------------------------------------------- 口径与规则（批 4b M2 / M10）
    def note_out(n: DatasetNote) -> dict:
        return {"id": n.id, "dataset_id": n.dataset_id, "kind": n.kind, "name": n.name, "body": n.body, "unit": n.unit,
                "synonyms": n.synonyms, "sha": n.sha, "source": n.source, "supersedes": n.supersedes,
                "retired_at": n.retired_at, "created_at": n.created_at}

    def active_notes(db, dataset_id: str) -> list[DatasetNote]:
        return list(db.scalars(select(DatasetNote).where(DatasetNote.dataset_id == dataset_id,
                                                         DatasetNote.retired_at.is_(None))
                               .order_by(DatasetNote.kind, DatasetNote.created_at, DatasetNote.name)))

    def find_active(db, dataset_id: str, kind: str, name: str) -> DatasetNote | None:
        return db.scalar(select(DatasetNote).where(DatasetNote.dataset_id == dataset_id, DatasetNote.kind == kind,
                                                   DatasetNote.name == name, DatasetNote.retired_at.is_(None)))

    def clean_or_400(raw: dict) -> dict:
        from app.memory.metrics import NoteError, clean
        try:
            return clean(raw)
        except NoteError as e:
            raise HTTPException(400, str(e)) from None

    def write_note(db, dataset_id: str, vals: dict, supersedes: DatasetNote | None = None) -> DatasetNote:
        """写一行新版本。supersedes 给出时先把旧行停用（同一事务里，部分唯一索引不会撞）。只追加，不改旧行内容。"""
        from app.memory.metrics import SOURCE, note_sha
        if supersedes is not None:
            supersedes.retired_at = now()
            db.flush()
        n = DatasetNote(dataset_id=dataset_id, **vals, sha=note_sha(vals), source=SOURCE,
                        supersedes=supersedes.id if supersedes is not None else None, created_at=now())
        db.add(n)
        db.flush()
        return n

    def get_note_or_404(db, dataset_id: str, note_id: str) -> DatasetNote:
        n = db.get(DatasetNote, note_id)
        if n is None or n.dataset_id != dataset_id:
            raise HTTPException(404, f"口径不存在：{note_id}")
        return n

    @app.get("/datasets/{dataset_id}/notes", dependencies=[Depends(auth)])
    def list_notes(dataset_id: str, history: bool = Query(False), db=Depends(db_dep)):
        get_or_404(db, Dataset, dataset_id)
        if not history:
            return [note_out(n) for n in active_notes(db, dataset_id)]
        rows = db.scalars(select(DatasetNote).where(DatasetNote.dataset_id == dataset_id)
                          .order_by(DatasetNote.kind, DatasetNote.name, DatasetNote.created_at))
        return [note_out(n) for n in rows]

    @app.post("/datasets/{dataset_id}/notes", dependencies=[Depends(auth)])
    def create_note(dataset_id: str, body: NoteIn, db=Depends(db_dep)):
        get_or_404(db, Dataset, dataset_id)
        vals = clean_or_400(body.model_dump())
        if find_active(db, dataset_id, vals["kind"], vals["name"]) is not None:
            raise HTTPException(409, f"已经有一条在用的「{vals['name']}」，请改用编辑")
        n = write_note(db, dataset_id, vals)
        db.commit()
        return note_out(n)

    @app.put("/datasets/{dataset_id}/notes/{note_id}", dependencies=[Depends(auth)])
    def update_note(dataset_id: str, note_id: str, body: NoteIn, db=Depends(db_dep)):
        old = get_note_or_404(db, dataset_id, note_id)
        if old.retired_at is not None:
            raise HTTPException(409, "这条口径已经停用或被新版本取代，不能再改")
        vals = clean_or_400(body.model_dump())
        from app.memory.metrics import note_sha
        if note_sha(vals) == old.sha:
            return note_out(old)              # 内容没变：不产生新版本
        clash = find_active(db, dataset_id, vals["kind"], vals["name"])
        if clash is not None and clash.id != old.id:
            raise HTTPException(409, f"已经有一条在用的「{vals['name']}」，请改用编辑")
        n = write_note(db, dataset_id, vals, supersedes=old)
        db.commit()
        return note_out(n)

    @app.delete("/datasets/{dataset_id}/notes/{note_id}", dependencies=[Depends(auth)], status_code=204)
    def retire_note(dataset_id: str, note_id: str, db=Depends(db_dep)):
        """软遗忘：只写 retired_at，不物理删行；已经停用的再停一次也是 204。"""
        n = get_note_or_404(db, dataset_id, note_id)
        if n.retired_at is None:
            n.retired_at = now()
            db.commit()
        return Response(status_code=204)

    def parse_import(raw: bytes, content_type: str) -> list[tuple[int, dict]]:
        """→ [(行号, 原始字段)]。CSV 的行号按文件行（表头是第 1 行），JSON 按数组下标从 1 起。"""
        if not raw.strip():
            raise HTTPException(400, "导入文件是空的")
        if "json" in (content_type or "").lower():
            try:
                data = json.loads(raw.decode("utf-8-sig"))
            except (UnicodeDecodeError, ValueError):
                raise HTTPException(400, "JSON 解析失败：请导入一个口径对象的数组") from None
            if not isinstance(data, list):
                raise HTTPException(400, "JSON 必须是数组")
            return [(i, x if isinstance(x, dict) else {"_bad": True}) for i, x in enumerate(data, 1)]
        import csv
        import io
        from app.tools.csv_io import CSVEncodingError, detect_encoding
        try:
            text = raw.decode(detect_encoding(raw), errors="strict")
        except (CSVEncodingError, UnicodeDecodeError) as e:
            raise HTTPException(400, str(e)) from None
        text = text.lstrip("\ufeff")
        reader = csv.DictReader(io.StringIO(text))
        cols = [str(c or "").strip().lower() for c in (reader.fieldnames or [])]
        if "kind" not in cols or "name" not in cols or "body" not in cols:
            raise HTTPException(400, "CSV 表头必须包含 kind,name,body（可选 unit,synonyms）")
        out = []
        for row in reader:
            row = {str(k or "").strip().lower(): v for k, v in row.items() if k is not None}
            if not any(str(v or "").strip() for v in row.values()):
                continue                       # 空行跳过
            out.append((reader.line_num, row))
        return out

    @app.post("/datasets/{dataset_id}/notes/import", dependencies=[Depends(auth)])
    async def import_notes(dataset_id: str, request: Request):
        """M10 导入：整批校验，任何一行不合法就整批拒绝（400，指出行号），不写一半。
        幂等：在用的同名行 sha 相同 → 跳过；sha 不同 → 新版本取代旧行（批 3 §5：不覆盖）；没有同名行 → 新增。"""
        with Session() as db:
            get_or_404(db, Dataset, dataset_id)
        raw = await request.body()
        if len(raw) > NOTES_IMPORT_MAX_BYTES:
            raise HTTPException(413, f"导入文件超过 {NOTES_IMPORT_MAX_BYTES // 1024} KB")
        from app.memory.metrics import NoteError, clean, note_sha
        rows = parse_import(raw, request.headers.get("content-type", ""))
        if len(rows) > NOTES_IMPORT_MAX_ROWS:
            raise HTTPException(400, f"一次最多导入 {NOTES_IMPORT_MAX_ROWS} 条")
        errors, vals, seen = [], [], {}
        for line, r in rows:
            try:
                if r.get("_bad"):
                    raise NoteError("每条口径必须是一个对象")
                v = clean(r)
            except NoteError as e:
                errors.append(f"第 {line} 行：{e}")
                continue
            key = (v["kind"], v["name"])
            if key in seen:
                errors.append(f"第 {line} 行：与第 {seen[key]} 行同名（{v['name']}）")
                continue
            seen[key] = line
            vals.append(v)
        if errors:
            raise HTTPException(400, "导入失败，没有写入任何一条：" + "；".join(errors[:20])
                                + (f"；另有 {len(errors) - 20} 处" if len(errors) > 20 else ""))
        if not vals:
            raise HTTPException(400, "导入文件里没有口径")
        added = updated = unchanged = 0
        with Session() as db:
            get_or_404(db, Dataset, dataset_id)
            for v in vals:
                cur = find_active(db, dataset_id, v["kind"], v["name"])
                if cur is None:
                    write_note(db, dataset_id, v)
                    added += 1
                elif cur.sha == note_sha(v):
                    unchanged += 1
                else:
                    write_note(db, dataset_id, v, supersedes=cur)
                    updated += 1
            db.commit()
        return {"added": added, "updated": updated, "unchanged": unchanged, "errors": []}

    @app.get("/datasets/{dataset_id}/notes/export", dependencies=[Depends(auth)])
    def export_notes(dataset_id: str, format: Literal["csv", "json"] = Query("csv"), db=Depends(db_dep)):
        """只导出在用的口径。CSV 的别名用 ; 分隔（和导入格式一致），带 BOM 方便 Excel 打开。"""
        get_or_404(db, Dataset, dataset_id)
        items = [{"kind": n.kind, "name": n.name, "body": n.body, "unit": n.unit, "synonyms": n.synonyms}
                 for n in active_notes(db, dataset_id)]
        if format == "json":
            return Response(json.dumps(items, ensure_ascii=False, indent=2), media_type="application/json",
                            headers={"Content-Disposition": 'attachment; filename="notes.json"'})
        import csv
        import io
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(["kind", "name", "body", "unit", "synonyms"])
        for x in items:
            w.writerow([x["kind"], x["name"], x["body"], x["unit"], x["synonyms"].replace(",", ";")])
        return Response("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="notes.csv"'})

    def notes_for_analysis(db, dataset_id: str) -> list[dict]:
        """post_message 传给 analyze 的口径：在用的行，纯 dict（app/core 不 import app/server）。"""
        return [{"kind": n.kind, "name": n.name, "body": n.body, "unit": n.unit, "synonyms": n.synonyms, "sha": n.sha}
                for n in active_notes(db, dataset_id)]

    def accepted_pairs_for(db, ds: Dataset, session_id: str) -> list[dict]:
        """M9：同一数据集指纹、其他会话里 👍 过的助手消息 → [{question, code}]。每轮现算，只看最近 SCAN_LIMIT 条 👍。
        数据集不可变（重新上传得到新 id），指纹相同的数据集（同一份文件重新上传）也算同一数据集。"""
        from app.memory.pairs import SCAN_LIMIT, dataset_fingerprint, eligible
        fp = dataset_fingerprint(ds.files)
        same = [d.id for d in db.scalars(select(Dataset)) if d.id == ds.id or dataset_fingerprint(d.files) == fp]
        rows = db.execute(
            select(Message, Feedback.rating)
            .join(Feedback, Feedback.message_id == Message.id)
            .join(ChatSession, ChatSession.id == Message.session_id)
            .where(ChatSession.dataset_id.in_(same), Message.session_id != session_id, Message.role == "assistant",
                   Message.status == "ok", Feedback.rating == "up")
            .order_by(Message.created_at.desc()).limit(SCAN_LIMIT)).all()
        out = []
        for m, rating in rows:
            try:
                r = json.loads(m.result_json) if m.result_json else None
            except ValueError:
                r = None
            if not eligible(r, m.status, rating):
                continue
            q = db.scalar(select(Message).where(Message.session_id == m.session_id, Message.role == "user",
                                                Message.created_at <= m.created_at)
                          .order_by(Message.created_at.desc()).limit(1))
            if q is not None and q.content.strip():
                out.append({"question": q.content, "code": r["code"]})
        return out

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

    def auto_title(db, s: ChatSession, question: str) -> str:
        """U5 自动标题：本地规则（app/server/titles.py），同一数据集重名追加（2）（3）。用户手动改的名字不走这里。"""
        taken = db.scalars(select(ChatSession.title).where(ChatSession.dataset_id == s.dataset_id,
                                                           ChatSession.id != s.id))
        return unique_title(session_title(question), taken)

    @app.patch("/sessions/{session_id}", dependencies=[Depends(auth)])
    def rename_session(session_id: str, body: SessionPatch, db=Depends(db_dep)):
        s = get_or_404(db, ChatSession, session_id)
        title = _CONTROL_CHARS.sub("", body.title).strip()[:120]
        if not title:                                    # U5（§4 已定 3）：清空 = 还原自动标题，用该会话的第一问重新生成
            first = next((m.content for m in s.messages if m.role == "user"), "")
            title = auto_title(db, s, first)
        s.title = title
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
        from app.memory.config import REWRITE_SETTING_KEY, SETTING_KEY, normalize_flag, resolve_memory_mode
        row = db.get(Setting, SETTING_KEY)
        mem_setting = row.value if row else None
        rw_row = db.get(Setting, REWRITE_SETTING_KEY)
        rw_setting = normalize_flag(rw_row.value) if rw_row else None   # 批 4a：只读下传，改写在 service.py 里做
        mode = resolve_memory_mode(mem_setting)
        # 上一轮是反问吗（clarify 的出口，2026-11-16）：从上一条 assistant 消息的
        # result_json 读 AnalysisResult.clarify。不加 DB 列 —— result_json 本来就是
        # to_record() 的全文（create_all 不会给旧表加列，加列等于强制迁移）。
        # 旧消息没有这个键，.get 缺省 False；反问轮 status 是 ok，result_json 必有值。
        prev_clarify = False
        for x in reversed(s.messages):
            if x.role == "assistant":
                try:
                    prev_clarify = bool((json.loads(x.result_json) if x.result_json else {}).get("clarify"))
                except ValueError:
                    prev_clarify = False
                break
        notes, pairs = [], []
        if mode != "off":
            history = turn_snapshots(s.messages)          # 阶段 6.6：两种 agent 都带（workflow 只用来折叠工作状态）
            notes = notes_for_analysis(db, s.dataset_id)  # 批 4b M2：口径在 memory_mode != off 时生效
            if mode == "full" and agent == "react":       # 批 4b M9：只在 full、只给 ReAct
                pairs = accepted_pairs_for(db, get_or_404(db, Dataset, s.dataset_id), session_id)
        else:
            history = turn_history(s.messages) if agent == "react" else None
        q = Message(session_id=session_id, role="user", content=body.content, created_at=now())
        a = Message(session_id=session_id, role="assistant", status="running", created_at=now())
        db.add_all([q, a])
        if not s.title:                                  # U5：只在标题为空时生成（用户改过的名字不覆盖）
            s.title = auto_title(db, s, body.content)
        s.updated_at = now()
        db.commit()
        msg_id = a.id
        session_title_now = s.title or ""

        kwargs = dict(agent=agent, trace_id=msg_id, log=False, memory_mode=mem_setting, rewrite=rw_setting,
                      prev_clarify=prev_clarify,
                      **(analyze_kwargs or {}))
        cfg, meta = llm_config_meta()     # 阶段 6.5：每条分析消息记下当时的连接名和模型（result.meta）
        if chat_model_factory is not None:
            kwargs["chat_model"] = chat_model_factory()
        else:
            kwargs["llm_config"] = cfg
        if history:
            kwargs["history"] = history
        if notes:
            kwargs["dataset_notes"] = notes
        if pairs:
            kwargs["accepted_pairs"] = pairs

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
                            attach_key_numbers(d["data"]["result"], ev.result)   # U3-2：落库（result_json）与外发（yield）同一份
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
                                          "X-User-Message-Id": q.id,
                                          # U5：HTTP 头只能是 latin-1，标题百分号编码；前端 decodeURIComponent
                                          "X-Session-Title": quote(session_title_now, safe="")})

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
        from app.memory.config import (DEFAULT_MODE, REWRITE_SETTING_KEY, SETTING_KEY, env_override, normalize,
                                       normalize_flag, resolve_memory_mode, resolve_rewrite, rewrite_env_override)
        # setting 是「这里存的值」：没存过就显示默认档本身（C-021 起是 state），不然设置页会出现
        # 「下拉框选 off、实际生效 state」这种自相矛盾的画面。
        memory = {"mode": resolve_memory_mode(st.get(SETTING_KEY)), "setting": normalize(st.get(SETTING_KEY)) or DEFAULT_MODE,
                  "env": env_override(),        # 阶段 6.6：mode 是实际生效值；env 非空时设置页提示被环境变量覆盖
                  "rewrite": resolve_rewrite(st.get(REWRITE_SETTING_KEY)),   # 批 4a：改写开关的实际生效值（env → settings → False）
                  # 批 4b：设置页要分开显示「这里存的值」和「被环境变量覆盖」（同 setting / env 的分法）
                  "rewrite_setting": bool(normalize_flag(st.get(REWRITE_SETTING_KEY))),
                  "rewrite_env": rewrite_env_override()}
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
            if isinstance(v, bool):              # 批 4a memory_rewrite：存 1 / 0（config.normalize_flag 两种都认）
                v = "1" if v else "0"
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
