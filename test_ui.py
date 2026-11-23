"""端到端自测：用 Playwright 驱动真实浏览器验证播放器行为。"""
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
    with urllib.request.urlopen(BASE + path, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def upload(name: str, token: str):
    data = (AUDIO_DIR / name).read_bytes()
    req = urllib.request.Request(
        f"{BASE}/api/upload?t={token}",
        data=data,
        headers={"X-Filename": urllib.parse.quote(name), "Content-Type": "application/octet-stream"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    token = api("/api/info")["token"]
    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome",
            headless=True,
            args=["--autoplay-policy=no-user-gesture-required", "--force-device-scale-factor=1"],
        )
        page = browser.new_page(viewport={"width": 1320, "height": 860})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append("console:" + m.text) if m.type == "error" else None)

        page.goto(BASE + "/", wait_until="networkidle")
        page.wait_for_timeout(900)
        print("empty state:", page.locator("#emptyState").is_visible())
        print("QR natural size:", page.evaluate("() => {const i=document.getElementById('qrImg'); return [i.naturalWidth, i.naturalHeight, i.complete]}"))
        page.screenshot(path=str(ROOT / "ui_empty.png"))

        # 1) 手机上传 → 自动播放
        r1 = upload("Unit 1 Listening.wav", token)
        print("upload1:", r1.get("ok"), r1.get("name"))
        page.wait_for_timeout(2600)
        st = page.evaluate("""() => {
            const a = document.getElementById('audio');
            const active = document.querySelector('.track.active');
            return {paused: a.paused, t: a.currentTime.toFixed(2), dur: a.duration,
                    title: active ? active.querySelector('.t-name').textContent : null,
                    icon: document.querySelector('#playIcon use').getAttribute('href')};
        }""")
        print("after upload1:", st)

        # 2) 倍速
        page.click('[data-speed="1.5"]')
        page.wait_for_timeout(300)
        print("speed:", page.evaluate("() => document.getElementById('audio').playbackRate"))

        # 3) 播完不自动下一首
        page.evaluate("""() => { const a = document.getElementById('audio');
            a.currentTime = Math.max(0, a.duration - 0.4); }""")
        page.wait_for_timeout(2500)
        st2 = page.evaluate("""() => {
            const a = document.getElementById('audio');
            return {paused: a.paused, ended: a.ended, t: a.currentTime,
                    active: document.querySelector('.track.active')?.querySelector('.t-name')?.textContent};
        }""")
        print("after ended:", st2)

        # 4) 第二次上传 → 切到新音频并播放
        r2 = upload("Unit 2 Listening.wav", token)
        page.wait_for_timeout(2800)
        st3 = page.evaluate("""() => {
            const a = document.getElementById('audio');
            return {paused: a.paused, title: document.querySelector('.track.active .t-name')?.textContent,
                    count: document.querySelectorAll('.track').length,
                    speeds: document.querySelectorAll('#speedGroup button.on').length,
                    recent: document.querySelectorAll('.recent-item').length};
        }""")
        print("after upload2:", st3)

        page.wait_for_timeout(1200)
        page.screenshot(path=str(ROOT / "ui_content.png"))

        # 5) 设置弹窗
        page.click("#btnSettings")
        page.wait_for_timeout(400)
        page.screenshot(path=str(ROOT / "ui_settings.png"))
        print("modal visible:", page.locator("#modalMask").is_visible())

        print("page errors:", errors[:5])
        browser.close()


if __name__ == "__main__":
    main()
