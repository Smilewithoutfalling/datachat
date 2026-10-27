"""桌面端「导出 PNG」落盘（阶段 6 收尾，S 10-27 本机试装：WebView2 里 data URL + <a download> 没反应）。

壳里没有下载处理器，前端在桌面模式下把 PNG 字节 POST 给后端，由后端写进用户的「下载」文件夹。
只在 app.state.export_dir 不为 None 时启用（app.server.__main__ 带 --desktop 才挂）；浏览器模式照旧走 <a download>。

防线（THREAT_MODEL：文件名是用户字符串离开画布的出口）：
- 只收 PNG：校验 8 字节文件头，大小上限 MAX_PNG_BYTES；
- 文件名后端再清一遍（不信任前端 safeFilename）：删控制符和 bidi、换掉路径分隔符和 Windows 非法字符、限长、保留名前加 _、
  一律以 .png 结尾；只取 basename，写入路径必须仍在 export_dir 里；
- 重名自动编号「名字 (1).png」，用 open(..., "xb") 独占创建，不覆盖已有文件。
"""
from __future__ import annotations

import os
import re
import unicodedata

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MAX_PNG_BYTES = 64 * 1024 * 1024
NAME_MAX = 60
FALLBACK = "图表"
MAX_SUFFIX = 999

_DROP = re.compile("[\u0000-\u001f\u007f-\u009f\u2028\u2029\u200e\u200f\u061c\u202a-\u202e\u2066-\u2069]")
_ILLEGAL = re.compile(r'[\\/:*?"<>|]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


class ExportError(ValueError):
    pass


def clean_filename(name: str | None) -> str:
    """清洗后的文件名主干（不含 .png）。"""
    s = name or ""
    if s.lower().endswith(".png"):
        s = s[:-4]
    s = unicodedata.normalize("NFC", s)
    s = _DROP.sub("", s)
    s = _ILLEGAL.sub("_", s)
    s = re.sub(r"\s+", " ", s)
    s = s[:NAME_MAX]                       # 限长在去首尾空格 / 点之前，免得截断重新造出尾随的点
    s = s.strip(" .")
    if not s:
        s = FALLBACK
    if s.split(".")[0].rstrip().upper() in _RESERVED:
        s = "_" + s
    return s


def default_export_dir() -> str:
    """用户的「下载」文件夹：DATACHAT_EXPORT_DIR；Windows 用已知文件夹 FOLDERID_Downloads（用户可能把它挪到 D 盘）；
    其他系统或取不到时用 ~/Downloads。"""
    if os.getenv("DATACHAT_EXPORT_DIR"):
        return os.getenv("DATACHAT_EXPORT_DIR")
    if os.name == "nt":
        try:
            return _known_downloads()
        except Exception:  # noqa: BLE001
            pass
    return os.path.join(os.path.expanduser("~"), "Downloads")


def _known_downloads() -> str:  # pragma: no cover - 只在 Windows 上跑（desktop.yml 安装冒烟）
    import ctypes
    from ctypes import wintypes
    import uuid

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_ubyte * 8)]

    u = uuid.UUID("{374DE290-123F-4565-9164-39C4925E467B}")
    g = GUID(u.fields[0], u.fields[1], u.fields[2], (ctypes.c_ubyte * 8)(*u.bytes[8:]))
    p = ctypes.c_wchar_p()
    if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(p)) != 0:
        raise OSError("SHGetKnownFolderPath failed")
    try:
        return p.value
    finally:
        ctypes.windll.ole32.CoTaskMemFree(p)


def save_png(export_dir: str, filename: str | None, data: bytes) -> str:
    """写入 export_dir，返回完整路径。不是 PNG / 太大时抛 ExportError。"""
    if len(data) > MAX_PNG_BYTES:
        raise ExportError("图片太大")
    if not data.startswith(PNG_MAGIC):
        raise ExportError("只接受 PNG 图片")
    root = os.path.realpath(export_dir)
    os.makedirs(root, exist_ok=True)
    stem = clean_filename(os.path.basename((filename or "").replace("\\", "/")))
    for i in range(MAX_SUFFIX + 1):
        name = f"{stem}.png" if i == 0 else f"{stem} ({i}).png"
        path = os.path.join(root, name)
        if os.path.dirname(os.path.realpath(path)) != root:   # 纵深防御：清洗后不应出现，出现就拒绝
            raise ExportError("文件名无效")
        try:
            with open(path, "xb") as f:
                f.write(data)
            return path
        except FileExistsError:
            continue
    raise ExportError("同名文件太多")
