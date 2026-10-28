"""模型连接（阶段 6.5 §3、§4）：connections 表的读写、迁移、生效连接 → LLMConfig，以及 /providers、/connections* 路由。

- Key 只在系统钥匙串（ACCOUNT=conn:<id>），任何响应都不带 Key，只带 {needed, configured}。
- 没有任何连接时，生效的是只读虚拟连接「环境变量」（id=env）：DEEPSEEK_* 环境变量 + 旧 settings 行（model / base_url）
  的覆盖，和阶段 6.5 之前的 llm_config 一字不差——浏览器模式、CI、e2e 都靠它。
- 迁移（§4）：启动时跑一次（settings.connections_migrated 作标记），旧 settings 的 model / base_url 加上钥匙串里旧的
  llm_api_key 生成一个连接并设为生效；旧条目不删（保留一个版本）。
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Literal, Optional
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core import keystore, providers
from app.core.errors import NO_KEY_MESSAGE, user_error
from app.core.llm import LLMConfig, LLMError, list_models, ping, probe_tools
from app.server.db import Connection, Setting, now

logger = logging.getLogger("datachat.connections")

ENV_ID = "env"
ENV_NAME = "环境变量"
ACTIVE_KEY = "active_connection"
MIGRATED_KEY = "connections_migrated"
ENV_PROBE_KEY = "env_probe"
MIGRATED_NAME_DEEPSEEK = "DeepSeek"
MIGRATED_NAME_CUSTOM = "我的连接"
# 不需要 Key 的服务商（Ollama、LM Studio）：OpenAI SDK 要求一个非空 api_key，Ollama 文档写明"必填但忽略"
NO_KEY_PLACEHOLDER = "not-needed"
NAME_MAX = 60
LEGACY_KEYS = ("model", "base_url", "timeout")
DEEPSEEK_HOST = "api.deepseek.com"


class QuirksIn(BaseModel):
    no_stream_options: Optional[bool] = None
    no_array_content: Optional[bool] = None
    reasoning_replay: Optional[bool] = None
    thinking_param: Optional[Literal["enable_thinking", "thinking"]] = None


class ExtraIn(BaseModel):
    deployment: Optional[str] = Field(None, max_length=200)
    thinking: Optional[bool] = None
    quirks: Optional[QuirksIn] = None


class ConnectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=NAME_MAX)
    provider: str = Field(min_length=1, max_length=32)
    protocol: Optional[str] = Field(None, max_length=32)
    base_url: Optional[str] = Field(None, max_length=500)
    model: str = Field("", max_length=200)
    extra: Optional[ExtraIn] = None


class ConnectionPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=NAME_MAX)
    provider: Optional[str] = Field(None, min_length=1, max_length=32)
    protocol: Optional[str] = Field(None, max_length=32)
    base_url: Optional[str] = Field(None, max_length=500)
    model: Optional[str] = Field(None, max_length=200)
    extra: Optional[ExtraIn] = None


class KeyIn(BaseModel):
    api_key: str = Field(min_length=1, max_length=512)


# ------------------------------------------------------------------ 读写小工具
def get_setting(db, key: str) -> Optional[str]:
    row = db.get(Setting, key)
    return row.value if row is not None else None


def put_setting(db, key: str, value: str) -> None:
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value


def _loads(s: Optional[str], default):
    try:
        v = json.loads(s) if s else default
    except ValueError:
        return default
    return v if isinstance(v, type(default)) else default


def has_connections(db) -> bool:
    return db.scalar(select(Connection.id).limit(1)) is not None


def active_row(db) -> Optional[Connection]:
    """生效连接。active_connection 指向的行不在了（被删、库被手改）而还有别的连接时，取最早建的那个并写回。"""
    cid = get_setting(db, ACTIVE_KEY)
    row = db.get(Connection, cid) if cid else None
    if row is None:
        row = db.scalars(select(Connection).order_by(Connection.created_at)).first()
        if row is not None:
            put_setting(db, ACTIVE_KEY, row.id)
            db.commit()
    return row


def needs_key(provider_id: str) -> bool:
    p = providers.get(provider_id)
    return True if p is None else bool(p["needs_key"])


def stored_extra(row: Connection) -> dict:
    return _loads(row.extra, {})


def effective_extra(row: Connection) -> dict:
    ex = stored_extra(row)
    return {**ex, "quirks": providers.effective_quirks(row.provider, ex.get("quirks"))}


def conn_key(row: Connection) -> Optional[str]:
    return keystore.get_api_key(keystore.conn_account(row.id))


def timeout_overrides(db) -> dict:
    """超时仍是全局设置（§3）：settings.timeout，坏值不生效（同旧 llm_config）。"""
    v = get_setting(db, "timeout")
    try:
        return {"timeout": float(v)} if v else {}
    except ValueError:
        return {}


def legacy_overrides(db) -> dict:
    """没有连接时，旧 settings 行（model / base_url / timeout）覆盖环境变量——阶段 6.5 之前的 llm_config 原样。"""
    st = {r.key: r.value for r in db.scalars(select(Setting).where(Setting.key.in_(LEGACY_KEYS)))}
    over = {k: v for k, v in st.items() if v}
    if "timeout" in over:
        try:
            over["timeout"] = float(over["timeout"])
        except ValueError:
            over.pop("timeout")
    return over


def config_for(db, row: Connection) -> LLMConfig:
    key = conn_key(row)
    if not key and not needs_key(row.provider):
        key = NO_KEY_PLACEHOLDER
    return LLMConfig.from_env(**timeout_overrides(db)).with_(
        model=row.model, api_key=key or None, base_url=row.base_url, protocol=row.protocol, extra=effective_extra(row))


def env_config(db) -> LLMConfig:
    return LLMConfig.from_env(**legacy_overrides(db))


def active_config(db) -> tuple[LLMConfig, dict]:
    """(LLMConfig, {"id", "name"})：生效连接；没有任何连接时是「环境变量」虚拟连接。"""
    row = active_row(db)
    if row is None:
        return env_config(db), {"id": ENV_ID, "name": ENV_NAME}
    return config_for(db, row), {"id": row.id, "name": row.name}


def probe_valid(probe: Optional[dict], model: str) -> Optional[dict]:
    """probe 按「连接 + 模型」算（§2d）：model 对不上就当没测过。"""
    return probe if isinstance(probe, dict) and probe.get("model") == model else None


def connection_out(row: Connection, active_id: Optional[str]) -> dict:
    key_set = conn_key(row) is not None
    return {"id": row.id, "name": row.name, "provider": row.provider, "protocol": row.protocol,
            "base_url": row.base_url, "model": row.model, "extra": stored_extra(row),
            "quirks": effective_extra(row)["quirks"], "probe": probe_valid(_loads(row.probe, {}) or None, row.model),
            "created_at": row.created_at, "updated_at": row.updated_at, "active": row.id == active_id,
            "readonly": False, "key": {"needed": needs_key(row.provider), "configured": key_set}}


def env_out(db) -> dict:
    cfg = env_config(db)
    _, src = keystore.resolve_api_key()
    return {"id": ENV_ID, "name": ENV_NAME, "provider": "deepseek", "protocol": "openai_chat",
            "base_url": cfg.base_url, "model": cfg.model, "extra": {}, "quirks": providers.effective_quirks("custom"),
            "probe": probe_valid(_loads(get_setting(db, ENV_PROBE_KEY), {}) or None, cfg.model),
            "created_at": None, "updated_at": None, "active": True, "readonly": True,
            "key": {"needed": True, "configured": src is not None, "source": src}}


# ------------------------------------------------------------------ 校验
def provider_or_400(pid: str) -> dict:
    p = providers.get(pid)
    if p is None:
        raise HTTPException(400, f"未知服务商：{pid}")
    return p


def _protocol_for(p: dict, given: Optional[str]) -> str:
    """自定义可以选协议（OpenAI 兼容 / Responses / Anthropic）；其余服务商的协议由预设定死，传了别的就 400。"""
    if p["id"] == providers.CUSTOM:
        proto = given or p["protocol"]
        if proto not in providers.custom_protocols():
            raise HTTPException(400, f"自定义连接的协议只能是 {', '.join(providers.custom_protocols())}")
        return proto
    if given and given != p["protocol"]:
        raise HTTPException(400, f"{p['name']} 的协议是 {p['protocol']}，不能改")
    return p["protocol"]


def base_url_for(p: dict, given: Optional[str]) -> str:
    url = (given or "").strip() or p["base_url"]
    if not url:
        raise HTTPException(400, f"{p['name']} 需要填 Base URL")
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.netloc:
        raise HTTPException(400, "Base URL 要以 http:// 或 https:// 开头")
    return url


def _extra_json(old: dict, given: Optional[ExtraIn]) -> dict:
    if given is None:
        return old
    out = dict(old)
    d = given.model_dump(exclude_unset=True)
    for k in ("deployment", "thinking"):
        if k in d:
            if d[k] in (None, ""):
                out.pop(k, None)
            else:
                out[k] = d[k].strip() if isinstance(d[k], str) else d[k]
    if "quirks" in d:
        out["quirks"] = {k: v for k, v in (d["quirks"] or {}).items()}
        if not out["quirks"]:
            out.pop("quirks")
    return out


def _clean_name(name: str) -> str:
    from app.core.text import CONTROL_CHARS
    n = CONTROL_CHARS.sub("", name).strip()
    if not n:
        raise HTTPException(400, "连接名不能为空")
    return n[:NAME_MAX]


# ------------------------------------------------------------------ 迁移（§4）
def migrate_legacy(Session) -> Optional[str]:
    """第一次启动新版时执行一次。返回新连接的 id（没东西可迁时 None）。

    - 旧 settings 的 model / base_url 和钥匙串里旧的 llm_api_key（不看环境变量：环境变量不是存储，下一次启动照样在）
      三者都没有 → 空库，不建连接（环境变量虚拟连接照常生效）。
    - base_url 为空或主机是 api.deepseek.com → 服务商 DeepSeek，命名「DeepSeek」；其他地址 → 「自定义」，命名「我的连接」。
    - model 为空时用当时实际生效的模型名（环境变量 DEEPSEEK_MODEL，否则默认值），迁移前后调的是同一个模型。
    - Key 复制到 conn:<id>；旧条目不删。迁移后设为生效连接。
    """
    with Session() as db:
        if get_setting(db, MIGRATED_KEY):
            return None
        new_id = None
        if not has_connections(db):
            model = (get_setting(db, "model") or "").strip()
            base = (get_setting(db, "base_url") or "").strip()
            key = keystore.get_api_key()
            if model or base or key:
                host = (urlparse(base).hostname or "") if base else ""
                deepseek = not base or host == DEEPSEEK_HOST
                p = providers.get(providers.DEEPSEEK if deepseek else providers.CUSTOM)
                row = Connection(name=MIGRATED_NAME_DEEPSEEK if deepseek else MIGRATED_NAME_CUSTOM,
                                 provider=p["id"], protocol=p["protocol"], base_url=base or p["base_url"],
                                 model=model or LLMConfig.from_env().model, extra="{}")
                db.add(row)
                db.flush()
                new_id = row.id
                if key:
                    try:
                        keystore.set_api_key(key, keystore.conn_account(row.id))
                    except keystore.KeyStoreError as e:
                        logger.warning("迁移：Key 复制到连接 %s 失败：%s", row.id, e)
                put_setting(db, ACTIVE_KEY, row.id)
                logger.info("迁移：旧设置生成连接 %s（%s）", row.id, row.provider)
        put_setting(db, MIGRATED_KEY, now())
        db.commit()
        return new_id


# ------------------------------------------------------------------ 路由
def register(app: FastAPI, Session, auth: Callable, db_dep: Callable, test_lock: threading.Lock) -> None:

    def row_or_404(db, cid: str) -> Connection:
        if cid == ENV_ID:
            raise HTTPException(400, "「环境变量」是只读的虚拟连接，改环境变量或新建一个连接")
        row = db.get(Connection, cid)
        if row is None:
            raise HTTPException(404, f"连接不存在：{cid}")
        return row

    def listing(db) -> dict:
        rows = list(db.scalars(select(Connection).order_by(Connection.created_at)))
        if not rows:
            return {"active": ENV_ID, "items": [env_out(db)]}
        act = active_row(db)
        aid = act.id if act else None
        return {"active": aid, "items": [connection_out(r, aid) for r in rows]}

    def ensure_unique(db, name: str, exclude: Optional[str] = None):
        other = db.scalar(select(Connection).where(Connection.name == name))
        if other is not None and other.id != exclude:
            raise HTTPException(409, f"已有同名连接：{name}")

    def commit_unique(db):
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "已有同名连接") from None

    @app.get("/providers", dependencies=[Depends(auth)])
    def get_providers():
        return providers.catalog()

    @app.get("/connections", dependencies=[Depends(auth)])
    def list_connections(db=Depends(db_dep)):
        return listing(db)

    @app.post("/connections", dependencies=[Depends(auth)])
    def create_connection(body: ConnectionIn, db=Depends(db_dep)):
        p = provider_or_400(body.provider)
        extra = _extra_json({}, body.extra)
        model = body.model.strip() or ((extra.get("deployment") or "") if p["protocol"] == "azure" else "")
        if not model:
            raise HTTPException(400, "模型名不能为空")
        first = not has_connections(db)
        name = _clean_name(body.name)
        ensure_unique(db, name)
        row = Connection(name=name, provider=p["id"], protocol=_protocol_for(p, body.protocol),
                         base_url=base_url_for(p, body.base_url), model=model, extra=json.dumps(extra, ensure_ascii=False))
        db.add(row)
        db.flush()
        if first:   # 第一个连接直接生效：此前生效的是环境变量虚拟连接，建了连接后它就不再生效了（§3）
            put_setting(db, ACTIVE_KEY, row.id)
        commit_unique(db)
        return connection_out(row, active_row(db).id)

    @app.put("/connections/{cid}", dependencies=[Depends(auth)])
    def update_connection(cid: str, body: ConnectionPatch, db=Depends(db_dep)):
        row = row_or_404(db, cid)
        d = body.model_dump(exclude_unset=True)
        before = (row.provider, row.protocol, row.base_url, row.model, row.extra)
        if d.get("name") is not None:
            name = _clean_name(d["name"])
            ensure_unique(db, name, row.id)      # 先查再赋值：赋值后查询会 autoflush，先撞 UNIQUE
            row.name = name
        p = provider_or_400(d.get("provider") or row.provider)
        if p["id"] != row.provider:
            row.provider = p["id"]
            row.protocol = _protocol_for(p, d.get("protocol"))
            row.base_url = base_url_for(p, d.get("base_url"))
        else:
            if "protocol" in d:
                row.protocol = _protocol_for(p, d["protocol"])
            if "base_url" in d:
                row.base_url = base_url_for(p, d["base_url"])
        if "extra" in d:
            row.extra = json.dumps(_extra_json(stored_extra(row), body.extra), ensure_ascii=False)
        if d.get("model") is not None:
            m = d["model"].strip() or ((stored_extra(row).get("deployment") or "") if row.protocol == "azure" else "")
            if not m:
                raise HTTPException(400, "模型名不能为空")
            row.model = m
        if (row.provider, row.protocol, row.base_url, row.extra) != before[:3] + (before[4],):
            row.probe = None      # 换了地址 / 协议 / 怪癖，旧测试结果作废；只换模型时 probe 按 model 自然失效
        row.updated_at = now()
        commit_unique(db)
        act = active_row(db)
        return connection_out(row, act.id if act else None)

    @app.delete("/connections/{cid}", dependencies=[Depends(auth)])
    def delete_connection(cid: str, db=Depends(db_dep)):
        row = row_or_404(db, cid)
        try:
            keystore.delete_api_key(keystore.conn_account(row.id))
        except keystore.KeyStoreError as e:   # 钥匙串不可用时这一行照样删；凭据留在钥匙串里，日志记一笔
            logger.warning("删除连接 %s：钥匙串删除失败：%s", row.id, e)
        db.delete(row)
        if get_setting(db, ACTIVE_KEY) == cid:
            put_setting(db, ACTIVE_KEY, "")
        db.commit()
        return listing(db)    # 删的是生效连接：active_row 取最早建的那个；一个都不剩就回到环境变量

    def key_status(row: Connection) -> dict:
        return {"needed": needs_key(row.provider), "configured": conn_key(row) is not None}

    @app.put("/connections/{cid}/api-key", dependencies=[Depends(auth)])
    def put_conn_key(cid: str, body: KeyIn, db=Depends(db_dep)):
        row = row_or_404(db, cid)
        try:
            keystore.set_api_key(body.api_key, keystore.conn_account(row.id))
        except keystore.KeyStoreError as e:
            raise HTTPException(400, str(e)) from None
        row.probe = None
        db.commit()
        return key_status(row)

    @app.delete("/connections/{cid}/api-key", dependencies=[Depends(auth)])
    def delete_conn_key(cid: str, db=Depends(db_dep)):
        row = row_or_404(db, cid)
        try:
            keystore.delete_api_key(keystore.conn_account(row.id))
        except keystore.KeyStoreError as e:
            raise HTTPException(400, str(e)) from None
        row.probe = None
        db.commit()
        return key_status(row)

    @app.post("/connections/{cid}/activate", dependencies=[Depends(auth)])
    def activate(cid: str, db=Depends(db_dep)):
        row = row_or_404(db, cid)
        put_setting(db, ACTIVE_KEY, row.id)
        db.commit()
        return listing(db)

    def resolve(db, cid: str) -> tuple[LLMConfig, Optional[Connection], bool]:
        """(cfg, 行或 None（环境变量）, 是否需要 Key)。环境变量虚拟连接只在没有任何连接时存在。"""
        if cid == ENV_ID:
            if has_connections(db):
                raise HTTPException(404, "已有连接，环境变量不再生效")
            return env_config(db), None, True
        row = db.get(Connection, cid)
        if row is None:
            raise HTTPException(404, f"连接不存在：{cid}")
        return config_for(db, row), row, needs_key(row.provider)

    def scrubbed(text: str, cfg: LLMConfig) -> str:
        """T11 的 _KEY 只认 sk- 开头的 Key；别家的 Key（AIza…、xxx.yyy）上游回显时按原值再打一遍码。"""
        k = cfg.api_key
        return text.replace(k, "***") if k and k != NO_KEY_PLACEHOLDER and len(k) >= 8 else text

    def fail(e: LLMError, cfg: LLMConfig, t0: float, trace_id: str) -> dict:
        return {"ok": False, "llm_kind": e.kind, "latency_ms": round((time.monotonic() - t0) * 1000),
                "message": scrubbed(user_error("llm", e, trace_id=trace_id), cfg)}

    @app.post("/connections/{cid}/test", dependencies=[Depends(auth)])
    def test_connection(cid: str, db=Depends(db_dep)):
        """§2d：两步——连接（ping）+ 工具调用（只有一个工具、tool_choice 强制）。结果存进 probe。
        和 /settings/test 共用一把锁：同一时间只许一个测试，第二个 409。"""
        cfg, row, need = resolve(db, cid)
        if not test_lock.acquire(blocking=False):
            raise HTTPException(409, "已有一个测试连接在进行")
        try:
            trace_id = secrets.token_hex(16)
            out: dict = {"model": cfg.model}
            if need and not cfg.api_key:
                out["connect"] = {"ok": False, "llm_kind": "no_key", "latency_ms": 0,
                                  "message": user_error("text", NO_KEY_MESSAGE, trace_id=trace_id)}
                out["tools"] = None
            else:
                t0 = time.monotonic()
                try:
                    ping(cfg)
                    out["connect"] = {"ok": True, "latency_ms": round((time.monotonic() - t0) * 1000)}
                except LLMError as e:
                    out["connect"] = fail(e, cfg, t0, trace_id)
                if not out["connect"]["ok"]:
                    out["tools"] = None    # 连不上就不测工具调用
                else:
                    t1 = time.monotonic()
                    try:
                        has = probe_tools(cfg)
                        out["tools"] = {"ok": has, "latency_ms": round((time.monotonic() - t1) * 1000)}
                        if not has:
                            out["tools"]["message"] = "模型没有按要求调用工具：这个模型（或网关）可能不支持工具调用。"
                    except LLMError as e:
                        out["tools"] = fail(e, cfg, t1, trace_id)
                        # 400 这类被拒（参数不认 tools / tool_choice）判作不支持；超时、5xx 是没测出来，不下结论
                        out["tools"]["ok"] = False if e.kind in ("bad_request",) or e.kind.startswith("http_4") else None
            tools_ok = out["tools"]["ok"] if out["tools"] else None
            probe = {"model": cfg.model, "connect": out["connect"]["ok"], "tools": tools_ok,
                     "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            out["probe"] = probe
            out["ok"] = bool(out["connect"]["ok"]) and tools_ok is not False
            if row is None:
                put_setting(db, ENV_PROBE_KEY, json.dumps(probe))
            else:
                row.probe = json.dumps(probe)
            db.commit()
            return out
        finally:
            test_lock.release()

    @app.get("/connections/{cid}/models", dependencies=[Depends(auth)])
    def get_models(cid: str, db=Depends(db_dep)):
        """读服务商的模型列表（10 秒超时，不重试）。失败时返回预设里的模型和原因（T11 文案），前端照样能下拉。"""
        cfg, row, need = resolve(db, cid)
        preset = (providers.get(row.provider) if row is not None else providers.get(providers.DEEPSEEK)) or {}
        fallback = list(preset.get("models") or [])
        trace_id = secrets.token_hex(16)
        if need and not cfg.api_key:
            return {"source": "preset", "models": fallback,
                    "reason": user_error("text", NO_KEY_MESSAGE, trace_id=trace_id)}
        if cfg.protocol == "azure":
            return {"source": "preset", "models": fallback, "reason": "Azure 按部署名调用，没有可列出的模型，请填部署名。"}
        try:
            ids = list_models(cfg)
        except LLMError as e:
            return {"source": "preset", "models": fallback, "llm_kind": e.kind,
                    "reason": scrubbed(user_error("llm", e, trace_id=trace_id), cfg)}
        return {"source": "remote", "models": ids}


def legacy_env_source(key: str) -> bool:
    return bool(os.getenv({"model": "DEEPSEEK_MODEL", "base_url": "DEEPSEEK_BASE_URL",
                           "timeout": "DATACHAT_LLM_TIMEOUT"}[key]))
