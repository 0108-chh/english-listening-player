"""桌面外壳：启动内置服务 + WebView2 窗口。"""
from __future__ import annotations

import os
import sys
import threading
import time

import webview

from config import APP_NAME, APP_VERSION, app_root
from server import AppServer

# 允许无用户交互自动播放：上传完成即自动播放刚收到的音频
os.environ.setdefault(
    "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
    "--autoplay-policy=no-user-gesture-required --disable-features=msWebOOUI,msPdfOOUI",
)


def _dialog_type(name: str) -> int:
    """兼容不同 pywebview 版本的文件对话框类型。"""
    try:
        return int(getattr(webview.FileDialog, name.upper()))
    except Exception:
        return int(getattr(webview, f"{name.upper()}_DIALOG"))


class Api:
    """暴露给页面的原生能力（目录选择、资源管理器、中转控制）。"""

    def __init__(self, app: AppServer):
        self.app = app

    def _window(self):
        return webview.windows[0] if webview.windows else None

    def pick_folder(self):
        w = self._window()
        if not w:
            return ""
        try:
            res = w.create_file_dialog(_dialog_type("folder"), directory=str(self.app.upload_dir))
        except Exception:
            return ""
        if not res:
            return ""
        return res[0] if isinstance(res, (list, tuple)) else str(res)

    def pick_files(self):
        w = self._window()
        if not w:
            return []
        try:
            res = w.create_file_dialog(
                _dialog_type("open"),
                allow_multiple=True,
                file_types=("音频文件 (*.mp3;*.wav;*.m4a;*.flac;*.ogg;*.aac;*.wma)",
                            "所有文件 (*.*)"),
            )
        except Exception:
            return []
        return list(res) if res else []

    def reveal(self, path: str = ""):
        target = path or str(self.app.upload_dir)
        try:
            import subprocess
            if os.path.isfile(target):
                subprocess.Popen(["explorer", "/select,", os.path.normpath(target)])
            else:
                os.startfile(target)  # noqa: S606
        except Exception:
            pass
        return True

    def info(self):
        return self.app.info()

    def tunnel(self, action: str = "start"):
        if action == "stop":
            self.app.tunnel.stop()
        else:
            self.app.tunnel.start()
        self.app._sync_tunnel()
        return self.app.tunnel.status()

    def version(self):
        return APP_VERSION


def work_area() -> tuple[int, int]:
    """可用桌面区域（不含任务栏），用于自适应窗口尺寸。"""
    if os.name != "nt":
        return (1440, 900)
    try:
        import ctypes
        from ctypes import wintypes

        class RECT(ctypes.Structure):
            _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                        ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

        rect = RECT()
        if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            if w > 400 and h > 400:
                return (w, h)
    except Exception:
        pass
    return (1440, 900)


def main() -> None:
    app = AppServer()
    app.start()

    def background():
        # 重新扫描已添加的听力目录（不阻塞窗口显示）
        try:
            app.store.rescan_folders()
        except Exception:
            pass
        if app.store.data.get("channel") == "tunnel":
            time.sleep(1.2)
            app.tunnel.start()
            app._sync_tunnel()

    threading.Thread(target=background, daemon=True).start()

    api = Api(app)
    url = f"http://127.0.0.1:{app.port}/"

    sw, sh = work_area()
    win_w = max(1040, min(1360, sw - 60))
    win_h = max(660, min(900, sh - 50))
    window = webview.create_window(
        APP_NAME,
        url,
        js_api=api,
        width=win_w,
        height=win_h,
        min_size=(1024, 640),
        background_color="#eef1f8",
        text_select=False,
        x=max(0, (sw - win_w) // 2),
        y=max(0, (sh - win_h) // 2),
    )

    def on_closed():
        try:
            app.tunnel.shutdown()
        finally:
            app.stop()

    window.events.closed += on_closed

    icon = app_root() / "static" / "app.ico"
    start_kwargs = {}
    if icon.exists():
        start_kwargs["icon"] = str(icon)
    try:
        webview.start(**start_kwargs)
    finally:
        app.tunnel.shutdown()
        app.stop()


if __name__ == "__main__":
    main()
