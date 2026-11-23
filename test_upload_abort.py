"""回归测试：手机端中途取消上传时的清理行为。

覆盖三件事：
1. 传到一半就断线 —— 上传目录里不能留 `.part` 半截文件；
2. 读流时抛出 ConnectionResetError —— 转成 ClientGone，不当成 500 错误；
3. 正常传完 —— 文件落盘，`.part` 消失。

用法：python test_upload_abort.py
"""
from __future__ import annotations

import io
import socket
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "app"))

import server as server_mod  # noqa: E402


class FakeStore:
    """只记录调用，不碰真实的 state.json。"""

    def __init__(self) -> None:
        self.added: list[str] = []

    def add_paths(self, paths, source: str = ""):
        self.added.extend(str(p) for p in paths)
        return [{"id": "fake", "name": self.added[-1], "path": self.added[-1]}]

    def bump_upload(self) -> None:
        pass

    def find_by_path(self, _p):
        return None


def case_abort_over_socket(app, port: int) -> bool:
    """发一半请求体就断开连接，模拟老师在手机上取消上传。"""
    s = socket.create_connection(("127.0.0.1", port), timeout=3)
    head = (
        f"POST /api/upload?t={app.token} HTTP/1.1\r\n"
        f"Host: 127.0.0.1:{port}\r\n"
        "Content-Type: application/octet-stream\r\n"
        "X-Filename: abort-test.mp3\r\n"
        "Content-Length: 500000\r\n"
        "Connection: close\r\n\r\n"
    ).encode()
    s.sendall(head + b"\x00" * 4096)
    s.close()
    time.sleep(0.8)
    left = [p.name for p in Path(app.upload_dir).iterdir()]
    if left:
        print(f"  ✗ 断开后仍有残留：{left}")
        return False
    print("  ✓ 断开后上传目录为空")
    return True


def case_reset_during_read(app) -> bool:
    """流的 read() 直接抛 ConnectionResetError。"""

    class Boom(io.RawIOBase):
        def readable(self) -> bool:
            return True

        def readinto(self, b):  # noqa: D401
            raise ConnectionResetError("forcibly closed")

    try:
        app.handle_upload("reset.mp3", Boom(), 1024)
    except server_mod.ClientGone:
        left = [p.name for p in Path(app.upload_dir).iterdir()]
        if left:
            print(f"  ✗ 异常后仍有残留：{left}")
            return False
        print("  ✓ 读到一半断流：抛 ClientGone 且无残留")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  ✗ 抛了非预期异常：{type(e).__name__}: {e}")
        return False
    print("  ✗ 没有抛 ClientGone")
    return False


def case_normal_upload(app) -> bool:
    """正常上传应当落盘。"""
    payload = b"ID3" + b"\x00" * 2048
    res = app.handle_upload("normal.mp3", io.BytesIO(payload), len(payload))
    files = sorted(p.name for p in Path(app.upload_dir).iterdir())
    if res.get("size") != len(payload):
        print(f"  ✗ 字节数不对：{res.get('size')} != {len(payload)}")
        return False
    if any(f.endswith(".part") for f in files):
        print(f"  ✗ 留下了 .part：{files}")
        return False
    if "normal.mp3" not in files:
        print(f"  ✗ 文件没落盘：{files}")
        return False
    print(f"  ✓ 正常上传落盘：{files}")
    return True


def main() -> int:
    app = server_mod.AppServer()
    tmpdir = Path(tempfile.mkdtemp(prefix="elp-abort-"))
    app.upload_dir = tmpdir
    app.store = FakeStore()          # 不污染真实播放列表
    app.start()
    print(f"测试服务已启动：127.0.0.1:{app.port}，上传目录 {tmpdir}")

    results = [
        case_abort_over_socket(app, app.port),
        case_reset_during_read(app),
        case_normal_upload(app),
    ]
    app.stop()
    ok = all(results)
    print("\n结果：", "全部通过" if ok else "有失败项")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
