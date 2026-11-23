# 英语听力播放器

> 给英语课堂用的 Windows 听力播放器：老师用手机扫一下二维码就能把音频传到电脑上，电脑端立刻播放这一条；也可以直接挂一个课本听力文件夹，上课时按单元点。

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-lightgrey.svg)](#)

一个单文件 exe，双击即用，不需要在教室电脑上装 Python、也不依赖任何在线服务。界面、上传页、音频流全部由本机 `127.0.0.1` 提供，断网也能放听力。

---

## 为什么做这个

教室电脑上放英语听力，通常的流程是：U 盘拷文件 → 找文件夹 → 双击 → 播放器自己连播下一首 → 老师手忙脚乱按暂停。

这个工具把流程压到最短：

- **手机扫码上传**，不用 U 盘、不用登录、上传页没有任何广告。
- **上传完只播这一条**，播完就停在这一条，不会自己跳下一首。
- **一条一条点着放**，单元听力挂在列表里，随时切换。

## 功能

| 功能 | 说明 |
| --- | --- |
| 扫码上传 | 页面左侧常驻二维码，老师手机扫码即可选音频上传，上传完成电脑端**自动播放这一条** |
| 上传页无广告 | 上传页是本程序自带的页面（`/u/<房间号>`），没有任何第三方广告、统计脚本 |
| 上传通道 | 默认**局域网直连**（手机与电脑同一 Wi-Fi）；可切换**公网中转**（Cloudflare 免费隧道，手机用 4G 也能传） |
| 播放列表 | 单击任意条目即播放；支持搜索、单条移除、清空 |
| 添加听力目录 | 选一个文件夹，递归导入其中所有音频并记住该目录（下次启动自动补新增文件，设置里可移除） |
| 不自动连播 | 启动时不自动播放；一首播完后**停在该首**，按钮变成「重播」 |
| 倍速 | 0.5× / 0.75× / 1.0× / 1.25× / 1.5× / 2.0× 一键切换，退出后记住 |
| 其他 | 拖拽音频文件导入、进度条拖动定位、音量与上次选中的曲目记忆 |

## 快速开始

**用现成的**：到 [Releases](https://github.com/0108-chh/english-listening-player/releases/latest) 下载 `english-listening-player-x.y.z.exe`，双击运行（首次启动约 2～4 秒解包）。

1. 若 Windows 弹出防火墙提示，选择**允许访问**（局域网扫码上传需要它）。
2. 手机连上**同一个 Wi-Fi**，用微信/相机扫左侧二维码 → 上传页 → 选择音频 → 上传。
3. 电脑端自动播放这条音频。

> 二维码旁会显示房间号地址，例如 `http://192.168.0.18:8765/u/50f5a8`，同一 Wi-Fi 下也可以在手机浏览器里手动输入。
> 默认端口 8765，被占用时会自动往后找可用端口，界面和二维码里的地址会跟着变。

### 手机和电脑不在同一个 Wi-Fi（或扫码打不开）

电脑端右上角 **⚙ 设置 → 上传方式 → 公网中转**，点一下即可：

- 程序通过 Cloudflare 免费快速隧道把上传页映射到公网，**不需要注册账号**，上传页仍是本程序自带的干净页面。
- 需要 `cloudflared.exe`（约 55MB）。仓库里没有收录这个二进制文件，程序首次使用时会自动下载到 `%APPDATA%\EnglishListeningPlayer\bin\`；下载失败时手动把它放到 exe 同目录的 `tools\` 文件夹即可。
- 连接成功后二维码自动换成公网地址，手机用 4G 也能扫码上传。
- 公网地址每次启动都会变，以界面上显示的为准。

手动下载地址：<https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe>

## 快捷键

| 按键 | 作用 |
| --- | --- |
| `空格` | 播放 / 暂停 |
| `←` `→` | 快退 / 快进 5 秒 |
| `[` `]` | 降低 / 提高倍速 |
| `Esc` | 关闭设置弹窗 |

## 文件都存放在哪

| 内容 | 位置 |
| --- | --- |
| 老师上传的音频 | `音乐\英语听力\老师上传\`（设置里可一键打开） |
| 播放列表 / 倍速 / 音量等 | `%APPDATA%\EnglishListeningPlayer\state.json` |
| 公网中转组件 | `%APPDATA%\EnglishListeningPlayer\bin\cloudflared.exe` |

清空列表只影响播放列表，**不会删除磁盘上的音频文件**。

## 从源码运行与打包

需要 Python 3.10+（Windows）。WebView2 运行时 Win10/11 已自带，Win7/8 需自行安装。

```bash
pip install -r requirements.txt
python app/main.py          # 开发运行（会开一个 127.0.0.1 的本地服务 + WebView2 窗口）
python build_exe.py         # 打包单文件 exe -> dist/英语听力播放器.exe
```

`test_*.py` 是基于 Playwright 的端到端自测脚本（界面快照、布局检查、上传流程），装在 `test-audio/` 下的示例音频可以直接用：

```bash
pip install playwright && playwright install chromium
python test_final.py
```

## 目录结构

```
app/
  main.py        桌面外壳（WebView2 窗口、文件对话框、JS 桥）
  server.py      内置 HTTP 服务：界面、上传页、音频流、二维码
  store.py       播放列表与设置的持久化
  tunnel.py      Cloudflare 公网中转
  config.py      路径与常量
  static/        单页界面 index.html / style.css / app.js / upload.html
build_exe.py     一键打包脚本
tools/           图标生成、截图辅助脚本
test-audio/      测试用音频
test_*.py        端到端自测脚本
```

## 实现要点

- 界面是单页 HTML/CSS/JS，由本机 `127.0.0.1:8765` 提供，**不引用任何 CDN 或外网资源**，断网可用。
- 音频走带 `Range` 支持的本地流接口，可随意拖动进度，不需要把整首歌读进内存。
- 上传用原始二进制 `POST`（文件名放在 `X-Filename` 头），支持大文件与中文文件名，手机端显示上传百分比；扩展名不在白名单内会被明确拒绝，而不是偷偷改成 `.mp3`。
- 房间号（二维码令牌）随机生成并保存在本机，过期令牌返回 403。
- WebView2 启动参数带 `--autoplay-policy=no-user-gesture-required`，保证「上传后自动播放」不被浏览器策略拦截。
- 端口用独占方式绑定并自增重试，避免 Windows 上 `SO_REUSEADDR` 造成两个进程抢同一端口。

## 已知限制

- 只支持 Windows（依赖 WebView2 + Win32 窗口接口）。
- 公网中转依赖 Cloudflare 的免费快速隧道，地址每次启动都变，学校网络若拦截出境连接则不可用；此时用局域网直连。
- 只做播放，不做听力编辑、不做成绩统计。

## 贡献

欢迎提 Issue / PR。改动前请先开 Issue 说明场景，尤其是涉及上传协议、播放状态机的部分 —— 这三块是最容易改出回归的地方。

## License

[MIT](LICENSE)
