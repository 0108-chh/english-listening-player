"""不同窗口尺寸下的布局回归 + 多上传记录。"""
import json
import urllib.parse
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
ROOT = Path(__file__).resolve().parent
AUDIO = ROOT / "test-audio" / "Unit 2 Listening.wav"


def api(p):
    with urllib.request.urlopen(BASE + p, timeout=15) as r:
        return json.loads(r.read().decode())


def upload(name, token):
    req = urllib.request.Request(
        f"{BASE}/api/upload?t={token}", data=AUDIO.read_bytes(),
        headers={"X-Filename": urllib.parse.quote(name)}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def main():
    token = api("/api/info")["token"]
    for i in range(3, 8):
        upload(f"Unit {i}.wav", token)

    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True,
                              args=["--autoplay-policy=no-user-gesture-required"])
        for w, h, tag in [(1360, 862, "lg"), (1280, 720, "md"), (1040, 640, "sm")]:
            pg = b.new_page(viewport={"width": w, "height": h})
            pg.goto(BASE + "/", wait_until="networkidle")
            pg.wait_for_timeout(1200)
            info = pg.evaluate("""() => {
              const q = document.querySelector('.qr-panel');
              const t = document.querySelector('.panel-title');
              const img = document.getElementById('qrImg');
              const foot = document.querySelector('.qr-foot');
              return {scrollH: q.scrollHeight, clientH: q.clientHeight,
                      titleTop: t.getBoundingClientRect().top,
                      panelTop: q.getBoundingClientRect().top,
                      qr: [img.getBoundingClientRect().width, img.getBoundingClientRect().height],
                      footBottom: foot.getBoundingClientRect().bottom,
                      panelBottom: q.getBoundingClientRect().bottom};
            }""")
            print(tag, info)
            pg.screenshot(path=str(ROOT / f"ui_{tag}.png"))
            pg.close()
        b.close()


if __name__ == "__main__":
    main()
