/* 英语听力播放器 —— 单页逻辑 */
(() => {
  const $ = (s) => document.querySelector(s);
  const audio = $('#audio');

  const state = {
    tracks: [],
    folders: [],
    current: null,
    speed: 1,
    volume: 0.85,
    seq: 0,
    info: null,
    filter: '',
  };

  const durCache = new Map();
  let ended = false;
  let isDragging = false;
  let lastInfoKey = '';
  let saveTimer = null;
  let metaBusy = false;
  const metaQueue = [];

  /* ------------------ 工具 ------------------ */
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  function fmt(sec) {
    if (!isFinite(sec) || sec < 0) sec = 0;
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }

  function toast(msg, kind = '', icon = '') {
    const el = document.createElement('div');
    el.className = `toast ${kind}`;
    el.innerHTML = `${icon ? `<svg><use href="#${icon}"/></svg>` : ''}<span>${esc(msg)}</span>`;
    $('#toasts').appendChild(el);
    setTimeout(() => {
      el.style.transition = 'opacity .25s, transform .25s';
      el.style.opacity = '0';
      el.style.transform = 'translateY(-6px)';
      setTimeout(() => el.remove(), 260);
    }, 2600);
  }

  async function getJSON(url) {
    const r = await fetch(url, { cache: 'no-store' });
    return r.json();
  }

  async function post(url, body) {
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
    return r.json();
  }

  /* 设置写盘：把短时间内的多次改动合并成一次请求。
     注意要「合并」而不是「覆盖」——否则拖倍速后马上调音量，
     后一次调用会把还没发出去的 speed 取消掉，重启后倍速就丢了。 */
  let pendingPatch = {};

  function flushSettings() {
    if (!Object.keys(pendingPatch).length) return;
    const body = JSON.stringify(pendingPatch);
    pendingPatch = {};
    try {
      navigator.sendBeacon('/api/settings', new Blob([body], { type: 'application/json' }));
    } catch (e) { /* 退出阶段失败就算了，下次改动还会写 */ }
  }

  function saveSettings(patch, delay = 0) {
    Object.assign(pendingPatch, patch);
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      const body = pendingPatch;
      pendingPatch = {};
      post('/api/settings', body).catch(() => {});
    }, delay);
  }

  // 关窗前把还没写盘的设置补发一次（sendBeacon 在页面卸载时也能发出去）
  window.addEventListener('beforeunload', flushSettings);

  const parentName = (p) => {
    const parts = String(p || '').split(/[\\/]/).filter(Boolean);
    return parts.length > 1 ? parts[parts.length - 2] : '';
  };

  const SRC_LABEL = { upload: '上传', folder: '目录', local: '本地' };

  /* ------------------ 倍速（无极调节） ------------------ */
  const SPEED_MIN = 0.5;
  const SPEED_MAX = 3;
  const SPEED_STEP = 0.05;

  /* 吸附到 0.05 网格并夹在 [0.5, 3] 内，保证数值干净、不会出现 1.0500000001 */
  function snapSpeed(v) {
    let n = Math.round((Number(v) - SPEED_MIN) / SPEED_STEP);
    const max = Math.round((SPEED_MAX - SPEED_MIN) / SPEED_STEP);
    if (!isFinite(n)) n = Math.round((1 - SPEED_MIN) / SPEED_STEP);
    n = Math.max(0, Math.min(max, n));
    return +(SPEED_MIN + n * SPEED_STEP).toFixed(2);
  }

  /* 1.0× / 1.25× / 0.75×：最多两位小数，至少保留一位 */
  function fmtSpeed(v) {
    return (Math.round(v * 100) / 100).toFixed(2).replace(/0$/, '') + '×';
  }

  const speedRatio = (v) => (v - SPEED_MIN) / (SPEED_MAX - SPEED_MIN);

  /* 只负责把当前倍速画到滑杆和读数上 */
  function paintSpeed(v) {
    const range = $('#speedRange');
    if (range) {
      range.style.setProperty('--p', (speedRatio(v) * 100).toFixed(2) + '%');
      if (Math.abs(parseFloat(range.value) - v) > 1e-6) range.value = String(v);
    }
    const badge = $('#speedBadge');
    if (badge) {
      badge.textContent = fmtSpeed(v);
      badge.classList.toggle('tuned', Math.abs(v - 1) > 1e-6);
    }
  }

  function setSpeed(v, persist = true) {
    const val = snapSpeed(v);
    state.speed = val;
    audio.playbackRate = val;
    paintSpeed(val);
    if (persist) saveSettings({ speed: val }, 250);
  }

  /* 一键回到正常速度（双击滑杆 / 点读数） */
  function resetSpeed() {
    if (Math.abs(state.speed - 1) < 1e-6) return;
    setSpeed(1);
    saveSettings({ speed: 1 }, 0);
    toast('倍速已恢复 1.0×');
  }

  /* ------------------ 渲染 ------------------ */
  function visibleTracks() {
    const q = state.filter.trim().toLowerCase();
    if (!q) return state.tracks;
    return state.tracks.filter((t) =>
      t.title.toLowerCase().includes(q) ||
      parentName(t.path).toLowerCase().includes(q));
  }

  function renderTracks() {
    const list = visibleTracks();
    const box = $('#tracks');
    const empty = $('#emptyState');

    $('#trackCount').textContent = `${state.tracks.length} 首`;

    if (!state.tracks.length) {
      box.innerHTML = '';
      empty.hidden = false;
      return;
    }
    empty.hidden = true;

    if (!list.length) {
      box.innerHTML = `<div class="no-result">没有匹配「${esc(state.filter)}」的音频</div>`;
      return;
    }

    const playing = !audio.paused && !audio.ended;
    box.innerHTML = list.map((t, i) => {
      const active = t.id === state.current;
      const d = durCache.get(t.id);
      const sub = parentName(t.path);
      return `<div class="track${active ? ' active' : ''}" data-id="${t.id}">
        <div class="t-idx">${active
          ? `<div class="eq${playing ? '' : ' paused'}"><i></i><i></i><i></i></div>`
          : (i + 1)}</div>
        <div class="t-main">
          <div class="t-name" title="${esc(t.title)}">${esc(t.title)}</div>
          <div class="t-sub">
            <span class="t-src ${t.source}">${SRC_LABEL[t.source] || '本地'}</span>
            ${sub ? `<span class="t-folder" title="${esc(sub)}">${esc(sub)}</span>` : ''}
          </div>
        </div>
        <div class="t-dur" data-dur="${t.id}">${d ? fmt(d) : '--:--'}</div>
        <button class="t-del" data-del="${t.id}" title="从列表移除">
          <svg><use href="#i-trash"/></svg>
        </button>
      </div>`;
    }).join('');

    list.forEach(queueMeta);
  }

  function renderNow() {
    const t = state.tracks.find((x) => x.id === state.current);
    const playing = !audio.paused && !audio.ended;
    $('#npTitle').textContent = t ? t.title : '未选择音频';
    $('#npSub').textContent = t
      ? `${SRC_LABEL[t.source] || '本地'}${parentName(t.path) ? ' · ' + parentName(t.path) : ''}`
      : '从上方列表选择一首听力开始';
    $('#cover').classList.toggle('playing', playing && !!t);
    const icon = ended ? 'i-replay' : (playing ? 'i-pause' : 'i-play');
    $('#playIcon').innerHTML = `<use href="#${icon}"/>`;
    $('#btnPlay').classList.toggle('playing', playing);
    $('#tTotal').textContent = fmt(audio.duration || durCache.get(state.current) || 0);
    $('#tNow').textContent = fmt(audio.currentTime || 0);
    if (!isDragging) setBar(audio.duration ? audio.currentTime / audio.duration : 0);
  }

  function renderRecent() {
    const ups = state.tracks.filter((t) => t.source === 'upload').slice(-4).reverse();
    const box = $('#recentList');
    $('#recentCount').textContent = ups.length ? `${ups.length}` : '';
    if (!ups.length) {
      box.innerHTML = '<div class="recent-empty">暂无上传记录</div>';
      return;
    }
    box.innerHTML = ups.map((t) => {
      const d = new Date((t.added || 0) * 1000);
      const hh = String(d.getHours()).padStart(2, '0');
      const mm = String(d.getMinutes()).padStart(2, '0');
      return `<div class="recent-item" data-id="${t.id}" title="${esc(t.title)}">
        <span class="r-ico"><svg><use href="#i-check"/></svg></span>
        <span class="r-name">${esc(t.title)}</span>
        <span class="r-time">${hh}:${mm}</span>
      </div>`;
    }).join('');
  }

  function renderInfo() {
    const info = state.info;
    if (!info) return;
    const key = JSON.stringify([info.upload_url, info.channel, info.tunnel.state]);
    if (key === lastInfoKey) return;
    lastInfoKey = key;

    $('#urlText').textContent = info.upload_url;
    $('#urlText').title = info.upload_url;

    const tag = $('#channelTag');
    const chip = $('#channelChip');
    const chipText = $('#channelText');
    chip.classList.remove('busy', 'off');

    const tunnelOn = info.channel === 'tunnel' && info.tunnel.state === 'on';
    if (info.channel === 'tunnel') {
      if (tunnelOn) {
        chipText.textContent = '公网中转已连接';
      } else if (info.tunnel.state === 'error') {
        chipText.textContent = '中转异常 · 已回退局域网';
        chip.classList.add('off');
      } else if (info.tunnel.state === 'off') {
        chipText.textContent = `局域网直连 · ${info.lan_ip}`;
        chip.classList.add('off');
      } else {
        chipText.textContent = '正在连接中转…';
        chip.classList.add('busy');
      }
    } else {
      chipText.textContent = `局域网直连 · ${info.lan_ip}`;
    }

    // 标签始终反映「当前二维码实际指向的通道」
    if (tunnelOn) {
      tag.textContent = '公网';
      tag.classList.add('green');
    } else {
      tag.textContent = '局域网';
      tag.classList.remove('green');
    }

    // 二维码跟着当前上传地址走：地址变了（换通道 / 中转重连 / 端口变化）就重画
    checkQr();
    renderTunnelState();
  }

  /* ------------------ 二维码：自动刷新 ------------------ */
  const QR_TTL = 5 * 60 * 1000;   // 兜底：最长 5 分钟重新取一次图
  const QR_CHECK_MS = 8000;       // 每 8 秒核对一次「图里的地址 == 服务端当前地址」

  const qrState = { url: '', at: 0, loading: false, tries: 0 };
  let qrNoteTimer = null;
  let qrCheckTimer = null;

  /* 把「更新于 HH:MM:SS」写在二维码下方 */
  function stampQr(fresh) {
    const el = $('#qrStamp');
    if (!el || !qrState.at) return;
    const d = new Date(qrState.at);
    const hh = String(d.getHours()).padStart(2, '0');
    const mm = String(d.getMinutes()).padStart(2, '0');
    const ss = String(d.getSeconds()).padStart(2, '0');
    el.textContent = `更新于 ${hh}:${mm}:${ss}`;
    el.classList.remove('fresh');
    if (fresh) {
      // 触发一次重排，保证连续两次刷新也能重新闪一下
      void el.offsetWidth;
      el.classList.add('fresh');
      setTimeout(() => el.classList.remove('fresh'), 2800);
    }
  }

  /* 二维码变化时在提示行里说一句，几秒后恢复成「等待老师扫码」 */
  function qrNote(text) {
    const txt = $('#qrHintText');
    const hint = $('#qrHint');
    if (!txt || !hint) return;
    clearTimeout(qrNoteTimer);
    txt.textContent = text;
    txt.classList.add('warn');
    hint.classList.add('note');
    qrNoteTimer = setTimeout(() => {
      txt.textContent = '等待老师扫码';
      txt.classList.remove('warn');
      hint.classList.remove('note');
    }, 6000);
  }

  /**
   * 重新生成二维码。
   * opts.quiet：静默重取（定时兜底），不闪透明度、不提示
   * opts.fresh：地址变了导致的更新，闪一下绿色「更新于」
   */
  function loadQr(opts = {}) {
    const img = $('#qrImg');
    const url = state.info?.upload_url || '';
    if (!url || qrState.loading) return;
    qrState.loading = true;
    qrState.url = url;
    qrState.at = Date.now();
    if (!opts.quiet) img.style.opacity = '0.3';
    img.onload = () => {
      qrState.loading = false;
      qrState.tries = 0;
      img.style.opacity = '1';
      stampQr(!!opts.fresh);
    };
    img.onerror = () => {
      qrState.loading = false;
      if (qrState.tries++ < 3) setTimeout(() => loadQr(opts), 1500);
      else img.style.opacity = '1';
    };
    img.src = `/qr.svg?v=${qrState.at}`;
  }

  /* 二维码自检：地址过期 / 长时间没动 / 服务端换地址，都会自动重画。
     注意不能因为「窗口被遮住/最小化」就跳过——投影时窗口正好处于隐藏状态，
     而这恰恰是最需要二维码保持最新的时候。 */
  async function checkQr() {
    const cur = state.info?.upload_url || '';
    if (!cur) return;                              // 还在启动，等下一轮
    if (!qrState.url) {                            // 首次加载，不需要提示
      loadQr();
      return;
    }
    if (cur !== qrState.url) {
      loadQr({ fresh: true });
      qrNote('二维码已自动更新，请重新扫码');
      return;
    }
    if (Date.now() - qrState.at > QR_TTL) {         // 兜底重取，防止拿到旧图
      loadQr({ quiet: true });
      return;
    }
    try {
      const d = await getJSON('/api/qr');           // 以服务端为准再核对一次
      if (d && d.ok && d.url && d.url !== qrState.url) {
        loadQr({ fresh: true });
        qrNote('二维码已自动更新，请重新扫码');
      }
    } catch (e) { /* 服务正在重启，下一轮再说 */ }
  }

  function startQrWatch() {
    clearInterval(qrCheckTimer);
    qrCheckTimer = setInterval(checkQr, QR_CHECK_MS);
    // 切回窗口立刻核一次：老师上课前把窗口调出来时，看到的必须是最新的码
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) checkQr();
    });
  }

  function renderFolders() {
    const box = $('#folderList');
    if (!box) return;
    const list = state.folders || [];
    if (!list.length) {
      box.innerHTML = '<div class="folder-empty">还没有添加听力目录</div>';
      return;
    }
    box.innerHTML = list.map((f) => {
      const prefix = f.path.toLowerCase();
      const count = state.tracks.filter((t) =>
        t.source === 'folder' && t.path.toLowerCase().startsWith(prefix)).length;
      return `<div class="folder-row">
        <span class="f-path" data-reveal="${esc(f.path)}" title="${esc(f.path)}">${esc(f.path)}</span>
        <span class="f-count">${count} 首</span>
        <button class="f-del" data-del-folder="${esc(f.path)}" title="移除该目录">移除</button>
      </div>`;
    }).join('');
  }

  function renderTunnelState() {
    const info = state.info;
    if (!info) return;
    document.querySelectorAll('.channel-opt').forEach((b) => {
      b.classList.toggle('active', b.dataset.channel === info.channel);
    });
    const lan = $('#lanState');
    lan.textContent = '已就绪';
    lan.className = 'co-state on';

    const tn = $('#tunnelState');
    const st = info.tunnel.state;
    tn.className = 'co-state' + (st === 'on' ? ' on' : st === 'error' ? ' err' : '');
    tn.textContent = st === 'on' ? '已连接'
      : st === 'downloading' ? '下载组件…'
      : st === 'starting' ? '连接中…'
      : st === 'error' ? '连接失败' : '未启用';

    const hint = $('#tunnelHint');
    if (st === 'error') {
      hint.textContent = info.tunnel.message || '连接失败，可切回局域网模式，或检查网络后重试。';
    } else if (st === 'downloading' || st === 'starting') {
      hint.textContent = info.tunnel.message || '正在建立中转连接…';
    } else if (st === 'on') {
      hint.innerHTML = `公网地址：<span class="hint-url">${esc(info.tunnel.url || '')}</span><br>上传页面由本程序内置，无任何广告。手机用 4G 也能扫码上传。`;
    } else {
      hint.textContent = '公网中转使用 Cloudflare 免费快速隧道，仅首次需要下载约 50MB 组件。';
    }
    $('#uploadDir').textContent = info.upload_dir || '—';
    $('#verText').textContent = 'v' + (info.version || '1.0.0');
    renderFolders();
  }

  /* ------------------ 时长探测 ------------------ */
  function queueMeta(t) {
    if (durCache.has(t.id) || metaQueue.some((x) => x.id === t.id)) return;
    metaQueue.push(t);
    pumpMeta();
  }

  function pumpMeta() {
    if (metaBusy) return;
    const t = metaQueue.shift();
    if (!t) return;
    metaBusy = true;
    const probe = new Audio();
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      metaBusy = false;
      probe.removeAttribute('src');
      pumpMeta();
    };
    probe.preload = 'metadata';
    probe.onloadedmetadata = () => {
      durCache.set(t.id, probe.duration || 0);
      const el = document.querySelector(`[data-dur="${t.id}"]`);
      if (el) el.textContent = fmt(probe.duration || 0);
      if (t.id === state.current) $('#tTotal').textContent = fmt(probe.duration || 0);
      finish();
    };
    probe.onerror = finish;
    probe.src = `/media/${t.id}`;
    setTimeout(finish, 9000);
  }

  /* ------------------ 播放控制 ------------------ */
  function setBar(ratio) {
    const pct = Math.max(0, Math.min(1, ratio || 0)) * 100;
    $('#barFill').style.width = pct + '%';
    $('#barKnob').style.left = pct + '%';
  }

  async function play() {
    if (!state.current) {
      if (state.tracks.length) return selectTrack(state.tracks[0].id, true);
      toast('请先添加音频或扫码上传');
      return;
    }
    if (ended) { audio.currentTime = 0; ended = false; }
    try {
      await audio.play();
    } catch (e) {
      toast('无法自动播放，请点击播放按钮', 'err');
    }
  }

  function pause() { audio.pause(); }

  function toggle() {
    if (audio.paused) play(); else pause();
  }

  function selectTrack(id, autoplay = true) {
    const t = state.tracks.find((x) => x.id === id);
    if (!t) return;
    if (state.current !== id) {
      state.current = id;
      ended = false;
      audio.src = `/media/${id}`;
      audio.playbackRate = state.speed;
      audio.volume = state.volume;
      saveSettings({ current: id }, 300);
      $('#barFill').style.width = '0%';
      $('#barKnob').style.left = '0%';
      $('#tNow').textContent = '00:00';
      $('#tTotal').textContent = fmt(durCache.get(id) || 0);
    }
    renderTracks();
    renderNow();
    if (autoplay) play();
    scrollToActive();
  }

  function scrollToActive() {
    const el = document.querySelector('.track.active');
    if (el) el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }

  function step(dir) {
    const list = visibleTracks();
    if (!list.length) return;
    const idx = list.findIndex((t) => t.id === state.current);
    let next = idx + dir;
    if (idx < 0) next = 0;
    if (next < 0) next = 0;
    if (next >= list.length) next = list.length - 1;
    if (list[next] && list[next].id !== state.current) selectTrack(list[next].id, true);
    else if (list[next]) selectTrack(list[next].id, true);
  }

  function setVolume(v, persist = true) {
    state.volume = v;
    audio.volume = v;
    audio.muted = v === 0;
    $('#volRange').value = Math.round(v * 100);
    $('#volRange').style.setProperty('--p', (v * 100).toFixed(0) + '%');
    $('#btnMute').innerHTML = `<svg><use href="#${v === 0 ? 'i-mute' : 'i-vol'}"/></svg>`;
    if (persist) saveSettings({ volume: v }, 400);
  }

  /* ------------------ 数据同步 ------------------ */
  async function refresh(keepSeq = true) {
    const d = await getJSON('/api/state');
    state.tracks = d.tracks || [];
    state.folders = d.folders || [];
    state.current = d.current || null;
    if (!keepSeq) state.seq = d.upload_seq || 0;
    state.info = d.info || state.info;
    if (audio.readyState === 0 && state.current) {
      audio.src = `/media/${state.current}`;
      audio.playbackRate = state.speed;
      audio.volume = state.volume;
    }
    renderTracks();
    renderRecent();
    renderFolders();
    renderInfo();
    renderNow();
    return d;
  }

  async function poll(force = false) {
    try {
      const d = await getJSON(`/api/poll?since=${state.seq}`);
      if (d.info) state.info = d.info;
      if (d.seq > state.seq) {
        state.seq = d.seq;
        await refresh();
        const latest = (d.tracks || [])[(d.tracks || []).length - 1];
        if (latest) {
          selectTrack(latest.id, true);
          toast(`收到上传：${latest.title}`, 'ok', 'i-upload');
        }
      } else {
        renderInfo();
      }
    } catch (e) { /* 服务重启中，忽略 */ }
    if (force) renderTracks();
  }

  /* ------------------ 添加音频 ------------------ */
  async function addFolder() {
    if (!window.pywebview?.api?.pick_folder) {
      toast('请在桌面应用中使用此功能', 'err');
      return;
    }
    const dir = await window.pywebview.api.pick_folder();
    if (!dir) return;
    const r = await post('/api/add-folder', { path: dir });
    if (!r.ok) return toast(r.error || '添加失败', 'err');
    await refresh();
    const n = (r.added || []).length;
    if (n) toast(`已添加 ${n} 个音频`, 'ok', 'i-check');
    else toast('该目录下没有新音频（可能已在列表中）', '');
    if (r.added && r.added.length && !audio.src) selectTrack(r.added[0].id, false);
  }

  async function addFiles() {
    if (!window.pywebview?.api?.pick_files) {
      toast('请在桌面应用中使用此功能', 'err');
      return;
    }
    const files = await window.pywebview.api.pick_files();
    if (!files || !files.length) return;
    const r = await post('/api/add-files', { paths: files });
    await refresh();
    const n = (r.added || []).length;
    if (n) toast(`已添加 ${n} 个音频`, 'ok', 'i-check');
    else toast('这些音频已在列表中', '');
  }

  async function removeTrack(id) {
    const wasCurrent = state.current === id;
    if (wasCurrent) { audio.pause(); audio.removeAttribute('src'); audio.load(); }
    await post('/api/remove', { id });
    if (wasCurrent) {
      state.current = null;
      ended = false;
      $('#barFill').style.width = '0%';
      $('#barKnob').style.left = '0%';
      $('#tNow').textContent = '00:00';
      $('#tTotal').textContent = '00:00';
    }
    await refresh();
    renderNow();
  }

  async function clearAll() {
    if (!state.tracks.length) return;
    if (!confirm(`确定清空播放列表中的 ${state.tracks.length} 首音频吗？\n（不会删除磁盘上的文件）`)) return;
    audio.pause();
    audio.removeAttribute('src');
    state.current = null;
    await post('/api/clear');
    await refresh();
    renderNow();
  }

  /* 拖拽上传：直接走手机同一条上传通道 */
  function uploadDropped(file) {
    return new Promise((resolve) => {
      const token = state.info?.token || '';
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `/api/upload?t=${encodeURIComponent(token)}`);
      xhr.setRequestHeader('X-Filename', encodeURIComponent(file.name));
      xhr.onload = () => {
        try { resolve(JSON.parse(xhr.responseText)); } catch { resolve({ ok: false }); }
      };
      xhr.onerror = () => resolve({ ok: false });
      xhr.send(file);
    });
  }

  async function handleDrop(files) {
    const audios = Array.from(files).filter((f) =>
      /\.(mp3|wav|m4a|flac|ogg|opus|aac|wma)$/i.test(f.name) ||
      (f.type || '').startsWith('audio/'));
    if (!audios.length) return toast('请拖入音频文件', 'err');
    toast(`正在导入 ${audios.length} 个音频…`);
    let ok = 0;
    for (const f of audios) {
      const r = await uploadDropped(f);
      if (r.ok) ok++;
    }
    await poll(true);
    if (ok) toast(`已导入 ${ok} 个音频`, 'ok', 'i-check');
    else toast('导入失败', 'err');
  }

  /* ------------------ 事件绑定 ------------------ */
  audio.addEventListener('play', () => { ended = false; renderNow(); renderTracks(); });
  audio.addEventListener('pause', () => { renderNow(); renderTracks(); });
  audio.addEventListener('ended', () => {
    ended = true;
    // 需求：一首播完不自动播下一首
    renderNow();
    renderTracks();
    toast('播放结束');
  });
  audio.addEventListener('loadedmetadata', () => {
    if (state.current && audio.duration) durCache.set(state.current, audio.duration);
    audio.playbackRate = state.speed;      // 换源后确保倍速仍然是上次记住的值
    $('#tTotal').textContent = fmt(audio.duration || 0);
    renderNow();
  });
  audio.addEventListener('timeupdate', () => {
    if (isDragging) return;
    $('#tNow').textContent = fmt(audio.currentTime);
    setBar(audio.duration ? audio.currentTime / audio.duration : 0);
  });
  audio.addEventListener('error', () => {
    if (state.current) toast('音频无法播放，可能文件已移动', 'err');
  });

  $('#btnPlay').addEventListener('click', toggle);
  $('#btnPrev').addEventListener('click', () => step(-1));
  $('#btnNext').addEventListener('click', () => step(1));

  $('#tracks').addEventListener('click', (e) => {
    const del = e.target.closest('.t-del');
    if (del) { e.stopPropagation(); removeTrack(del.dataset.del); return; }
    const row = e.target.closest('.track');
    if (row) selectTrack(row.dataset.id, true);
  });

  $('#recentList').addEventListener('click', (e) => {
    const row = e.target.closest('.recent-item');
    if (row) selectTrack(row.dataset.id, true);
  });

  $('#searchInput').addEventListener('input', (e) => {
    state.filter = e.target.value;
    renderTracks();
  });

  // 倍速：拖动即时生效，松手后立刻落盘；双击滑杆 / 点读数回到 1.0×
  const speedRange = $('#speedRange');
  speedRange.addEventListener('input', (e) => setSpeed(parseFloat(e.target.value)));
  speedRange.addEventListener('change', () => saveSettings({ speed: state.speed }, 0));
  speedRange.addEventListener('dblclick', resetSpeed);
  $('#speedBadge').addEventListener('click', resetSpeed);

  $('#volRange').addEventListener('input', (e) => setVolume(parseInt(e.target.value, 10) / 100));
  $('#btnMute').addEventListener('click', () => {
    if (state.volume > 0) { setVolume(0); } else { setVolume(0.85); }
  });

  // 进度条拖动
  const bar = $('#bar');
  const ratioOf = (ev) => {
    const r = bar.getBoundingClientRect();
    return Math.max(0, Math.min(1, (ev.clientX - r.left) / r.width));
  };
  bar.addEventListener('pointerdown', (ev) => {
    if (!state.current || !audio.duration) return;
    isDragging = true;
    bar.classList.add('dragging');
    bar.setPointerCapture(ev.pointerId);
    const r = ratioOf(ev);
    setBar(r);
    $('#tNow').textContent = fmt(r * audio.duration);
  });
  bar.addEventListener('pointermove', (ev) => {
    if (!isDragging) return;
    const r = ratioOf(ev);
    setBar(r);
    $('#tNow').textContent = fmt(r * (audio.duration || 0));
  });
  bar.addEventListener('pointerup', (ev) => {
    if (!isDragging) return;
    isDragging = false;
    bar.classList.remove('dragging');
    const r = ratioOf(ev);
    if (audio.duration) audio.currentTime = r * audio.duration;
    $('#tNow').textContent = fmt(audio.currentTime);
  });

  // 添加 / 清空
  const bindAdd = (id, fn) => { const el = $(id); if (el) el.addEventListener('click', fn); };
  bindAdd('#btnAddFolder', addFolder);
  bindAdd('#btnAddFiles', addFiles);
  bindAdd('#emptyAddFolder', addFolder);
  bindAdd('#emptyAddFiles', addFiles);
  $('#btnClear').addEventListener('click', clearAll);

  $('#btnCopy').addEventListener('click', async () => {
    const url = state.info?.upload_url || '';
    if (!url) return;
    try {
      await navigator.clipboard.writeText(url);
    } catch {
      const ta = document.createElement('textarea');
      ta.value = url; document.body.appendChild(ta); ta.select();
      document.execCommand('copy'); ta.remove();
    }
    toast('上传地址已复制', 'ok', 'i-check');
  });

  $('#btnReveal').addEventListener('click', () => {
    if (window.pywebview?.api?.reveal) window.pywebview.api.reveal('');
  });
  $('#btnRefreshQr').addEventListener('click', () => {
    lastInfoKey = '';
    renderInfo();
    loadQr({ fresh: true });
    qrNote('二维码已刷新');
  });

  // 设置弹窗
  const modal = $('#modalMask');
  const openModal = () => { modal.hidden = false; lastInfoKey = ''; renderInfo(); };
  const closeModal = () => { modal.hidden = true; };
  $('#btnSettings').addEventListener('click', openModal);
  $('#btnCloseModal').addEventListener('click', closeModal);
  $('#btnDone').addEventListener('click', closeModal);
  modal.addEventListener('click', (e) => { if (e.target === modal) closeModal(); });
  $('#btnOpenDir').addEventListener('click', () => {
    if (window.pywebview?.api?.reveal) window.pywebview.api.reveal('');
  });

  $('#folderList').addEventListener('click', async (e) => {
    const del = e.target.closest('[data-del-folder]');
    if (del) {
      const p = del.dataset.delFolder;
      if (!confirm(`移除该听力目录？\n${p}\n\n（只从播放列表移除，不会删除磁盘上的文件）`)) return;
      const r = await post('/api/remove-folder', { path: p });
      await refresh();
      if (r.ok) toast(`已移除目录（${r.removed} 首）`, 'ok', 'i-check');
      return;
    }
    const rev = e.target.closest('[data-reveal]');
    if (rev && window.pywebview?.api?.reveal) window.pywebview.api.reveal(rev.dataset.reveal);
  });

  document.querySelectorAll('.channel-opt').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const ch = btn.dataset.channel;
      if (state.info?.channel === ch && !(ch === 'tunnel' && state.info?.tunnel.state === 'error')) return;
      const r = await post('/api/settings', { channel: ch });
      if (r.info) state.info = r.info;
      lastInfoKey = '';
      renderInfo();
      if (ch === 'tunnel') toast('正在建立公网中转…');
    });
  });

  // 键盘
  document.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
      if (e.key === 'Escape') e.target.blur();
      return;
    }
    if (e.key === 'Escape' && !modal.hidden) { closeModal(); return; }
    if (e.code === 'Space') { e.preventDefault(); toggle(); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); audio.currentTime = Math.max(0, audio.currentTime - 5); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); audio.currentTime = Math.min(audio.duration || 0, audio.currentTime + 5); }
    else if (e.key === '[') { e.preventDefault(); stepSpeed(e.shiftKey ? -0.25 : -0.05); }
    else if (e.key === ']') { e.preventDefault(); stepSpeed(e.shiftKey ? 0.25 : 0.05); }
  });

  function stepSpeed(delta) {
    setSpeed(snapSpeed(state.speed + delta));
    saveSettings({ speed: state.speed }, 150);
    toast(`倍速 ${fmtSpeed(state.speed)}`);
  }

  // 拖拽导入
  const body = document.querySelector('.list-body');
  ['dragenter', 'dragover'].forEach((ev) => body.addEventListener(ev, (e) => {
    e.preventDefault();
    body.classList.add('dropping');
  }));
  ['dragleave', 'drop'].forEach((ev) => body.addEventListener(ev, (e) => {
    e.preventDefault();
    if (ev === 'dragleave' && e.relatedTarget && body.contains(e.relatedTarget)) return;
    body.classList.remove('dropping');
  }));
  body.addEventListener('drop', (e) => {
    if (e.dataTransfer?.files?.length) handleDrop(e.dataTransfer.files);
  });

  /* ------------------ 启动 ------------------ */
  async function boot() {
    const d = await getJSON('/api/state');
    state.tracks = d.tracks || [];
    state.folders = d.folders || [];
    state.speed = snapSpeed(d.speed ?? 1);
    state.volume = typeof d.volume === 'number' ? d.volume : 0.85;
    state.seq = d.upload_seq || 0;
    state.current = d.current || null;
    state.info = d.info;

    setSpeed(state.speed, false);
    setVolume(state.volume, false);

    if (state.current) {
      audio.src = `/media/${state.current}`;
      audio.playbackRate = state.speed;
      audio.volume = state.volume;
      // 默认不自动播放：仅加载，等待老师点击
    }
    renderTracks();
    renderRecent();
    renderFolders();
    renderInfo();
    renderNow();
    loadQr({ fresh: true });
    startQrWatch();

    setInterval(() => poll(false), 1200);
    setInterval(() => { if (modal.hidden) renderInfo(); }, 3000);
  }

  window.addEventListener('pywebviewready', () => {
    document.body.classList.add('native');
  });

  boot().catch((e) => console.error(e));
})();
