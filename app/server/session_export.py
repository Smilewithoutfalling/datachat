"""整段会话导出成一个自包含 HTML（原型，proto/genie-shell）。

- 内容：标题、数据集、导出时间；每一轮的提问、回答正文（Markdown 子集转 HTML）、图表、结果表（result_text）。
- 图表：后端自己画的 PNG（matplotlib）从 chart_dir 读出来内嵌 base64；ECharts 结构化图只有 spec 没有 PNG，
  由前端用与屏幕同一条 prepare 离屏渲染成 PNG，随请求体传来（data URL），这里只认 PNG 文件头、限总大小。
- 所有文本先 html.escape，再做 Markdown 子集替换；不输出任何 <script>，文件可离线打开。
"""
from __future__ import annotations

import base64
import html
import os
import re

from app.server.exports import PNG_MAGIC

MAX_CLIENT_PNG_BYTES = 48 * 1024 * 1024        # 前端传来的图合计上限（解码后）
_DATA_URL = re.compile(r"^data:image/png;base64,([A-Za-z0-9+/=\s]+)$")


class SessionExportError(ValueError):
    pass


def decode_client_pngs(charts: dict | None) -> dict[str, dict[int, bytes]]:
    """{message_id: {index: data_url}} → {message_id: {index: png_bytes}}；非 PNG / 超限抛 SessionExportError。"""
    out: dict[str, dict[int, bytes]] = {}
    total = 0
    for mid, items in (charts or {}).items():
        if not isinstance(items, dict):
            raise SessionExportError("charts 格式不对")
        for k, url in items.items():
            m = _DATA_URL.match(url or "") if isinstance(url, str) else None
            if not m:
                raise SessionExportError("图表必须是 PNG data URL")
            try:
                raw = base64.b64decode(m.group(1), validate=False)
            except ValueError:
                raise SessionExportError("图表 base64 解码失败") from None
            if not raw.startswith(PNG_MAGIC):
                raise SessionExportError("图表不是 PNG")
            total += len(raw)
            if total > MAX_CLIENT_PNG_BYTES:
                raise SessionExportError("图表合计超过 48 MB")
            out.setdefault(str(mid), {})[int(k)] = raw
    return out


# ---------- Markdown 子集 ----------

def _inline(s: str) -> str:
    s = html.escape(s, quote=False)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    return s


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def md_to_html(text: str) -> str:
    lines = (text or "").replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        if not ln.strip():
            i += 1
            continue
        if ln.lstrip().startswith("```"):
            j = i + 1
            buf = []
            while j < len(lines) and not lines[j].lstrip().startswith("```"):
                buf.append(lines[j])
                j += 1
            out.append(f"<pre>{html.escape(chr(10).join(buf))}</pre>")
            i = j + 1
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", ln)
        if m:
            lv = min(len(m.group(1)) + 2, 6)               # 回答里的 # 降两级，不跟导出标题抢层级
            out.append(f"<h{lv}>{_inline(m.group(2))}</h{lv}>")
            i += 1
            continue
        if "|" in ln and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
            head = _cells(ln)
            i += 2
            rows = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append(_cells(lines[i]))
                i += 1
            t = ["<table><thead><tr>", *(f"<th>{_inline(c)}</th>" for c in head), "</tr></thead><tbody>"]
            for r in rows:
                t += ["<tr>", *(f"<td>{_inline(c)}</td>" for c in r), "</tr>"]
            out.append("".join(t) + "</tbody></table>")
            continue
        if re.match(r"^\s*([-*]|\d+\.)\s+", ln):
            ordered = bool(re.match(r"^\s*\d+\.", ln))
            items = []
            while i < len(lines) and re.match(r"^\s*([-*]|\d+\.)\s+", lines[i]):
                items.append(re.sub(r"^\s*([-*]|\d+\.)\s+", "", lines[i]))
                i += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{_inline(x)}</li>" for x in items) + f"</{tag}>")
            continue
        buf = []
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#{1,4}\s|\s*([-*]|\d+\.)\s|\s*```)", lines[i]):
            buf.append(_inline(lines[i]))
            i += 1
        out.append("<p>" + "<br>".join(buf) + "</p>")
    return "\n".join(out)


# ---------- 拼页面 ----------

_CSS = """
body{margin:0;background:#F5F5F7;color:#1D1D1F;font:15px/1.65 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
main{max-width:860px;margin:0 auto;padding:40px 24px 80px}
header h1{font-size:24px;margin:0 0 6px}
header p{margin:0;color:#6E6E73;font-size:13px}
.turn{background:#fff;border:1px solid #E5E5EA;border-radius:12px;padding:20px 24px;margin-top:20px}
.q{font-weight:600;font-size:16px;margin:0 0 12px;padding-left:10px;border-left:3px solid #0A66C2}
.answer h3,.answer h4,.answer h5,.answer h6{font-size:15px;margin:16px 0 6px}
figure{margin:16px 0}figure img{max-width:100%;border:1px solid #E5E5EA;border-radius:8px}
table{border-collapse:collapse;font-size:13px;margin:12px 0;width:100%}
th,td{padding:6px 10px;text-align:left;border-bottom:1px solid #E5E5EA}
th{background:#EEF4FB;font-weight:600}tbody tr:nth-child(even){background:#F7F7F9}
pre{background:#F7F7F9;border-radius:8px;padding:12px;overflow:auto;font-size:12px}
details summary{cursor:pointer;color:#6E6E73;font-size:13px}
.muted{color:#6E6E73;font-size:13px}
"""


def _img(png: bytes, alt: str) -> str:
    return f'<figure><img alt="{html.escape(alt)}" src="data:image/png;base64,{base64.b64encode(png).decode()}"></figure>'


def _local_time(iso: str) -> str:
    """后端 now() 是 UTC ISO；导出页面给人看，换成本机时区的「2026-11-27 15:05」。"""
    from datetime import datetime
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso


def build_html(*, title: str, dataset: str, exported_at: str, turns: list[dict]) -> str:
    """turns: [{"question", "answer", "answer_status", "charts": [png bytes or None], "result_text"}]"""
    exported_at = _local_time(exported_at)
    body = []
    for n, t in enumerate(turns, 1):
        parts = [f'<section class="turn"><p class="q">{n}. {html.escape(t["question"] or "（无提问）")}</p>']
        if t.get("answer"):
            parts.append(f'<div class="answer">{md_to_html(t["answer"])}</div>')
        elif t.get("answer_status") and t["answer_status"] != "done":
            parts.append('<p class="muted">这一轮没有完成。</p>')
        missing = 0
        for k, png in enumerate(t.get("charts") or []):
            if png:
                parts.append(_img(png, f"第 {n} 轮图表 {k + 1}"))
            else:
                missing += 1
        if missing:
            parts.append(f'<p class="muted">有 {missing} 张图未能导出，请在应用里查看。</p>')
        if t.get("result_text"):
            parts.append(f'<details><summary>结果数据</summary><pre>{html.escape(t["result_text"])}</pre></details>')
        parts.append("</section>")
        body.append("".join(parts))
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(title)}</title><style>{_CSS}</style></head><body><main>"
        f'<header><h1>{html.escape(title)}</h1><p>数据集：{html.escape(dataset)} · 导出时间：{html.escape(exported_at)}'
        f" · 共 {len(turns)} 轮</p></header>"
        + "".join(body)
        + "</main></body></html>"
    )


def read_png(path: str | None, chart_dir: str) -> bytes | None:
    """只读 chart_dir 里的 PNG（路径必须仍在 chart_dir 内）。"""
    if not path:
        return None
    root = os.path.realpath(chart_dir)
    p = os.path.realpath(path if os.path.isabs(path) else os.path.join(root, os.path.basename(path)))
    if not p.startswith(root + os.sep) or not os.path.isfile(p):
        return None
    with open(p, "rb") as f:
        raw = f.read()
    return raw if raw.startswith(PNG_MAGIC) else None
