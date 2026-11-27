"""生成 DataChat 自动更新的签名密钥对（phase6-desktop.md §4 第 2 条，issue #149）。

为什么有这个脚本：私钥只能由 S 本人生成、本人粘贴进 GitHub Secret，不进仓库、不进对话；而 S 本机不装 Node，
用不了 `tauri signer generate`。这里只用 Python 标准库，生成与 `tauri signer generate`（tauri-cli 2.12.6，
内部是 rsign2 / minisign 格式）完全相同格式的密钥：
- 私钥：base64( "untrusted comment: rsign encrypted secret key\\n" + base64(158 字节的 minisign 加密私钥) + "\\n" )，
  用 scrypt（opslimit=1048576, memlimit=33554432，与 tauri CLI 默认一致）以口令加密；
- 公钥：base64( "untrusted comment: minisign public key: <KEYID>\\n" + base64("Ed" + keyid + 公钥32字节) + "\\n" )。
tests/test_gen_update_key.py 用 tauri CLI 生成的密钥做了格式对照，并用生成的私钥签名、用公钥验签。

用法（Windows cmd，conda 环境 dc）：
    python scripts\\desktop\\gen_update_key.py  [输出私钥文件，默认 %USERPROFILE%\\datachat-update.key]
按提示输入两次口令（不能为空）。然后：
1. 打开私钥文件，把**整段内容**粘贴到 GitHub 仓库 Settings → Secrets and variables → Actions →
   New repository secret，名字 TAURI_SIGNING_PRIVATE_KEY；
2. 口令另建一个 secret：TAURI_SIGNING_PRIVATE_KEY_PASSWORD；
3. 把屏幕上打印的**公钥**发给我（公钥可以公开），我写进 tauri.conf.json；
4. 私钥文件和口令自己妥善保存。丢了就再也发不了已装用户能接受的更新（只能让大家手动重装）。
"""
from __future__ import annotations

import base64
import getpass
import hashlib
import os
import secrets
import struct
import sys
from pathlib import Path

# ---------------------------------------------------------------- Ed25519（RFC 8032 参考实现，只需由种子算公钥和签名）
_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_I = pow(2, (_P - 1) // 4, _P)


def _inv(x: int) -> int:
    return pow(x, _P - 2, _P)


def _xrecover(y: int) -> int:
    xx = (y * y - 1) * _inv(_D * y * y + 1)
    x = pow(xx, (_P + 3) // 8, _P)
    if (x * x - xx) % _P != 0:
        x = (x * _I) % _P
    if x % 2 != 0:
        x = _P - x
    return x


_BY = 4 * _inv(5) % _P
_B = (_xrecover(_BY), _BY, 1, _xrecover(_BY) * _BY % _P)  # 扩展坐标 (X, Y, Z, T)


def _add(p, q):
    a = (p[1] - p[0]) * (q[1] - q[0]) % _P
    b = (p[1] + p[0]) * (q[1] + q[0]) % _P
    c = 2 * p[3] * q[3] * _D % _P
    d = 2 * p[2] * q[2] % _P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _mul(s: int, p):
    q = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            q = _add(q, p)
        p = _add(p, p)
        s >>= 1
    return q


def _encode(p) -> bytes:
    zi = _inv(p[2])
    x, y = p[0] * zi % _P, p[1] * zi % _P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _secret_scalar(seed: bytes) -> tuple[int, bytes]:
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def ed25519_public(seed: bytes) -> bytes:
    a, _ = _secret_scalar(seed)
    return _encode(_mul(a, _B))


def ed25519_sign(seed: bytes, msg: bytes) -> bytes:
    a, prefix = _secret_scalar(seed)
    pk = _encode(_mul(a, _B))
    r = int.from_bytes(hashlib.sha512(prefix + msg).digest(), "little") % _L
    rb = _encode(_mul(r, _B))
    k = int.from_bytes(hashlib.sha512(rb + pk + msg).digest(), "little") % _L
    return rb + ((r + k * a) % _L).to_bytes(32, "little")


# ---------------------------------------------------------------- minisign / rsign2 格式
OPSLIMIT = 1048576      # tauri signer generate 生成的密钥里读出来的值
MEMLIMIT = 33554432


def _scrypt_params(ops: int, mem: int) -> tuple[int, int, int]:
    """libsodium crypto_pwhash_scryptsalsa208sha256 的 pickparams，返回 (log2 N, r, p)。"""
    r = 8
    ops = max(ops, 32768)
    if ops < mem // 32:
        p = 1
        max_n = ops // (r * 4)
    else:
        max_n = mem // (r * 128)
        p = None
    n_log2 = 1
    while n_log2 < 63 and (1 << n_log2) <= max_n // 2:
        n_log2 += 1
    if p is None:
        maxrp = min((ops // 4) // (1 << n_log2), 0x3FFFFFFF)
        p = maxrp // r
    return n_log2, r, p


def _keystream(password: bytes, salt: bytes, ops: int, mem: int, n: int) -> bytes:
    n_log2, r, p = _scrypt_params(ops, mem)
    return hashlib.scrypt(password, salt=salt, n=1 << n_log2, r=r, p=p, maxmem=2 ** 31 - 1, dklen=n)


def make_keypair(password: str, *, seed: bytes | None = None, key_id: bytes | None = None,
                 salt: bytes | None = None) -> tuple[str, str]:
    """返回 (私钥字符串, 公钥字符串)，都是 tauri 能直接用的 base64 文本。"""
    seed = seed or secrets.token_bytes(32)
    key_id = key_id or secrets.token_bytes(8)
    salt = salt or secrets.token_bytes(32)
    pk = ed25519_public(seed)
    sk = seed + pk
    chk = hashlib.blake2b(b"Ed" + key_id + sk, digest_size=32).digest()
    plain = key_id + sk + chk
    ks = _keystream(password.encode("utf-8"), salt, OPSLIMIT, MEMLIMIT, len(plain))
    enc = bytes(a ^ b for a, b in zip(plain, ks))
    raw = b"Ed" + b"Sc" + b"B2" + salt + struct.pack("<QQ", OPSLIMIT, MEMLIMIT) + enc
    sk_text = "untrusted comment: rsign encrypted secret key\n" + base64.b64encode(raw).decode() + "\n"
    kid_hex = key_id[::-1].hex().upper()
    pk_text = (f"untrusted comment: minisign public key: {kid_hex}\n"
               + base64.b64encode(b"Ed" + key_id + pk).decode() + "\n")
    return base64.b64encode(sk_text.encode()).decode(), base64.b64encode(pk_text.encode()).decode()


def read_secret(private_key: str, password: str) -> tuple[bytes, bytes]:
    """解开私钥，返回 (key_id, seed)；口令错或格式错抛 ValueError。测试与自检用。"""
    lines = base64.b64decode(private_key).decode().splitlines()
    raw = base64.b64decode(lines[1])
    if raw[:6] != b"EdScB2" or len(raw) != 158:
        raise ValueError("不是 rsign/minisign 加密私钥")
    salt = raw[6:38]
    ops, mem = struct.unpack("<QQ", raw[38:54])
    enc = raw[54:]
    ks = _keystream(password.encode("utf-8"), salt, ops, mem, len(enc))
    plain = bytes(a ^ b for a, b in zip(enc, ks))
    key_id, sk, chk = plain[:8], plain[8:72], plain[72:]
    if hashlib.blake2b(b"Ed" + key_id + sk, digest_size=32).digest() != chk:
        raise ValueError("口令不对或私钥损坏")
    return key_id, sk[:32]


def main(argv: list[str]) -> int:
    out = Path(argv[1]) if len(argv) > 1 else Path(os.path.expanduser("~")) / "datachat-update.key"
    if out.exists():
        print(f"{out} 已存在，为防覆盖旧私钥，请换一个文件名或先挪走它。")
        return 1
    pw = getpass.getpass("设置私钥口令（输入时不显示）：")
    if not pw or pw != getpass.getpass("再输入一次："):
        print("口令为空或两次不一致，没有生成。")
        return 1
    print("生成中（scrypt 加密大约需要几秒）……")
    sk, pk = make_keypair(pw)
    read_secret(sk, pw)  # 自检：能用同一口令解开
    out.write_text(sk, encoding="ascii")
    print(f"\n私钥已写入：{out}\n  → 整段内容粘贴到 GitHub Secret  TAURI_SIGNING_PRIVATE_KEY")
    print("  → 口令另建 Secret            TAURI_SIGNING_PRIVATE_KEY_PASSWORD")
    print("\n公钥（可以公开，发给 Hark 写进 tauri.conf.json）：\n")
    print(pk)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
