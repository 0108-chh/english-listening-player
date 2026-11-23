"""把应用窗口提到最前并截图（开发自测用）。"""
import ctypes
import sys
import time
from ctypes import wintypes

from PIL import ImageGrab

TITLE = "英语听力播放器"

u = ctypes.windll.user32
EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def find_window():
    found = []

    def cb(h, _):
        if u.IsWindowVisible(h):
            n = u.GetWindowTextLengthW(h)
            if n:
                b = ctypes.create_unicode_buffer(n + 1)
                u.GetWindowTextW(h, b, n + 1)
                if b.value.strip() == TITLE:
                    found.append(h)
        return True

    u.EnumWindows(EnumProc(cb), 0)
    return found[0] if found else None


h = find_window()
if not h:
    print("window not found")
    sys.exit(1)
u.ShowWindow(h, 9)
time.sleep(0.4)
try:
    u.SetForegroundWindow(h)
    u.BringWindowToTop(h)
except Exception:
    pass
time.sleep(1.2)
out = sys.argv[1] if len(sys.argv) > 1 else "shot.png"
ImageGrab.grab().save(out)
print("saved", out)
