"""阶段 6.5 §2b / §6 第 1 条：服务商预设 app/core/providers.json 的 schema 校验。

schema 用 pydantic 写（extra=forbid 的严格模型），没有新增 jsonschema 依赖：pydantic 本来就是运行依赖。
规则：每条字段齐全且不多；协议合法；URL 是 https，本地服务商（group=local）可以是 http://localhost / 127.0.0.1；
只有 Azure 和「自定义」可以没有默认 Base URL（地址因人而异）；申请 Key 的链接是 https 或 null（不需要 Key 的必须 null）。
"""
import json
from typing import Literal, Optional
from urllib.parse import urlparse

import pytest
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.core import providers
from app.core.llm import PROTOCOLS

GROUPS = ("cn", "global", "local", "custom")
FIRST_BATCH = ("deepseek", "bailian", "volcengine", "moonshot", "zhipu", "siliconflow", "minimax", "hunyuan",
               "openai", "anthropic", "gemini", "azure", "openrouter", "groq", "mistral", "xai", "ollama",
               "lmstudio", "newapi", "custom")
EMPTY_URL_OK = ("azure", "custom")


class Quirks(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    no_stream_options: Optional[bool] = None
    no_array_content: Optional[bool] = None
    reasoning_replay: Optional[bool] = None
    thinking_param: Optional[Literal["enable_thinking", "thinking"]] = None


class Provider(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    name: str
    group: Literal["cn", "global", "local", "custom"]
    protocol: Literal["openai_chat", "openai_responses", "azure", "anthropic"]
    base_url: str
    needs_key: bool
    key_url: Optional[str]
    models: list[str]
    quirks: Quirks

    @field_validator("id")
    @classmethod
    def _id(cls, v):
        assert v and v == v.lower() and v.replace("_", "").isalnum(), f"id 只用小写字母数字：{v!r}"
        return v

    @field_validator("models")
    @classmethod
    def _models(cls, v):
        assert all(m and m == m.strip() for m in v), "模型名不能为空或带首尾空白"
        assert len(set(v)) == len(v), "模型名重复"
        return v

    @model_validator(mode="after")
    def _urls(self):
        if not self.base_url:
            assert self.id in EMPTY_URL_OK, f"{self.id}：只有 {EMPTY_URL_OK} 可以没有默认 Base URL"
        else:
            u = urlparse(self.base_url)
            assert u.netloc and " " not in self.base_url, self.base_url
            if self.group == "local":
                assert (u.scheme == "https" or (u.scheme == "http" and u.hostname in ("localhost", "127.0.0.1"))), \
                    f"{self.id}：本地服务商只能是 https 或 http://localhost：{self.base_url}"
            else:
                assert u.scheme == "https", f"{self.id}：非本地服务商必须 https：{self.base_url}"
        if self.key_url is not None:
            assert urlparse(self.key_url).scheme == "https" and urlparse(self.key_url).netloc, self.key_url
        if not self.needs_key:
            assert self.key_url is None, f"{self.id}：不需要 Key 就不该有申请链接"
        return self


def raw():
    with open(providers.PATH, encoding="utf-8") as f:
        return json.load(f)


def test_every_entry_matches_schema():
    items = raw()["providers"]
    for p in items:
        Provider.model_validate(p)          # 失败时 pydantic 指出哪一条哪个字段


def test_ids_unique_and_first_batch_present():
    ids = [p["id"] for p in raw()["providers"]]
    assert len(ids) == len(set(ids))
    assert set(FIRST_BATCH) <= set(ids), set(FIRST_BATCH) - set(ids)
    assert ids[-1] == "custom"              # 下拉里「自定义」放最后


def test_top_level_lists_consistent_with_code():
    d = raw()
    assert tuple(d["protocols"]) == PROTOCOLS
    assert set(d["custom_protocols"]) <= set(PROTOCOLS) and "azure" not in d["custom_protocols"]
    assert tuple(d["groups"]) == GROUPS
    assert set(d) == {"_comment", "protocols", "custom_protocols", "groups", "providers"}


def test_catalog_drops_comment():
    assert "_comment" not in providers.catalog()
    assert providers.catalog()["providers"][0]["id"] == "deepseek"


@pytest.mark.parametrize("bad,why", [
    ({"base_url": "http://api.example.com/v1"}, "非本地 http"),
    ({"group": "local", "base_url": "http://10.0.0.2:11434/v1"}, "本地但不是 localhost"),
    ({"protocol": "gemini"}, "协议不合法"),
    ({"extra_field": 1}, "多字段"),
    ({"quirks": {"thinking_param": "on"}}, "怪癖取值不合法"),
    ({"needs_key": False}, "不需要 Key 却有申请链接"),
    ({"base_url": ""}, "非 Azure / 自定义没有默认地址"),
])
def test_schema_rejects(bad, why):
    good = dict(raw()["providers"][0])
    with pytest.raises(Exception):
        Provider.model_validate({**good, **bad})


def test_schema_rejects_missing_field():
    good = dict(raw()["providers"][0])
    good.pop("key_url")
    with pytest.raises(Exception):
        Provider.model_validate(good)


def test_effective_quirks_preset_then_override():
    q = providers.effective_quirks("deepseek")
    assert q == {"no_stream_options": False, "no_array_content": False, "reasoning_replay": True, "thinking_param": None}
    q = providers.effective_quirks("deepseek", {"reasoning_replay": False, "no_array_content": True, "junk": 1})
    assert q["reasoning_replay"] is False and q["no_array_content"] is True and "junk" not in q
    assert providers.effective_quirks("zhipu")["thinking_param"] == "thinking"
    assert providers.effective_quirks("zhipu", {"thinking_param": None})["thinking_param"] is None
    assert providers.effective_quirks("nope") == providers.effective_quirks("custom")
