"""细节回归：封面状态、二维码尺寸、提示位置、通道切换。"""
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
ROOT = Path(__file__).resolve().parent
AUDIO_DIR = ROOT / "test-audio"


def api(path):
    with urllib.request.urlopen(BASE + path, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def upload(name, token):
    data = (AUDIO_DIR / name).read_bytes()
    req = urllib.request.Request(
        f"{BASE}/api/upload?t={token}",
        data=data,
        headers={"X-Filename": urllib.parse.quote(name)},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    token = api("/api/info")["token"]
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True,
                                    args=["--autoplay-policy=no-user-gesture-required"])
        page = browser.new_page(viewport={"width": 1320, "height": 860})
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.on("console", lambda m: errs.append("c:" + m.text) if m.type == "error" else None)
        page.goto(BASE + "/", wait_until="networkidle")
        page.wait_for_timeout(800)
        print("qr:", page.evaluate("() => {const i=document.getElementById('qrImg'); return [i.naturalWidth,i.naturalHeight,i.getBoundingClientRect().width]}"))

        upload("Unit 1 Listening.wav", token)
        page.wait_for_timeout(2600)
        print("cover:", page.evaluate("() => document.getElementById('cover').className"))
        print("playing:", page.evaluate("() => !document.getElementById('audio').paused"))
        page.screenshot(path=str(ROOT / "ui_playing.png"))

        # 切到公网中转
        page.click("#btnSettings")
        page.wait_for_timeout(300)
        page.click('.channel-opt[data-channel="tunnel"]')
        for i in range(45):
            page.wait_for_timeout(1000)
            info = api("/api/info")
            st = info["tunnel"]["state"]
            if st in ("on", "error"):
                print("tunnel:", st, info["upload_url"], info["tunnel"].get("message"))
                break
            if i % 5 == 0:
                print("  ...", st, info["tunnel"].get("message"))
        page.wait_for_timeout(1500)
        page.screenshot(path=str(ROOT / "ui_tunnel.png"))
        print("chip:", page.locator("#channelText").inner_text())
        print("url:", page.locator("#urlText").inner_text())
        print("errors:", errs[:6])
        browser.close()


if __name__ == "__main__":
    main()
