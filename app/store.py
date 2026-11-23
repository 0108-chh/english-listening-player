"""播放列表 / 设置 的持久化存储（线程安全）。"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from config import AUDIO_EXTS, default_upload_dir, state_file


def media_id(path: Path) -> str:
    key = os.path.normcase(str(path.resolve() if path.exists() else path))
    return hashlib.sha1(key.encode("utf-8", "ignore")).hexdigest()[:16]


def pretty_title(path: Path) -> str:
    return path.stem.replace("_", " ").strip() or path.name


def list_audio_files(root: Path, recursive: bool = True) -> list[Path]:
    out: list[Path] = []
    if not root.exists():
        return out
    try:
        it = root.rglob("*") if recursive else root.glob("*")
        for p in it:
            try:
                if p.is_file() and p.suffix.lower() in AUDIO_EXTS:
                    # 跳过 Excel/Word 生成的隐藏临时文件
                    if p.name.startswith("~$") or p.name.startswith("."):
                        continue
                    out.append(p)
            except OSError:
                continue
    except OSError:
        pass
    out.sort(key=lambda p: str(p).lower())
    return out


class Store:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.path = state_file()
        self.data: dict[str, Any] = self._load()

    # ---------- 基础读写 ----------
    def _default(self) -> dict[str, Any]:
        return {
            "version": 1,
            "tracks": [],          # [{id, path, title, source, added}]
            "folders": [],         # [{path, added}]
            "current": None,
            "speed": 1.0,
            "volume": 0.85,
            "upload_seq": 0,
            "upload_dir": str(default_upload_dir()),
            "channel": "lan",      # lan | tunnel
        }

    def _load(self) -> dict[str, Any]:
        data = self._default()
        try:
            if self.path.exists():
                raw = json.loads(self.path.read_text("utf-8"))
                if isinstance(raw, dict):
                    data.update({k: v for k, v in raw.items() if k in data})
        except Exception:
            pass
        return data

    def save(self) -> None:
        with self.lock:
            tmp = self.path.with_suffix(".tmp")
            try:
                tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), "utf-8")
                tmp.replace(self.path)
            except Exception:
                pass

    # ---------- 列表操作 ----------
    def _has_path(self, path: Path) -> bool:
        key = os.path.normcase(str(path))
        return any(os.path.normcase(t["path"]) == key for t in self.data["tracks"])

    def add_paths(self, paths: list[Path], source: str = "local") -> list[dict[str, Any]]:
        added: list[dict[str, Any]] = []
        with self.lock:
            for p in paths:
                try:
                    p = p.resolve()
                except OSError:
                    continue
                if p.suffix.lower() not in AUDIO_EXTS or self._has_path(p):
                    continue
                item = {
                    "id": media_id(p),
                    "path": str(p),
                    "title": pretty_title(p),
                    "source": source,
                    "added": time.time(),
                }
                self.data["tracks"].append(item)
                added.append(item)
            if added:
                self.save()
        return added

    def add_folder(self, folder: Path) -> dict[str, Any]:
        folder = folder.resolve()
        with self.lock:
            if not any(os.path.normcase(f["path"]) == os.path.normcase(str(folder))
                       for f in self.data["folders"]):
                self.data["folders"].append({"path": str(folder), "added": time.time()})
            files = list_audio_files(folder)
            added = self.add_paths(files, source="folder")
            self.save()
        return {"added": added, "total": len(files)}

    def remove_folder(self, folder: Path) -> int:
        """移除已登记的听力目录（同时移除该目录导入的曲目，不删除磁盘文件）。"""
        try:
            key = os.path.normcase(str(folder.resolve()))
        except OSError:
            key = os.path.normcase(str(folder))
        with self.lock:
            self.data["folders"] = [
                f for f in self.data["folders"] if os.path.normcase(str(f["path"])) != key
            ]
            removed = 0
            keep = []
            for t in self.data["tracks"]:
                tp = os.path.normcase(t["path"])
                if t.get("source") == "folder" and (tp == key or tp.startswith(key + os.sep)):
                    removed += 1
                    continue
                keep.append(t)
            self.data["tracks"] = keep
            if self.data.get("current") and not any(t["id"] == self.data["current"] for t in keep):
                self.data["current"] = None
            self.save()
            return removed

    def rescan_folders(self) -> list[dict[str, Any]]:
        added: list[dict[str, Any]] = []
        with self.lock:
            for f in list(self.data["folders"]):
                root = Path(f["path"])
                if not root.exists():
                    continue
                added += self.add_paths(list_audio_files(root), source="folder")
        return added

    def remove_track(self, tid: str) -> None:
        with self.lock:
            self.data["tracks"] = [t for t in self.data["tracks"] if t["id"] != tid]
            if self.data.get("current") == tid:
                self.data["current"] = None
            self.save()

    def clear_tracks(self) -> None:
        with self.lock:
            self.data["tracks"] = []
            self.data["current"] = None
            self.save()

    def get_track(self, tid: str | None) -> dict[str, Any] | None:
        if not tid:
            return None
        with self.lock:
            for t in self.data["tracks"]:
                if t["id"] == tid:
                    return dict(t)
        return None

    def find_by_path(self, path: Path) -> dict[str, Any] | None:
        key = os.path.normcase(str(path))
        with self.lock:
            for t in self.data["tracks"]:
                if os.path.normcase(t["path"]) == key:
                    return dict(t)
        return None

    # ---------- 设置 ----------
    def set_setting(self, key: str, value: Any) -> None:
        if key in {"speed", "volume", "current", "upload_dir", "channel"}:
            with self.lock:
                self.data[key] = value
                self.save()

    def bump_upload(self) -> int:
        with self.lock:
            self.data["upload_seq"] = int(self.data.get("upload_seq") or 0) + 1
            self.save()
            return self.data["upload_seq"]

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "tracks": [dict(t) for t in self.data["tracks"]],
                "folders": [dict(f) for f in self.data["folders"]],
                "current": self.data.get("current"),
                "speed": self.data.get("speed", 1.0),
                "volume": self.data.get("volume", 0.85),
                "upload_seq": self.data.get("upload_seq", 0),
                "upload_dir": self.data.get("upload_dir"),
                "channel": self.data.get("channel", "lan"),
            }
