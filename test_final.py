"""最终回归：播放结束图标、重播、上下首、搜索、倍速持久化、通道文案。"""
import json
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
ROOT = Path(__file__).resolve().parent


def api(p):
    with urllib.request.urlopen(BASE + p, timeout=15) as r:
        return json.loads(r.read().decode())


def main():
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True,
                              args=["--autoplay-policy=no-user-gesture-required"])
        pg = b.new_page(viewport={"width": 1360, "height": 862})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(BASE + "/", wait_until="networkidle")
        pg.wait_for_timeout(900)

        print("chip:", pg.locator("#channelText").inner_text(), "| tag:", pg.locator("#channelTag").inner_text())

        # 选中第一首
        pg.locator(".track").first.click()
        pg.wait_for_timeout(1200)
        print("playing:", pg.evaluate("() => !document.getElementById('audio').paused"))

        # 快进到结尾
        pg.evaluate("() => { const a=document.getElementById('audio'); a.currentTime = a.duration - 0.3; }")
        pg.wait_for_timeout(2200)
        print("ended icon:", pg.evaluate("() => document.querySelector('#playIcon use').getAttribute('href')"),
              "| active unchanged:", pg.evaluate("() => document.querySelector('.track.active .t-name').textContent"))
        pg.screenshot(path=str(ROOT / "ui_ended.png"))

        # 再点播放 → 从头开始
        pg.click("#btnPlay")
        pg.wait_for_timeout(700)
        print("restart:", pg.evaluate("() => { const a=document.getElementById('audio'); return [a.paused, a.currentTime.toFixed(1)]; }"))

        # 下一首 / 上一首
        pg.click("#btnNext")
        pg.wait_for_timeout(600)
        print("next ->", pg.evaluate("() => document.querySelector('.track.active .t-name').textContent"))
        pg.click("#btnPrev")
        pg.wait_for_timeout(600)
        print("prev ->", pg.evaluate("() => document.querySelector('.track.active .t-name').textContent"))

        # 搜索
        pg.fill("#searchInput", "Unit 5")
        pg.wait_for_timeout(300)
        print("filtered rows:", pg.locator(".track").count())
        pg.fill("#searchInput", "")
        pg.wait_for_timeout(300)

        # 倍速持久化
        pg.click('[data-speed="1.25"]')
        pg.wait_for_timeout(800)
        pg.reload(wait_until="networkidle")
        pg.wait_for_timeout(1000)
        print("speed after reload:", pg.evaluate("() => document.getElementById('audio').playbackRate"),
              "| autoplay on load:", pg.evaluate("() => !document.getElementById('audio').paused"))

        # 上传页（手机端）
        token = api("/api/info")["token"]
        mob = b.new_page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        mob.goto(f"{BASE}/u/{token}", wait_until="domcontentloaded", timeout=20000)
        mob.wait_for_timeout(700)
        mob.screenshot(path=str(ROOT / "ui_mobile.png"))
        print("mobile status:", mob.locator("#statusText").inner_text())
        print("errors:", errs[:4])
        b.close()


if __name__ == "__main__":
    main()
