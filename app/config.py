"""全局路径与常量配置。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "英语听力播放器"
APP_ID = "EnglishListeningPlayer"
APP_VERSION = "1.1.0"


def app_root() -> Path:
    """静态资源所在目录（打包后是 PyInstaller 的解包目录）。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def data_dir() -> Path:
    """可写数据目录：%APPDATA%\\EnglishListeningPlayer"""
    base = os.environ.get("APPDATA") or str(Path.home())
    d = Path(base) / APP_ID
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_upload_dir() -> Path:
    """老师上传的音频默认落盘位置：音乐\\英语听力\\老师上传"""
    music = Path.home() / "Music"
    if not music.exists():
        docs = Path.home() / "Documents"
        music = docs if docs.exists() else data_dir()
    d = music / "英语听力" / "老师上传"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        d = data_dir() / "uploads"
        d.mkdir(parents=True, exist_ok=True)
    return d


def static_dir() -> Path:
    return app_root() / "static"


def state_file() -> Path:
    return data_dir() / "state.json"


AUDIO_EXTS = {
    ".mp3", ".wav", ".m4a", ".flac", ".ogg", ".opus",
    ".aac", ".wma", ".mp4", ".m4b", ".amr", ".webm",
}

MIME_BY_EXT = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".m4b": "audio/mp4",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".aac": "audio/aac",
    ".wma": "audio/x-ms-wma",
    ".mp4": "audio/mp4",
    ".amr": "audio/amr",
    ".webm": "audio/webm",
}
