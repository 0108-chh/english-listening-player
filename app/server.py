"""内置 HTTP 服务：桌面界面、手机上传页、音频流、二维码。"""
from __future__ import annotations

import io
import json
import os
import re
import socket
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from config import (APP_NAME, APP_VERSION, AUDIO_EXTS, MIME_BY_EXT,
                    data_dir, default_upload_dir, static_dir)
from store import Store, list_audio_files, media_id, pretty_title
from tunnel import Tunnel

MAX_UPLOAD = 1024 * 1024 * 800  # 800MB


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------
def lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.4)
        s.connect(("223.5.5.5", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return "127.0.0.1"


def pick_port(start: int = 8765, end: int = 8800) -> int:
    """找一个真正空闲的端口。

    Windows 上 SO_REUSEADDR 会允许两个进程绑定同一端口（互相抢请求），
    所以探测时用 SO_EXCLUSIVEADDRUSE，避免和已有实例冲突。
    """
    for port in range(start, end):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if os.name == "nt":
                s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            s.bind(("0.0.0.0", port))
            return port
        except OSError:
            continue
        finally:
            s.close()
    raise RuntimeError("没有可用端口")


class LocalHTTPServer(ThreadingHTTPServer):
    # Windows 下必须关闭地址复用，否则会和已在运行的实例抢同一端口
    allow_reuse_address = os.name != "nt"
    daemon_threads = True


def get_token() -> str:
    f = data_dir() / "room.txt"
    try:
        if f.exists():
            t = f.read_text("utf-8").strip()
            if re.fullmatch(r"[0-9a-f]{6,10}", t):
                return t
    except OSError:
        pass
    import secrets
    t = secrets.token_hex(3)
    try:
        f.write_text(t, "utf-8")
    except OSError:
        pass
    return t


def safe_name(raw: str, fallback: str) -> str:
    name = urllib.parse.unquote(raw or "").replace("\\", "/").split("/")[-1]
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name).strip().strip(".")
    if not name:
        name = fallback
    stem, ext = os.path.splitext(name)
    stem = (stem[:120] or "上传音频").strip()
    return stem + ext.lower()


def unique_path(folder: Path, name: str) -> Path:
    p = folder / name
    if not p.exists():
        return p
    stem, ext = os.path.splitext(name)
    i = 2
    while True:
        cand = folder / f"{stem}({i}){ext}"
        if not cand.exists():
            return cand
        i += 1


# --------------------------------------------------------------------------
# 服务主体
# --------------------------------------------------------------------------
class ClientGone(Exception):
    """手机端在上传过程中断开（取消、切后台、Wi-Fi 掉线）。

    这种情况下响应已经写不回去了，调用方只需要关掉连接，不要当成服务端错误。
    """


class AppServer:
    def __init__(self) -> None:
        self.store = Store()
        self.port = pick_port()
        self.token = get_token()
        self.public_url: str | None = None
        self.tunnel_state = "off"      # off | downloading | starting | on | error
        self.tunnel_error = ""
        self._qr_cache: dict[tuple[str, int], bytes] = {}
        self._lock = threading.Lock()
        self.upload_dir = Path(self.store.data.get("upload_dir") or default_upload_dir())
        try:
            self.upload_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.upload_dir = data_dir() / "uploads"
            self.upload_dir.mkdir(parents=True, exist_ok=True)
        self._httpd: ThreadingHTTPServer | None = None
        self.tunnel = Tunnel(self.port, on_change=self._sync_tunnel)
        self._clean_partials()

    def _clean_partials(self) -> None:
        """清掉上次异常退出（断电、强杀进程）遗留的 .part 半截文件。"""
        try:
            for p in self.upload_dir.glob("*.part"):
                try:
                    p.unlink()
                except OSError:
                    pass
        except OSError:
            pass

    def _sync_tunnel(self) -> None:
        st = self.tunnel.status()
        self.tunnel_state = st["state"]
        self.public_url = st["url"]
        self.tunnel_error = "" if st["state"] != "error" else st.get("message", "")

    # ---------- 地址 ----------
    def lan_base(self) -> str:
        return f"http://{lan_ip()}:{self.port}"

    def upload_base(self) -> str:
        if self.store.data.get("channel") == "tunnel" and self.public_url:
            return self.public_url
        return self.lan_base()

    def upload_url(self) -> str:
        return f"{self.upload_base()}/u/{self.token}"

    def info(self) -> dict:
        return {
            "app": APP_NAME,
            "version": APP_VERSION,
            "port": self.port,
            "lan_ip": lan_ip(),
            "lan_url": self.lan_base(),
            "upload_url": self.upload_url(),
            "channel": self.store.data.get("channel", "lan"),
            "tunnel_state": self.tunnel_state,
            "tunnel_error": self.tunnel_error,
            "public_url": self.public_url,
            "upload_dir": str(self.upload_dir),
            "token": self.token,
            "tunnel": self.tunnel.status(),
        }

    # ---------- 二维码 ----------
    def qr_png(self, url: str, size: int = 460) -> bytes:
        key = (url, size)
        with self._lock:
            if key in self._qr_cache:
                return self._qr_cache[key]
        import qrcode
        from PIL import Image
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=2)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#10141c", back_color="white").convert("RGB")
        box = max(1, size // img.size[0])
        img = img.resize((img.size[0] * box, img.size[1] * box), Image.NEAREST)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        data = buf.getvalue()
        with self._lock:
            self._qr_cache[key] = data
        return data

    def qr_svg(self, url: str) -> bytes:
        """矢量二维码：任意尺寸都清晰锐利。"""
        key = (url, 0)
        with self._lock:
            if key in self._qr_cache:
                return self._qr_cache[key]
        import qrcode
        import qrcode.image.svg
        qr = qrcode.QRCode(
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            border=2,
            box_size=10,
            image_factory=qrcode.image.svg.SvgPathImage,
        )
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image()
        buf = io.BytesIO()
        img.save(buf)
        data = buf.getvalue()
        # 去掉固定 mm 尺寸，交给 CSS 自适应；开启 crisptEdges 让模块边界锐利
        data = re.sub(rb'width="[\d.]+mm" height="[\d.]+mm"', b"", data, count=1)
        data = data.replace(b"<svg ", b'<svg shape-rendering="crispEdges" ', 1)
        with self._lock:
            self._qr_cache[key] = data
        return data

    # ---------- 上传处理 ----------
    def handle_upload(self, filename: str, stream, length: int) -> dict:
        name = safe_name(filename, f"上传音频-{int(time.time())}.mp3")
        if os.path.splitext(name)[1] not in AUDIO_EXTS:
            raise ValueError("只支持 mp3 / wav / m4a / flac 等音频文件")
        dest = unique_path(self.upload_dir, name)
        tmp = dest.with_suffix(dest.suffix + ".part")
        remaining = length
        written = 0
        try:
            with open(tmp, "wb") as f:
                while remaining > 0:
                    chunk = stream.read(min(262144, remaining))
                    if not chunk:
                        break
                    f.write(chunk)
                    written += len(chunk)
                    remaining -= len(chunk)
        except (ConnectionResetError, BrokenPipeError, TimeoutError) as e:
            tmp.unlink(missing_ok=True)      # 不留半截文件在“老师上传”目录里
            raise ClientGone(str(e)) from None
        except OSError:
            tmp.unlink(missing_ok=True)      # 磁盘满 / 无权限之类的真错误，交给上层报 500
            raise
        if written == 0:
            tmp.unlink(missing_ok=True)
            raise ValueError("没有收到文件内容")
        if remaining > 0:                    # 连接没断但数据没读完
            tmp.unlink(missing_ok=True)
            raise ClientGone("上传被中断，未收到完整文件")
        tmp.replace(dest)
        added = self.store.add_paths([dest], source="upload")
        self.store.bump_upload()
        track = added[0] if added else (self.store.find_by_path(dest) or {})
        return {"ok": True, "track": track, "name": dest.name, "size": written}

    # ---------- 启动 ----------
    def start(self) -> None:
        server = self

        class Handler(ApiHandler):
            app = server

        last_err: Exception | None = None
        for _ in range(6):
            try:
                httpd = LocalHTTPServer(("0.0.0.0", self.port), Handler)
            except OSError as e:
                last_err = e
                self.port = pick_port(self.port + 1, self.port + 20)
                self.tunnel.port = self.port
                continue
            self._httpd = httpd
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            return
        raise RuntimeError(f"无法监听端口：{last_err}")

    def stop(self) -> None:
        if self._httpd:
            try:
                self._httpd.shutdown()
            except Exception:
                pass


# --------------------------------------------------------------------------
# 请求处理
# --------------------------------------------------------------------------
class ApiHandler(BaseHTTPRequestHandler):
    app: AppServer
    server_version = "ListeningPlayer/1.0"
    protocol_version = "HTTP/1.1"

    # ---- 输出helpers ----
    def _send(self, code: int, body: bytes, ctype: str = "application/octet-stream",
              extra: dict | None = None, head_only: bool = False) -> None:
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError):
            # 客户端提前断开：连响应头都发不出去，直接关连接，别让 traceback 冒到 socketserver
            self.close_connection = True
            return
        if not head_only:
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True

    def _json(self, obj, code: int = 200, head_only: bool = False) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8", head_only=head_only)

    def _read_json(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0:
                return {}
            return json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except Exception:
            return {}

    def log_message(self, fmt, *args):  # 静音日志
        pass

    # ---- 路由 ----
    def do_HEAD(self):
        self.do_GET(head_only=True)

    def do_GET(self, head_only: bool = False):
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        qs = urllib.parse.parse_qs(parsed.query)
        app = self.app

        if path in ("/", "/index.html"):
            return self._file(static_dir() / "index.html", "text/html; charset=utf-8", head_only)
        if path.startswith("/static/"):
            return self._file(static_dir() / path[len("/static/"):], None, head_only)

        if path == "/favicon.ico":
            return self._file(static_dir() / "app.ico", "image/x-icon", head_only)

        if path.startswith("/u/"):
            token = path[3:].strip("/")
            if token != app.token:
                return self._send(403, "<h3>二维码已失效，请重新扫描电脑屏幕上的二维码</h3>"
                                  .encode("utf-8"), "text/html; charset=utf-8", head_only=head_only)
            return self._file(static_dir() / "upload.html", "text/html; charset=utf-8", head_only)

        if path == "/qr.png":
            size = int((qs.get("size") or ["460"])[0])
            size = max(200, min(1024, size))
            return self._send(200, app.qr_png(app.upload_url(), size), "image/png", head_only=head_only)

        if path == "/qr.svg":
            return self._send(200, app.qr_svg(app.upload_url()),
                              "image/svg+xml; charset=utf-8",
                              {"Cache-Control": "no-store"}, head_only=head_only)

        if path == "/api/info":
            return self._json(app.info(), head_only=head_only)

        if path == "/api/state":
            snap = app.store.snapshot()
            snap["info"] = app.info()
            return self._json(snap, head_only=head_only)

        if path == "/api/poll":
            since = int((qs.get("since") or ["0"])[0])
            snap = app.store.snapshot()
            seq = int(snap.get("upload_seq") or 0)
            new_items = []
            if seq > since:
                new_items = [t for t in snap["tracks"] if t.get("source") == "upload"
                             and float(t.get("added") or 0) >= 0]
                new_items = new_items[-5:]
            return self._json({"seq": seq, "tracks": new_items,
                               "channel": snap.get("channel"),
                               "tunnel_state": app.tunnel_state,
                               "tunnel": app.tunnel.status(),
                               "info": app.info(),
                               "upload_url": app.upload_url()}, head_only=head_only)

        if path == "/api/ping":
            return self._json({"ok": True, "app": APP_NAME, "version": APP_VERSION,
                               "upload_dir": str(app.upload_dir)}, head_only=head_only)

        # 二维码校验：告诉页面「现在这张码里应该编码哪个地址」，
        # 页面拿它和自己手里的图对比，不一致就自动重画。
        if path == "/api/qr":
            return self._json({"ok": True, "url": app.upload_url(),
                               "ts": int(time.time() * 1000),
                               "channel": app.store.data.get("channel", "lan"),
                               "tunnel_state": app.tunnel_state}, head_only=head_only)

        if path.startswith("/media/"):
            return self._media(path[len("/media/"):], head_only)

        return self._send(404, b"Not Found", "text/plain", head_only=head_only)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        qs = urllib.parse.parse_qs(parsed.query)
        app = self.app

        if path == "/api/upload":
            token = (qs.get("t") or [""])[0]
            if token != app.token:
                return self._json({"ok": False, "error": "无效的二维码令牌"}, 403)
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return self._json({"ok": False, "error": "没有收到文件"}, 400)
            if length > MAX_UPLOAD:
                return self._json({"ok": False, "error": "文件超过 800MB"}, 413)
            fname = self.headers.get("X-Filename") or "audio.mp3"
            try:
                result = app.handle_upload(fname, self.rfile, length)
                return self._json(result)
            except ClientGone:
                # 手机已经走了，响应写不回去，静默关连接；半截文件已在 handle_upload 里清掉
                self.close_connection = True
                return
            except ValueError as e:
                self.close_connection = True   # 未读取请求体，直接断开避免脏连接
                return self._json({"ok": False, "error": str(e)}, 400)
            except Exception as e:  # noqa: BLE001
                self.close_connection = True
                return self._json({"ok": False, "error": f"保存失败：{e}"}, 500)

        body = self._read_json()

        if path == "/api/settings":
            for k in ("speed", "volume", "current", "channel"):
                if k in body:
                    app.store.set_setting(k, body[k])
            if body.get("channel") == "tunnel":
                app.tunnel.start()
                app._sync_tunnel()
            elif body.get("channel") == "lan":
                app.tunnel.stop()
                app._sync_tunnel()
            return self._json({"ok": True, "state": app.store.snapshot(), "info": app.info()})

        if path == "/api/tunnel":
            action = body.get("action") or "start"
            if action == "start":
                app.tunnel.start()
            else:
                app.tunnel.stop()
            app._sync_tunnel()
            return self._json({"ok": True, "tunnel": app.tunnel.status(), "info": app.info()})

        if path == "/api/add-folder":
            raw = (body.get("path") or "").strip()
            if not raw:
                return self._json({"ok": False, "error": "目录为空"}, 400)
            folder = Path(raw)
            if not folder.exists():
                return self._json({"ok": False, "error": "目录不存在"}, 400)
            res = app.store.add_folder(folder)
            return self._json({"ok": True, "added": res["added"], "total": res["total"],
                               "state": app.store.snapshot()})

        if path == "/api/remove-folder":
            raw = (body.get("path") or "").strip()
            if not raw:
                return self._json({"ok": False, "error": "目录为空"}, 400)
            removed = app.store.remove_folder(Path(raw))
            return self._json({"ok": True, "removed": removed, "state": app.store.snapshot()})

        if path == "/api/rescan":
            added = app.store.rescan_folders()
            return self._json({"ok": True, "added": added, "state": app.store.snapshot()})

        if path == "/api/add-files":
            paths = [Path(p) for p in (body.get("paths") or [])]
            added = app.store.add_paths([p for p in paths if p.exists()], source="local")
            return self._json({"ok": True, "added": added, "state": app.store.snapshot()})

        if path == "/api/remove":
            app.store.remove_track(str(body.get("id") or ""))
            return self._json({"ok": True, "state": app.store.snapshot()})

        if path == "/api/clear":
            app.store.clear_tracks()
            return self._json({"ok": True, "state": app.store.snapshot()})

        if path == "/api/reveal":
            target = Path(body.get("path") or app.upload_dir)
            self._open_in_explorer(target)
            return self._json({"ok": True})

        return self._json({"ok": False, "error": "未知接口"}, 404)

    # ---- 静态文件 ----
    def _file(self, p: Path, ctype: str | None, head_only: bool = False):
        try:
            if not p.is_file():
                return self._send(404, b"Not Found", "text/plain", head_only=head_only)
            data = p.read_bytes()
        except OSError:
            return self._send(404, b"Not Found", "text/plain", head_only=head_only)
        if ctype is None:
            ext = p.suffix.lower()
            ctype = {".css": "text/css; charset=utf-8", ".js": "application/javascript; charset=utf-8",
                     ".html": "text/html; charset=utf-8", ".svg": "image/svg+xml",
                     ".png": "image/png", ".ico": "image/x-icon"}.get(ext, "application/octet-stream")
        self._send(200, data, ctype, head_only=head_only)

    # ---- 音频流（支持拖动进度） ----
    def _media(self, mid: str, head_only: bool = False):
        track = self.app.store.get_track(mid)
        if not track:
            return self._send(404, b"Not Found", "text/plain", head_only=head_only)
        p = Path(track["path"])
        if not p.is_file():
            return self._send(404, b"Not Found", "text/plain", head_only=head_only)
        size = p.stat().st_size
        ctype = MIME_BY_EXT.get(p.suffix.lower(), "audio/mpeg")
        range_header = self.headers.get("Range")
        start, end = 0, size - 1
        status = 200
        if range_header:
            m = re.match(r"bytes=(\d*)-(\d*)", range_header.strip())
            if m:
                if m.group(1):
                    start = int(m.group(1))
                if m.group(2):
                    end = min(int(m.group(2)), size - 1)
                if start > end or start >= size:
                    try:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.end_headers()
                    except (BrokenPipeError, ConnectionResetError):
                        self.close_connection = True
                    return
                status = 206
        length = end - start + 1
        try:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(length))
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True      # 拖动进度时连续发 Range 请求，旧连接常被主动断开
            return
        if head_only:
            return
        try:
            with open(p, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(262144, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    @staticmethod
    def _open_in_explorer(target: Path) -> None:
        try:
            if target.is_file():
                os.startfile(str(target.parent))  # noqa: S606
            else:
                os.startfile(str(target))  # noqa: S606
        except Exception:
            pass


def main() -> None:
    """独立调试模式：只启动 HTTP 服务（无窗口）。"""
    app = AppServer()
    app.start()
    print("upload url:", app.upload_url())
    print("desktop   :", f"http://127.0.0.1:{app.port}/")
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
