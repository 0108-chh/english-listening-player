#!/usr/bin/env python
"""一键打包为单文件 exe（需要先 pip install -r requirements.txt）。"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / "app"
NAME = "英语听力播放器"


def main() -> None:
    for d in (ROOT / "build", ROOT / "dist"):
        if d.exists():
            shutil.rmtree(d)
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onefile",
        "--windowed",
        "--name", NAME,
        "--icon", str(APP / "static" / "app.ico"),
        "--add-data", f"{APP / 'static'}{';' if sys.platform == 'win32' else ':'}static",
        "--collect-submodules", "webview",
        "--hidden-import", "clr",
        "--hidden-import", "qrcode.image.svg",
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
        str(APP / "main.py"),
    ]
    print(" ".join(cmd))
    subprocess.check_call(cmd, cwd=APP)
    exe = ROOT / "dist" / f"{NAME}.exe"
    print("\n生成成功:", exe, f"{exe.stat().st_size / 1048576:.1f} MB" if exe.exists() else "未找到")


if __name__ == "__main__":
    main()
