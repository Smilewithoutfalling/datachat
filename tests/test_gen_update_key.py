"""scripts/desktop/gen_update_key.py：生成的密钥与 tauri signer（tauri-cli 2.12.6）格式一致（issue #149）。

另外在沙箱里做过端到端核对（DEVLOG [226]）：本脚本生成的私钥交给 `tauri signer sign` 能签名，签名能用本脚本的公钥验过。
"""
import base64
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("gen_update_key", ROOT / "scripts" / "desktop" / "gen_update_key.py")
g = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(g)

# 一次性测试密钥：tauri signer generate --ci -p "" 生成（口令为空），只用于格式对照，不用于任何发布。
TAURI_SK = "dW50cnVzdGVkIGNvbW1lbnQ6IHJzaWduIGVuY3J5cHRlZCBzZWNyZXQga2V5ClJXUlRZMEl5Q0laenZPemVqUDF3TW1Sbzhab2dZeC9EZnhkV2pMUWNURzM3K1VPQjkrRUFBQkFBQUFBQUFBQUFBQUlBQUFBQVRZRUxkbXd0dnF1VGFuWmtRQjRFY2RaVG9jZ0pHZnRsS1ZUVFoxZnpnWVNhZC9ZVHAwcm5tSGpSTVp2V25HZ2pJT2dmVXZlUXV6bmxlS2tpNHNmWUkvblpLc3JQRVVrT0JmbFUxWm1YempjOEZDTnNRUWZGUHBYNlJEVkhMQ08xZzJRb1VVUzJrNm89Cg=="
TAURI_PK = "dW50cnVzdGVkIGNvbW1lbnQ6IG1pbmlzaWduIHB1YmxpYyBrZXk6IDg1N0ZEOEMzNjFGNDhENTIKUldSU2pmUmh3OWgvaFJtL1dDaTZvRi9YeFpMTnN6RUZxTFJ1Z2syL3ZOa0taeDFWVVpLTW9ZSm8K"


def test_reads_tauri_generated_key_and_matches_its_public_key():
    key_id, seed = g.read_secret(TAURI_SK, "")
    pk_raw = base64.b64decode(base64.b64decode(TAURI_PK).decode().splitlines()[1])
    assert pk_raw[:2] == b"Ed" and pk_raw[2:10] == key_id
    assert g.ed25519_public(seed) == pk_raw[10:]
    raw = base64.b64decode(base64.b64decode(TAURI_SK).decode().splitlines()[1])
    import struct
    assert struct.unpack("<QQ", raw[38:54]) == (g.OPSLIMIT, g.MEMLIMIT)


def test_generated_key_has_tauri_layout_and_roundtrips():
    sk, pk = g.make_keypair("口令 pw", seed=bytes(range(32)), key_id=b"\x01" * 8, salt=b"\x02" * 32)
    sk_lines = base64.b64decode(sk).decode().splitlines()
    pk_lines = base64.b64decode(pk).decode().splitlines()
    tk = base64.b64decode(TAURI_SK).decode().splitlines()
    tp = base64.b64decode(TAURI_PK).decode().splitlines()
    assert sk_lines[0] == tk[0] and len(base64.b64decode(sk_lines[1])) == len(base64.b64decode(tk[1])) == 158
    assert pk_lines[0].startswith("untrusted comment: minisign public key: ") and tp[0].startswith(
        "untrusted comment: minisign public key: ")
    assert pk_lines[0].endswith("0101010101010101")
    key_id, seed = g.read_secret(sk, "口令 pw")
    assert key_id == b"\x01" * 8 and seed == bytes(range(32))
    with pytest.raises(ValueError):
        g.read_secret(sk, "wrong")


def test_ed25519_rfc8032_vector_1():
    seed = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
    assert g.ed25519_public(seed).hex() == "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
    assert g.ed25519_sign(seed, b"").hex() == (
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555"
        "fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")


def test_main_refuses_to_overwrite(tmp_path, monkeypatch):
    out = tmp_path / "k.key"
    out.write_text("old")
    assert g.main(["x", str(out)]) == 1
    assert out.read_text() == "old"
