"""API Key 存进系统钥匙串（阶段 4 第一步，B18 / THREAT_MODEL）。

Windows 上是"凭据管理器"（Windows Credential Manager），macOS 是钥匙串，Linux 桌面是 Secret Service。
Key 不再以明文写在 .env 里。

读取顺序（LLMConfig.from_env 调 resolve_api_key）：
1. 环境变量 DEEPSEEK_API_KEY：开发、CI、临时覆盖用，显式设置时优先；
2. 系统钥匙串：产品默认。
钥匙串不可用（如无桌面的 Linux / CI，没有后端）时不报错，按"未配置"处理，由调用方给出提示。

这只是缩小暴露面，不是消除：同一用户身份下运行的任何程序都能读凭据管理器，
沙箱逃逸后仍可能读到（见 docs/THREAT_MODEL.md）；沙箱子进程的环境变量里不含 Key，import 白名单里也没有 keyring。

命令行（Key 从不回显、从不打印）：
    python -m app.core.keystore status      看 Key 从哪里来
    python -m app.core.keystore set         交互输入并存入钥匙串
    python -m app.core.keystore migrate     把 .env 里的 DEEPSEEK_API_KEY 搬进钥匙串（之后请手动删掉 .env 里那一行）
    python -m app.core.keystore delete      从钥匙串删除
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Optional

SERVICE = "datachat"
ACCOUNT = "llm_api_key"
ENV_VAR = "DEEPSEEK_API_KEY"


def conn_account(connection_id: str) -> str:
    """阶段 6.5：每个连接单独一条凭据，SERVICE 不变、ACCOUNT = conn:<id>。旧的 llm_api_key 条目保留一个版本。"""
    return f"conn:{connection_id}"


class KeyStoreError(RuntimeError):
    """钥匙串不可用或写入失败。消息里不含 Key，也不含异常类型名、后端全限定名（T11：这条会经 400 到界面）；
    细节只进日志。"""


_log = logging.getLogger("datachat.keystore")


def _keyring():
    try:
        import keyring
        return keyring
    except Exception as e:  # noqa: BLE001
        _log.warning("keyring import failed: %s: %s", type(e).__name__, e)
        raise KeyStoreError("钥匙串组件不可用") from None


def backend_name() -> str:
    try:
        kr = _keyring()
        b = kr.get_keyring()
        return f"{type(b).__module__}.{type(b).__name__}"
    except Exception as e:  # noqa: BLE001
        _log.warning("keyring backend unavailable: %s: %s", type(e).__name__, e)
        return "不可用"


def _usable(kr) -> bool:
    from keyring.backends.fail import Keyring as FailKeyring
    try:
        from keyring.backends.chainer import ChainerBackend
    except Exception:  # noqa: BLE001
        ChainerBackend = ()
    b = kr.get_keyring()
    if isinstance(b, FailKeyring):
        return False
    if ChainerBackend and isinstance(b, ChainerBackend) and not b.backends:
        return False
    return True


def get_api_key(account: str = ACCOUNT) -> Optional[str]:
    """钥匙串里的 Key；没有或钥匙串不可用时返回 None（不抛异常）。account 默认是旧的 llm_api_key。"""
    try:
        kr = _keyring()
        if not _usable(kr):
            return None
        v = kr.get_password(SERVICE, account)
    except Exception:  # noqa: BLE001
        return None
    return v or None


def set_api_key(key: str, account: str = ACCOUNT) -> None:
    key = (key or "").strip()
    if not key:
        raise KeyStoreError("Key 为空")
    if any(c.isspace() for c in key):
        raise KeyStoreError("Key 里不应有空白字符（可能粘贴了多余内容）")
    kr = _keyring()
    if not _usable(kr):
        _log.warning("keyring unusable, backend=%s", backend_name())
        raise KeyStoreError("系统钥匙串不可用")
    try:
        kr.set_password(SERVICE, account, key)
    except Exception as e:  # noqa: BLE001
        _log.warning("keyring set_password failed: %s: %s", type(e).__name__, e)
        raise KeyStoreError("写入系统钥匙串失败") from None


def delete_api_key(account: str = ACCOUNT) -> bool:
    """删除成功返回 True；本来就没有返回 False。"""
    kr = _keyring()
    if not _usable(kr):
        _log.warning("keyring unusable, backend=%s", backend_name())
        raise KeyStoreError("系统钥匙串不可用")
    try:
        kr.delete_password(SERVICE, account)
        return True
    except kr.errors.PasswordDeleteError:
        return False


def resolve_api_key() -> tuple[Optional[str], Optional[str]]:
    """(key, 来源)：来源为 "env" / "keyring" / None。"""
    v = (os.getenv(ENV_VAR) or "").strip()
    if v:
        return v, "env"
    v = get_api_key()
    if v:
        return v, "keyring"
    return None, None


def _env_file_key(path: str) -> Optional[str]:
    try:
        from dotenv import dotenv_values
        return (dotenv_values(path).get(ENV_VAR) or "").strip() or None
    except Exception:  # noqa: BLE001
        return None


def main(argv=None) -> int:
    import argparse
    import getpass

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap = argparse.ArgumentParser(prog="python -m app.core.keystore", description="管理存在系统钥匙串里的 API Key")
    ap.add_argument("action", choices=["status", "set", "migrate", "delete"])
    ap.add_argument("--env-file", default=os.path.join(root, ".env"))
    a = ap.parse_args(argv)
    try:
        if a.action == "status":
            _, src = resolve_api_key()
            in_env_file = _env_file_key(a.env_file) is not None
            print(f"钥匙串后端：{backend_name()}")
            print(f"钥匙串里：{'已保存' if get_api_key() else '没有'}")
            print(f"当前生效：{ {'env': '环境变量 ' + ENV_VAR, 'keyring': '系统钥匙串'}.get(src, '未配置') }")
            if in_env_file:
                print(f"注意：{a.env_file} 里仍有明文 {ENV_VAR}；确认钥匙串里已保存后请删掉那一行。")
        elif a.action == "set":
            key = getpass.getpass("粘贴 API Key（不会显示）：")
            set_api_key(key)
            print("已保存到系统钥匙串。")
        elif a.action == "migrate":
            key = _env_file_key(a.env_file)
            if not key:
                print(f"{a.env_file} 里没有 {ENV_VAR}，无需迁移。")
                return 0
            set_api_key(key)
            print(f"已把 {a.env_file} 里的 {ENV_VAR} 存进系统钥匙串。请手动删掉 .env 里那一行，然后运行 status 确认。")
        elif a.action == "delete":
            print("已从钥匙串删除。" if delete_api_key() else "钥匙串里本来就没有。")
    except KeyStoreError as e:
        print(f"失败：{e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
