"""公网中转：用 Cloudflare 免费快速隧道把本机上传页映射到公网。

不注册账号、无广告、上传页面完全由本程序提供。
隧道只上传/下载音频数据，电脑端始终是文件的最终归属。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Callable

from config import data_dir

MIRRORS = [
    "https://gh-proxy.com/https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe",
    "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe",
]

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def find_cloudflared() -> Path | None:
    exe_dir = Path(sys.executable).resolve().parent
    candidates = [
        data_dir() / "bin" / "cloudflared.exe",
        exe_dir / "tools" / "cloudflared.exe",
        exe_dir / "cloudflared.exe",
        Path(__file__).resolve().parent.parent / "tools" / "cloudflared.exe",
        Path(getattr(sys, "_MEIPASS", "")) / "tools" / "cloudflared.exe",
    ]
    which = shutil.which("cloudflared")
    if which:
        candidates.insert(0, Path(which))
    for c in candidates:
        try:
            if c and c.is_file() and c.stat().st_size > 8 * 1024 * 1024:
                return c
        except OSError:
            continue
    return None


def download_cloudflared(progress: Callable[[str, int], None]) -> Path | None:
    dest = data_dir() / "bin" / "cloudflared.exe"
    dest.parent.mkdir(parents=True, exist_ok=True)
    for url in MIRRORS:
        tmp = dest.with_suffix(".part")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=25) as resp, open(tmp, "wb") as f:
                total = int(resp.headers.get("Content-Length") or 0)
                got = 0
                while True:
                    chunk = resp.read(262144)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    if total:
                        progress("downloading", int(got * 100 / total))
                    else:
                        progress("downloading", -1)
            if tmp.stat().st_size > 20 * 1024 * 1024:
                tmp.replace(dest)
                return dest
            tmp.unlink(missing_ok=True)
        except Exception:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            continue
    return None


class Tunnel:
    """管理 cloudflared 子进程与公网地址。"""

    URL_RE = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")

    def __init__(self, port: int, on_change: Callable[[], None] | None = None):
        self.port = port
        self.on_change = on_change or (lambda: None)
        self.proc: subprocess.Popen | None = None
        self.url: str | None = None
        self.state = "off"          # off | downloading | starting | on | error
        self.message = ""
        self._lock = threading.Lock()
        self._reader: threading.Thread | None = None
        self._gen = 0               # 每次启动/停止自增，用于取消进行中的启动流程

    def status(self) -> dict:
        return {"state": self.state, "url": self.url, "message": self.message}

    def _notify(self) -> None:
        try:
            self.on_change()
        except Exception:
            pass

    def start(self) -> dict:
        with self._lock:
            if self.proc and self.proc.poll() is None:
                return self.status()
            self._gen += 1
            gen = self._gen
            self.state = "starting"
            self.message = "正在启动公网中转…"
            self.url = None
        self._notify()
        threading.Thread(target=self._run, args=(gen,), daemon=True).start()
        return self.status()

    def _alive(self, gen: int) -> bool:
        return gen == self._gen

    def _run(self, gen: int) -> None:
        exe = find_cloudflared()
        if not exe:
            self.state = "downloading"
            self.message = "正在下载中转组件（约 50MB，仅首次需要）…"

            def prog(_kind: str, pct: int) -> None:
                if not self._alive(gen):
                    raise RuntimeError("cancelled")
                self.message = ("正在下载中转组件 {}%…".format(pct)
                                if pct >= 0 else "正在下载中转组件…")
                self._notify()

            self._notify()
            try:
                exe = download_cloudflared(prog)
            except RuntimeError:
                return
            if not self._alive(gen):
                return
            if not exe:
                self.state = "error"
                self.message = "中转组件下载失败，请检查网络后重试，或改用局域网模式。"
                self._notify()
                return

        if not self._alive(gen):
            return

        self.state = "starting"
        self.message = "正在连接 Cloudflare 中转…"
        self._notify()
        try:
            proc = subprocess.Popen(
                [str(exe), "tunnel", "--url", f"http://127.0.0.1:{self.port}",
                 "--no-autoupdate", "--protocol", "http2"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW,
            )
        except Exception as e:  # noqa: BLE001
            self.state = "error"
            self.message = f"无法启动中转组件：{e}"
            self._notify()
            return

        if not self._alive(gen):
            try:
                proc.terminate()
            except Exception:
                pass
            return

        self.proc = proc
        self._reader = threading.Thread(target=self._read_loop, args=(proc, gen), daemon=True)
        self._reader.start()

        deadline = time.time() + 90
        while time.time() < deadline:
            if not self._alive(gen):
                return
            if self.url:
                return
            if proc.poll() is not None:
                self.state = "error"
                self.message = "中转进程已退出，请重试。"
                self._notify()
                return
            time.sleep(0.4)
        if not self.url and self._alive(gen):
            self.state = "error"
            self.message = "连接超时，可改用局域网模式。"
            self._notify()

    def _read_loop(self, proc: subprocess.Popen, gen: int) -> None:
        try:
            for raw in iter(proc.stderr.readline, b""):
                line = raw.decode("utf-8", "ignore").strip()
                m = self.URL_RE.search(line)
                if m and self.url != m.group(0) and self._alive(gen):
                    self.url = m.group(0)
                    self.state = "on"
                    self.message = "公网中转已连接"
                    self._notify()
        except Exception:
            pass
        finally:
            if self.proc is proc:
                self.proc = None
                if self.state != "off" and self._alive(gen):
                    self.state = "error" if not self.url else "off"
                    self.url = None
                    self.message = "中转已断开"
                    self._notify()

    def stop(self) -> dict:
        with self._lock:
            self._gen += 1          # 取消还在下载/启动中的流程
            p, self.proc = self.proc, None
            self.state = "off"
            self.url = None
            self.message = ""
        if p and p.poll() is None:
            try:
                p.terminate()
                p.wait(timeout=5)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        self._notify()
        return self.status()

    def shutdown(self) -> None:
        self.stop()
