'use strict';
// IPTV-Forge page logic. Everything real happens in gui/forge_gui.py (class
// Api, reached as window.pywebview.api); this file draws its state and
// forwards clicks. Each page polls its runner for new log lines and progress.

const ICONS = {
  tv: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 3l4 4 4-4"/>',
  film: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1"/><path d="M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1"/>',
  play: '<path d="M7 4.5v15l12-7.5z" fill="currentColor"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/>',
  zap: '<path d="M13 2L4 14h7l-1 8 9-12h-7z" fill="currentColor"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  file: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4M9 13h6M9 17h6"/>',
  sliders: '<path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/><circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>',
  terminal: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3M13 15h4"/>',
  download: '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
  upload: '<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
  refresh: '<path d="M20 11a8 8 0 0 0-14.9-3M4 4v4h4"/><path d="M4 13a8 8 0 0 0 14.9 3M20 20v-4h-4"/>',
  trash: '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  alert: '<path d="M12 7v6M12 17v.5"/>',
  dots: '<path d="M6 12h.01M12 12h.01M18 12h.01"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>',
  moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  star: '<path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
  activity: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
};
const MAIN_JOBS = ['更新直播', '点播筛选'];   // the ones the stepper follows
const HMT = ['香港', '澳门', '台湾'];

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
const svg = name => `<svg class="i" viewBox="0 0 24 24">${ICONS[name] || ''}</svg>`;
const clock = s => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;

let api, info = {}, env = null;
const pages = { live: { since: 0, running: false }, vod: { since: 0, running: false } };

window.addEventListener('pywebviewready', async () => {
  api = window.pywebview.api;
  $$('i[data-icon]').forEach(el => { el.innerHTML = svg(el.dataset.icon); });
  applyTheme(localStorage.getItem('theme') || 'light');
  info = await api.info();
  document.body.classList.toggle('can-push', info.can_push);
  if (!info.has_publish) {
    const t = $('[data-flag="--no-publish"]');
    t.checked = t.disabled = true;
    t.closest('.toggle').querySelector('small').textContent = '没检测到 HK-IPTV 仓库，结果只保存在本地';
  }
  $('#vod-steps').innerHTML = info.vod_steps.map(s =>
    `<label><input type="checkbox" value="${s.key}" checked><span class="k">${s.key}</span>${esc(s.label)}</label>`).join('');
  $('#check-file').value = info.check_default;
  renderSteps('live', info.live_stages, -1, '');
  renderSteps('vod', info.vod_steps.map(s => s.short), -1, '');
  bind();
  refreshStats();
  refreshEnv();
  poll();
});

// ---------------------------------------------------------------- wiring

function bind() {
  $$('.nav-item[data-page]').forEach(a => { a.onclick = () => showPage(a.dataset.page); });
  $('#theme').onclick = () => applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');

  $('#live-go').onclick = () => {
    const flags = $$('[data-flag]').filter(c => c.checked).map(c => c.dataset.flag);
    if (env && !env.docker && !flags.includes('--no-docker'))
      return toast('需要先安装 Docker Desktop，见「运行环境」', true);
    act(api.live_update(flags));
  };
  $('#vod-go').onclick = () => act(api.vod_run(info.vod_steps.map(s => s.key), $('#vod-fresh').checked));
  $('#vod-run-picked').onclick = () =>
    act(api.vod_run($$('#vod-steps input:checked').map(c => c.value), $('#vod-fresh').checked));
  $$('[data-preset]').forEach(b => {
    b.onclick = () => $$('#vod-steps input').forEach(c => {
      c.checked = b.dataset.preset === 'all' || b.dataset.preset.includes(c.value);
    });
  });
  $('#check-browse').onclick = async () => { const p = await api.pick_file(); if (p) $('#check-file').value = p; };
  $('#check-go').onclick = () => act(api.vod_check($('#check-file').value, $('#check-proxy').value));

  $$('[data-stop]').forEach(b => { b.onclick = () => api.stop(b.dataset.stop); });
  $$('[data-open]').forEach(b => { b.onclick = () => act(api.open(b.dataset.open)); });
  $$('[data-docker]').forEach(b => { b.onclick = () => act(api.live_docker(b.dataset.docker)); });
  $$('[data-publish]').forEach(b => { b.onclick = () => publish(b.dataset.publish); });
  $$('[data-copy]').forEach(b => { b.onclick = () => copy(b.dataset.copy); });
  $$('[data-clear]').forEach(b => {
    b.onclick = () => { api.clear(b.dataset.clear); $(`[data-log="${b.dataset.clear}"]`).innerHTML = ''; };
  });
  $('#env-refresh').onclick = refreshEnv;
}

async function act(call) {
  const r = await call;
  if (r && r.error) toast(r.error, true);
  return r;
}

function showPage(name) {
  $$('.nav-item[data-page]').forEach(a => a.classList.toggle('active', a.dataset.page === name));
  $$('.page').forEach(p => p.classList.toggle('active', p.id === 'page-' + name));
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem('theme', theme);
  const b = $('#theme');
  b.querySelector('i').innerHTML = svg(theme === 'dark' ? 'sun' : 'moon');
  b.querySelector('span').textContent = theme === 'dark' ? '浅色模式' : '深色模式';
}

// ---------------------------------------------------------------- polling

async function poll() {
  for (const page of ['live', 'vod']) {
    try {
      const s = await api.poll(page, pages[page].since);
      pages[page].since = s.seq;
      appendLog(page, s.lines);
      renderJob(page, s.job, s.running);
      const was = pages[page].running;
      pages[page].running = s.running;
      setBusy(page, s.running);
      if (was && !s.running) {
        refreshStats();
        const j = s.job;
        if (j.state === 'done') toast(`${j.title} 完成，用时 ${clock(j.elapsed)}`);
        else if (j.state === 'failed') toast(`${j.title} 失败，看运行日志`, true);
      }
    } catch (e) {
      console.error(e);
    }
  }
  setTimeout(poll, 400);
}

function appendLog(page, lines) {
  if (!lines.length) return;
  const box = $(`[data-log="${page}"]`);
  const follow = box.scrollTop + box.clientHeight >= box.scrollHeight - 12;
  box.querySelector('.log-empty')?.remove();
  const frag = document.createDocumentFragment();
  for (const [, text, tag] of lines) {
    const span = document.createElement('span');
    if (tag) span.className = tag;
    span.textContent = text;
    frag.appendChild(span);
  }
  box.appendChild(frag);
  while (box.childNodes.length > 4000) box.firstChild.remove();
  if (follow) box.scrollTop = box.scrollHeight;
}

function renderJob(page, job, running) {
  if (!job) return;
  const main = MAIN_JOBS.includes(job.title);
  const n = job.stages.length;
  const label = $(`[data-state="${page}"]`);
  const bar = $(`[data-bar="${page}"]`);
  const current = job.stages[Math.min(job.stage, n - 1)];

  if (main) renderSteps(page, job.stages, job.stage, job.state);
  let text;
  if (job.state === 'running') {
    const pct = job.progress != null ? ` · ${Math.round(job.progress * 100)}%` : '';
    text = main ? `正在${current}${pct}` : `${job.title}：运行中${pct}`;
  } else {
    text = { done: '✓ 完成', failed: '✗ 失败，看下面的运行日志', stopped: '已停止' }[job.state];
    if (!main) text = `${job.title}：${text}`;
  }
  label.textContent = text;
  label.className = job.state;
  $(`[data-time="${page}"]`).textContent = '用时 ' + clock(job.elapsed);

  if (main || running) {
    const done = job.state === 'done' ? n : job.stage + (job.progress || 0);
    bar.style.width = `${Math.min(100, done / n * 100)}%`;
    bar.classList.toggle('failed', job.state === 'failed');
  }
}

function renderSteps(page, stages, stage, state) {
  const ol = $(`[data-steps="${page}"]`);
  const key = JSON.stringify([stages, stage, state]);
  if (ol.dataset.key === key) return;     // unchanged: keep the running animation smooth
  ol.dataset.key = key;
  ol.innerHTML = stages.map((name, i) => {
    let cls = '';
    if (i < stage || state === 'done') cls = 'done';
    else if (i === stage) cls = state === 'running' ? 'running' : state === 'failed' ? 'failed' : '';
    const mark = cls === 'done' ? svg('check') : cls === 'failed' ? svg('x') : i + 1;
    return `<li class="${cls}"><span class="dot">${mark}</span><span class="label">${esc(name)}</span></li>`;
  }).join('');
}

function setBusy(page, running) {
  $(`.nav-item[data-page="${page}"]`).classList.toggle('busy', running);
  $(`[data-stop="${page}"]`).disabled = !running;
  $(`#${page}-go`).disabled = running;
  if (page === 'vod') $('#vod-run-picked').disabled = $('#check-go').disabled = running;
}

// ---------------------------------------------------------------- data

async function refreshStats() {
  const s = await api.stats();

  const groups = s.live.groups;
  const total = groups.reduce((a, [, n]) => a + n, 0);
  const hmt = HMT.map(k => (groups.find(g => g[0] === k) || [k, 0])[1]);
  $('#live-total').textContent = total ? total.toLocaleString() : '—';
  $('#live-time').textContent = s.live.time ? `更新于 ${s.live.time}` : '还没有结果，点「一键更新」';
  $('#live-hmt').textContent = total ? hmt.reduce((a, b) => a + b, 0).toLocaleString() : '—';
  ratio('live-hmt', HMT.map((k, i) => [k, hmt[i], ['#0ea5e9', '#10b981', '#8b5cf6'][i]]));
  $('#live-file').textContent = s.live.file;
  const max = Math.max(1, ...groups.map(g => g[1]));
  $('#live-groups').innerHTML = groups.length ? groups.map(([g, n]) => `
    <div class="bar-row ${HMT.includes(g) ? 'hmt' : ''}">
      <span>${esc(g)}</span><div class="track"><div class="fill" style="width:${Math.max(2, n / max * 100)}%"></div></div>
      <span class="n">${n.toLocaleString()}</span>
    </div>`).join('') : '<div class="empty">还没有结果，跑一次「一键更新」就有了</div>';

  const v = s.vod;
  $('#vod-active').textContent = v.time ? v.active : '—';
  $('#vod-time').textContent = v.time ? `更新于 ${v.time}` : '还没有结果，点「一键筛选」';
  ratio('vod', [['可用', v.active, '#10b981'], ['失效已注释', v.dead, '#cbd5e1']]);
  $('#vod-cands').textContent = v.candidates || '—';
  $('#vod-sub').textContent = `${v.candidates} 个候选逐个探测，不需要 Docker，几分钟跑完`;
  $('#vod-file').textContent = v.file;
  $('#vod-picks').innerHTML = v.picks.length ? v.picks.map(p =>
    `<span class="pick" title="${esc(p.url)}"><span class="rank">${p.rank}</span>${esc(p.name)}</span>`).join('')
    : '<div class="empty">还没有精选，跑一次「一键筛选」就有了</div>';
  $('#note-live').textContent = s.live.file;
  $('#note-vod').textContent = v.file;
}

// a proportion bar + legend: parts are [label, count, colour]
function ratio(id, parts) {
  const sum = parts.reduce((a, p) => a + p[1], 0);
  $(`#${id}-ratio`).innerHTML = sum ? parts.filter(p => p[1]).map(([, n, c]) =>
    `<span style="flex:${n};background:${c}"></span>`).join('') : '';
  $(`#${id}-legend`).innerHTML = sum ? parts.map(([k, n, c]) =>
    `<span><i style="background:${c}"></i>${k} <b>${n}</b></span>`).join('') : '';
}

async function refreshEnv() {
  const ul = $('#env');
  ul.innerHTML = check('wait', 'dots', '检测中…', '');
  env = await api.env();
  const items = [];
  if (!env.docker)
    items.push(['bad', 'x', '没有安装 Docker Desktop',
      '直播的抓取测速引擎跑在 Docker 里 · <a href="https://www.docker.com/products/docker-desktop/" target="_blank">去下载</a>（点播不需要）']);
  else if (!env.docker_running)
    items.push(['warn', 'alert', 'Docker 已安装，还没启动', '点「一键更新」时会自动启动它']);
  else
    items.push(['ok', 'check', 'Docker 正在运行', '抓取 + 测速引擎就绪']);
  if (!env.proxy_port)
    items.push(['warn', 'alert', '没有配置代理', 'GitHub 上的订阅源在国内可能抓不到，可在「测速 / 代理」里设置 http_proxy']);
  else if (env.proxy_ok)
    items.push(['ok', 'check', `代理 127.0.0.1:${env.proxy_port} 可用`, '只用来抓取在线订阅，测速始终直连']);
  else
    items.push(['warn', 'alert', `代理 127.0.0.1:${env.proxy_port} 连不上`, '先打开代理软件，否则订阅源抓取失败，结果只剩本地源']);
  items.push(info.has_publish
    ? ['ok', 'check', '已连接 HK-IPTV 仓库', info.can_push ? '跑完可以一键提交并推送' : '结果会复制过去']
    : ['ok', 'check', '结果保存在本地', '不需要 HK-IPTV 仓库也能完整使用']);
  ul.innerHTML = items.map(i => check(...i)).join('');
}

const check = (cls, icon, title, sub) =>
  `<li class="${cls}"><span class="mark">${svg(icon)}</span><div><b>${title}</b><small>${sub}</small></div></li>`;

// ---------------------------------------------------------------- publish / overlays

async function publish(page) {
  const r = await act(api.git_prepare(page));
  if (!r || r.error) return;
  if (!r.changed) {
    if (await dialog('没有新的改动', `${r.file} 和上次提交的一样。\n仍然执行 git push 吗？（比如上次推送失败了）`))
      act(api.git_publish(page, ''));
    return;
  }
  const msg = await dialog('提交并推送到 GitHub',
    `把 HK-IPTV/${r.file} 提交并 push，订阅地址几分钟后更新。\n提交信息：`, r.message);
  if (msg) act(api.git_publish(page, msg));
}

// resolves to the input text (prompt), true (confirm), or null / false on cancel
function dialog(title, text, value) {
  const m = $('#modal'), input = $('#modal-input');
  $('#modal-title').textContent = title;
  $('#modal-text').textContent = text;
  input.hidden = value === undefined;
  input.value = value || '';
  m.hidden = false;
  if (!input.hidden) input.focus();
  return new Promise(resolve => {
    const done = ok => {
      m.hidden = true;
      resolve(input.hidden ? ok : ok ? input.value.trim() || null : null);
    };
    $('#modal-ok').onclick = () => done(true);
    $('#modal-cancel').onclick = () => done(false);
    input.onkeydown = e => { if (e.key === 'Enter') done(true); if (e.key === 'Escape') done(false); };
  });
}

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const t = document.createElement('textarea');
    t.value = text;
    document.body.appendChild(t);
    t.select();
    document.execCommand('copy');
    t.remove();
  }
  toast('已复制，粘贴到播放器里即可');
}

let toastTimer;
function toast(text, error) {
  const t = $('#toast');
  t.textContent = text;
  t.classList.toggle('error', !!error);
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), error ? 4500 : 2600);
}
