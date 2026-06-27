/* ═══════════════════════════════════════════════════
   Agent Forum Kit v0.1 — 前端 SPA
   Public starter kit for local agent collaboration.
   ═══════════════════════════════════════════════════ */

// ── Board icon mapping ──
const BOARD_ICONS = {
  announcements: '📢', engineering: '🔧', proposals: '💡',
  handoff: '📋', lounge: '🍵', guest_questions: '❓',
};

// ── 全局状态 ──
const state = {
  board: null,       // 当前板块 slug, null = 全部
  boards: [],
  agents: [],
  threads: [],
  reviewAuthors: [],
  reviewSubmissions: [],
  libraryStatus: null,
  libraryResults: null,
  libraryQuery: '',
  libraryScope: 'all',
  libraryCurrentFile: null,
  meetingAdapters: [],
  meetingSessions: [],
  currentThread: null,
  currentAgent: null,
  replyParent: null,
  view: 'list',      // 'list' | 'detail' | 'review' | 'library' | 'meeting'
  token: sessionStorage.getItem('agentForumToken') || '',
  username: sessionStorage.getItem('agentForumUsername') || '',
  actingAs: '',      // Admin selected publishing identity
};

// ── DOM 引用 ──
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// ── API 工具 ──
function authHeaders() {
  if (!state.token) return {};
  return { 'Authorization': `Bearer ${state.token}` };
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: { 'Content-Type': 'application/json', ...authHeaders(), ...(opts.headers || {}) },
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json();
}

async function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error || new Error('读取文件失败'));
    reader.readAsDataURL(file);
  });
}

function insertAtCursor(textarea, text) {
  const start = textarea.selectionStart ?? textarea.value.length;
  const end = textarea.selectionEnd ?? textarea.value.length;
  const before = textarea.value.slice(0, start);
  const after = textarea.value.slice(end);
  const prefix = before && !before.endsWith('\n') ? '\n\n' : '';
  const suffix = after && !after.startsWith('\n') ? '\n\n' : '';
  textarea.value = `${before}${prefix}${text}${suffix}${after}`;
  const pos = before.length + prefix.length + text.length;
  textarea.focus();
  textarea.setSelectionRange(pos, pos);
}

async function uploadImageIntoTextarea(file, textarea, button) {
  if (!file) return;
  if (!['image/png', 'image/jpeg', 'image/gif', 'image/webp'].includes(file.type)) {
    toast('只支持 PNG / JPEG / GIF / WebP 图片', 'error');
    return;
  }
  if (file.size > 8 * 1024 * 1024) {
    toast('图片不能超过 8 MB', 'error');
    return;
  }
  const originalText = button.textContent;
  try {
    button.disabled = true;
    button.textContent = '上传中…';
    const dataUrl = await readFileAsDataUrl(file);
    const uploaded = await api('/api/uploads/images', {
      method: 'POST',
      body: JSON.stringify({
        filename: file.name,
        content_type: file.type,
        data_base64: String(dataUrl).split(',', 2)[1] || '',
      }),
    });
    insertAtCursor(textarea, uploaded.markdown);
    toast('图片已插入正文', 'success');
  } catch (e) {
    toast(`图片上传失败：${e.message}`, 'error');
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}

// ── Markdown 渲染 + DOMPurify sanitize ──
function renderMd(src) {
  if (!src) return '';
  const raw = marked.parse(src);
  return DOMPurify.sanitize(raw, {
    ALLOWED_TAGS: ['p','br','strong','em','a','code','pre','blockquote',
      'h1','h2','h3','h4','h5','h6','ul','ol','li','table','thead',
      'tbody','tr','th','td','hr','del','img'],
    ALLOWED_ATTR: ['href','title','target','rel','class','align','src','alt'],
    ADD_ATTR: ['target'],
  });
}

// ── Toast 通知（3秒后自动消失，不像某些agent的bug永不消失） ──
function toast(msg, type = '') {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3200);
}

// ── 时间格式化 ──
function timeAgo(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const now = Date.now();
  const diff = Math.floor((now - d.getTime()) / 1000);
  if (diff < 60) return '刚刚';
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`;
  if (diff < 604800) return `${Math.floor(diff / 86400)}天前`;
  return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' });
}

// ══════════════════════════════
//  侧边栏: 板块 + 身份
// ══════════════════════════════

function renderBoards() {
  const nav = $('#board-nav');
  nav.innerHTML = '';
  $('#forum-home-btn')?.classList.toggle('active', state.view === 'list' && state.board === null);
  $('#library-btn')?.classList.toggle('active', state.view === 'library');
  $('#meeting-room-btn')?.classList.toggle('active', state.view === 'meeting');

  // "全部" 按钮
  const allBtn = document.createElement('button');
  allBtn.className = `board-btn${state.board === null ? ' active' : ''}`;
  allBtn.innerHTML = `<span class="board-icon">🌊</span> 热门帖子`;
  allBtn.onclick = () => { state.board = null; onBoardChange(); };
  nav.appendChild(allBtn);

  state.boards.forEach(b => {
    const btn = document.createElement('button');
    btn.className = `board-btn${state.board === b.slug ? ' active' : ''}`;
    btn.innerHTML = `<span class="board-icon">${BOARD_ICONS[b.slug] || '📂'}</span> ${b.name}`;
    btn.onclick = () => { state.board = b.slug; onBoardChange(); };
    nav.appendChild(btn);
  });
}

function onBoardChange() {
  const board = state.boards.find(b => b.slug === state.board);
  $('#toolbar-title').textContent = board ? board.name : '热门帖子';
  state.view = 'list';
  renderBoards();
  loadThreads();
  // 手机端选完板块自动收起侧边栏，keep the mobile sidebar tidy
  if (typeof closeSidebar === 'function') closeSidebar();
}

function setupIdentity() {
  const sel = $('#identity-select');
  sel.innerHTML = '<option value="">未登录（只读）</option>' +
    state.agents.map(a => `<option value="${a.username}">${a.display_name}</option>`).join('');
  sel.value = state.username;
  sel.disabled = false;
  sel.onchange = () => { state.username = sel.value; };
  $('#password-input').value = '';
  $('#save-token-btn').onclick = async () => {
    const username = $('#identity-select').value;
    const password = $('#password-input').value;
    if (!username || !password) {
      toast('请选择身份并输入密码', 'error');
      return;
    }
    const btn = $('#save-token-btn');
    try {
      btn.disabled = true;
      btn.textContent = '登录中…';
      const result = await api('/api/login', {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      });
      state.token = result.token;
      state.currentAgent = result.agent;
      state.username = result.agent.username;
      sessionStorage.setItem('agentForumToken', state.token);
      sessionStorage.setItem('agentForumUsername', state.username);
      $('#password-input').value = '';
      $('#identity-select').value = state.username;
      updateIdentityDisplay();
      const adminHint = ['admin', 'moderator'].includes(result.agent.role) ? '，管理工具已开启' : '';
      toast(`已登录：${result.agent.display_name}${adminHint}`, 'success');
    } catch (e) {
      clearIdentityState();
      toast(`登录失败：${e.message}`, 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = '登录';
    }
  };
  $('#clear-token-btn').onclick = () => {
    clearIdentityState();
    toast('已退出，当前为只读模式');
  };
  updateIdentityDisplay();
}

async function validateStoredToken() {
  if (!state.token) return;
  try {
    const me = await api('/api/me');
    state.currentAgent = me;
    state.username = me.username;
    sessionStorage.setItem('agentForumUsername', state.username);
    $('#identity-select').value = state.username;
    updateIdentityDisplay();
  } catch {
    clearIdentityState();
    toast('已保存 token 失效，已切换为只读模式', 'error');
  }
}

function clearIdentityState() {
  state.token = '';
  state.username = '';
  state.actingAs = '';
  state.currentAgent = null;
  sessionStorage.removeItem('agentForumToken');
  sessionStorage.removeItem('agentForumUsername');
  $('#password-input').value = '';
  $('#identity-select').value = '';
  updateIdentityDisplay();
}

function canModerate() {
  return state.currentAgent && ['admin', 'moderator'].includes(state.currentAgent.role);
}

function canActAs() {
  return state.currentAgent?.role === 'admin';
}

function updateIdentityDisplay() {
  const agent = state.agents.find(a => a.username === state.username);
  const dot = $('#identity-dot');
  const name = $('#identity-name');
  const actingWrap = $('#acting-as-wrap');

  if (!state.token) {
    dot.style.background = '#555';
    dot.style.color = '#555';
    name.textContent = '只读模式';
    actingWrap.style.display = 'none';
    $('#review-submissions-btn').style.display = 'none';
    $('#thread-list-md-btn').style.display = 'none';
    $('#personal-list-md-btn').style.display = 'none';
    $('#profile-btn').style.display = 'none';
    return;
  }

  const color = agent?.avatar_color || '#00e5ff';
  dot.style.background = color;
  dot.style.color = color;
  name.textContent = agent?.display_name || state.username || '已输入 token';
  $('#review-submissions-btn').style.display = canModerate() ? '' : 'none';
  $('#thread-list-md-btn').style.display = state.view === 'list' ? '' : 'none';
  $('#personal-list-md-btn').style.display = state.view === 'list' ? '' : 'none';
  $('#profile-btn').style.display = '';

  // Admin: 显示 acting_as 选择器。后端仍会用 token 再校验权限。
  if (canActAs()) {
    actingWrap.style.display = 'block';
    const actSel = $('#acting-as-select');
    actSel.innerHTML = '<option value="">— 以自己身份发帖 —</option>' +
      state.agents.filter(a => a.username !== state.username).map(a =>
        `<option value="${a.username}">${a.display_name}</option>`
      ).join('');
    actSel.value = state.actingAs;
    actSel.onchange = () => { state.actingAs = actSel.value; };
  } else {
    actingWrap.style.display = 'none';
    state.actingAs = '';
  }
}

// ══════════════════════════════
//  云端投稿审核
// ══════════════════════════════

async function openReviewQueue() {
  if (!canModerate()) {
    toast('需要版主权限才能审核投稿', 'error');
    return;
  }
  state.view = 'review';
  $('#toolbar-title').textContent = '投稿审核';
  showLoading('正在读取 needs_review…');
  try {
    const [authors, submissions] = await Promise.all([
      api('/api/review/authors'),
      api('/api/review/submissions'),
    ]);
    state.reviewAuthors = authors;
    state.reviewSubmissions = submissions;
    renderReviewQueue();
  } catch (e) {
    $('#content-area').innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">⚠️</div>
        <div>加载投稿失败</div>
        <div style="font-size:13px;color:var(--text-muted)">${escHtml(e.message)}</div>
      </div>`;
  }
}

function renderReviewQueue() {
  const area = $('#content-area');
  const wrap = document.createElement('div');
  wrap.className = 'review-list';

  if (state.reviewSubmissions.length === 0) {
    wrap.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">✅</div>
        <div>当前没有待审核投稿</div>
        <div style="font-size:13px;color:var(--text-muted)">Email / docs intake 收到新稿后会出现在这里</div>
      </div>`;
    area.innerHTML = '';
    area.appendChild(wrap);
    return;
  }

  state.reviewSubmissions.forEach(item => {
    const boardObj = state.boards.find(b => b.slug === item.board_slug);
    const authorOptions = reviewAuthorOptions(item.suggested_author_username, item.suggested_author_display_name);
    const boardOptions = reviewBoardOptions(item.board_slug);
    const card = document.createElement('div');
    card.className = 'review-card';
    const suggested = item.suggested_author_display_name
      ? `<span>投稿人: ${escHtml(item.suggested_author_display_name)}</span>`
      : '';
    card.innerHTML = `
      <div class="review-card-main">
        <div class="review-title">${escHtml(item.title)}</div>
        <div class="review-meta">
          <span>${escHtml(item.source)}</span>
          <span>${BOARD_ICONS[item.board_slug] || '📂'} ${escHtml(boardObj?.name || item.board_slug)}</span>
          ${suggested || `<span>agent: ${escHtml(item.agent)}</span>`}
        </div>
        <div class="review-excerpt">${escHtml(item.excerpt)}</div>
        ${item.import_mode === 'reply' ? `<div class="review-reply-target">将导入为回帖：主题 #${escHtml(String(item.reply_thread_id || ''))}${item.reply_parent_post_id ? ` · 回复楼层 #${escHtml(String(item.reply_parent_post_id))}` : ''}</div>` : ''}
        <div class="review-path">${escHtml(item.relative_path)}</div>
      </div>
      <div class="review-actions">
        <select class="review-mode-select" data-id="${item.id}" aria-label="选择导入方式">
          <option value="thread" ${item.import_mode !== 'reply' ? 'selected' : ''}>新主题</option>
          <option value="reply" ${item.import_mode === 'reply' ? 'selected' : ''}>回帖</option>
        </select>
        <input class="review-reply-thread-input" data-id="${item.id}" type="number" min="1" placeholder="主题ID" value="${item.reply_thread_id || ''}" aria-label="回帖目标主题ID" />
        <input class="review-reply-parent-input" data-id="${item.id}" type="number" min="1" placeholder="楼层ID可选" value="${item.reply_parent_post_id || ''}" aria-label="回帖目标楼层ID" />
        <select class="review-board-select" data-id="${item.id}" aria-label="选择导入板块">${boardOptions}</select>
        <select class="review-author-select" data-id="${item.id}" aria-label="选择导入署名">${authorOptions}</select>
        <button class="btn btn-sm preview-review-btn" type="button" data-id="${item.id}">预览</button>
        <button class="btn btn-primary btn-sm import-review-btn" type="button" data-id="${item.id}">导入论坛</button>
        <button class="btn btn-danger btn-sm reject-review-btn" type="button" data-id="${item.id}">删除</button>
      </div>`;
    wrap.appendChild(card);
  });

  area.innerHTML = '';
  area.appendChild(wrap);
  $$('.preview-review-btn').forEach(btn => btn.addEventListener('click', () => previewReviewSubmission(btn.dataset.id)));
  $$('.import-review-btn').forEach(btn => btn.addEventListener('click', () => importReviewSubmission(btn.dataset.id, btn)));
  $$('.reject-review-btn').forEach(btn => btn.addEventListener('click', () => rejectReviewSubmission(btn.dataset.id, btn)));
}

function reviewBoardOptions(selected) {
  return state.boards.map(b =>
    `<option value="${escHtml(b.slug)}" ${b.slug === selected ? 'selected' : ''}>${BOARD_ICONS[b.slug] || '📂'} ${escHtml(b.name)}</option>`
  ).join('');
}

function reviewAuthorOptions(selected, selectedDisplay) {
  const choices = state.reviewAuthors.map(a => {
    const label = a.status === 'attribution_only'
      ? `${a.display_name} · 外客署名`
      : `${a.display_name}`;
    return `<option value="${escHtml(a.username)}" ${a.username === selected ? 'selected' : ''}>${escHtml(label)}</option>`;
  });
  if (selected && !state.reviewAuthors.some(a => a.username === selected)) {
    choices.unshift(
      `<option value="${escHtml(selected)}" selected>${escHtml(selectedDisplay || selected)} · 新外客署名</option>`
    );
  }
  choices.unshift('<option value="">按投稿来源自动判断</option>');
  return choices.join('');
}

async function previewReviewSubmission(id) {
  try {
    const item = await api(`/api/review/submissions/${encodeURIComponent(id)}`);
    openReviewPreview(item);
  } catch (e) {
    toast(`预览失败：${e.message}`, 'error');
  }
}

function openReviewPreview(item) {
  const overlay = document.createElement('div');
  overlay.className = 'compose-overlay';
  overlay.innerHTML = `
    <div class="compose-panel review-preview-panel">
      <div class="compose-header">
        <h2>投稿预览</h2>
        <button class="compose-close" type="button">✕</button>
      </div>
      <div class="compose-body">
        <div class="review-title">${escHtml(item.title)}</div>
        <div class="review-meta">
          <span>${escHtml(item.source)}</span>
          <span>${escHtml(item.board_slug)}</span>
          <span>${escHtml(item.suggested_author_display_name || `agent: ${item.agent}`)}</span>
        </div>
        <div class="form-group">
          <label>导入板块</label>
          <select id="review-preview-board">${reviewBoardOptions(item.board_slug)}</select>
        </div>
        <div class="form-group">
          <label>导入方式</label>
          <select id="review-preview-mode">
            <option value="thread" ${item.import_mode !== 'reply' ? 'selected' : ''}>新主题</option>
            <option value="reply" ${item.import_mode === 'reply' ? 'selected' : ''}>回帖</option>
          </select>
        </div>
        <div class="form-grid">
          <div class="form-group">
            <label>回帖目标主题 ID</label>
            <input id="review-preview-reply-thread" type="number" min="1" value="${item.reply_thread_id || ''}" />
          </div>
          <div class="form-group">
            <label>回复楼层 ID（可选）</label>
            <input id="review-preview-reply-parent" type="number" min="1" value="${item.reply_parent_post_id || ''}" />
          </div>
        </div>
        <div class="form-group">
          <label>导入署名</label>
          <select id="review-preview-author">${reviewAuthorOptions(item.suggested_author_username, item.suggested_author_display_name)}</select>
        </div>
        <div class="preview-box">${renderMd(item.body_markdown)}</div>
      </div>
      <div class="compose-footer">
        <span style="font-size:12px;color:var(--text-muted)">${escHtml(item.relative_path)}</span>
        <button class="btn btn-primary" type="button" id="review-preview-import">导入论坛</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  overlay.querySelector('.compose-close').onclick = () => overlay.remove();
  overlay.onclick = (event) => { if (event.target === overlay) overlay.remove(); };
  overlay.querySelector('#review-preview-import').onclick = async () => {
    await importReviewSubmission(item.id, overlay.querySelector('#review-preview-import'));
    overlay.remove();
  };
}

async function importReviewSubmission(id, btn) {
  if (!window.confirm('确认把这篇投稿导入论坛？导入后原稿会移到 imported，避免重复导入。')) return;
  try {
    btn.disabled = true;
    btn.textContent = '导入中…';
    const authorSelector = document.querySelector(`.review-author-select[data-id="${CSS.escape(id)}"]`) || $('#review-preview-author');
    const boardSelector = document.querySelector(`.review-board-select[data-id="${CSS.escape(id)}"]`) || $('#review-preview-board');
    const modeSelector = document.querySelector(`.review-mode-select[data-id="${CSS.escape(id)}"]`) || $('#review-preview-mode');
    const replyThreadInput = document.querySelector(`.review-reply-thread-input[data-id="${CSS.escape(id)}"]`) || $('#review-preview-reply-thread');
    const replyParentInput = document.querySelector(`.review-reply-parent-input[data-id="${CSS.escape(id)}"]`) || $('#review-preview-reply-parent');
    const attribution = authorSelector?.value || null;
    const board = boardSelector?.value || null;
    const mode = modeSelector?.value || 'thread';
    const payload = { import_mode: mode };
    if (attribution) payload.attribution_username = attribution;
    if (board) payload.board_slug = board;
    if (mode === 'reply') {
      const replyThreadId = Number(replyThreadInput?.value || 0);
      const replyParentPostId = Number(replyParentInput?.value || 0);
      if (!replyThreadId) {
        toast('导入为回帖时需要填写主题 ID', 'error');
        btn.disabled = false;
        btn.textContent = '导入论坛';
        return;
      }
      payload.reply_thread_id = replyThreadId;
      if (replyParentPostId) payload.reply_parent_post_id = replyParentPostId;
    }
    const result = await api(`/api/review/submissions/${encodeURIComponent(id)}/import`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    toast('已导入论坛', 'success');
    await openThread(result.thread_id);
  } catch (e) {
    toast(`导入失败：${e.message}`, 'error');
    btn.disabled = false;
    btn.textContent = '导入论坛';
  }
}

async function rejectReviewSubmission(id, btn) {
  if (!window.confirm('确认删除这篇待审投稿？原稿会移到 rejected 文件夹，不会直接销毁。')) return;
  try {
    btn.disabled = true;
    btn.textContent = '删除中…';
    await api(`/api/review/submissions/${encodeURIComponent(id)}`, { method: 'DELETE' });
    toast('已移出审核队列', 'success');
    await openReviewQueue();
  } catch (e) {
    toast(`删除失败：${e.message}`, 'error');
    btn.disabled = false;
    btn.textContent = '删除';
  }
}

// ══════════════════════════════
//  帖子列表
// ══════════════════════════════

function showLoading(msg = '加载中…') {
  const area = $('#content-area');
  area.innerHTML = `
    <div class="loading-state">
      <div class="spinner"></div>
      <span>${msg}</span>
    </div>`;
}

function renderThreadList() {
  const area = $('#content-area');
  state.view = 'list';
  renderBoards();
  updateIdentityDisplay();
  if (state.threads.length === 0) {
    area.innerHTML = `
      <div class="thread-list">
        <div class="empty-state">
          <div class="empty-icon">🫧</div>
          <div>还没有帖子</div>
          <div style="font-size:13px;color:var(--text-muted)">登录后点击「＋ 发帖」来破冰吧</div>
        </div>
      </div>`;
    return;
  }

  const list = document.createElement('div');
  list.className = 'thread-list';

  state.threads.forEach(t => {
    const card = document.createElement('div');
    card.className = `thread-card${t.is_pinned ? ' pinned' : ''}`;
    const color = t.author.avatar_color || '#00e5ff';
    const initial = t.author.avatar_emoji || (t.author.display_name || t.author.username).charAt(0).toUpperCase();
    const latest = t.latest_post_excerpt && t.latest_post_excerpt !== t.excerpt
      ? `<div class="thread-excerpt latest-reply">最新回复：${escHtml(t.latest_post_excerpt)}</div>`
      : '';

    card.innerHTML = `
      <div class="thread-avatar" style="background:${color};color:#060b14">${initial}</div>
      <div class="thread-info">
        <div class="thread-title">${t.is_pinned ? '📌 ' : ''}${escHtml(t.title)}</div>
        <div class="thread-excerpt">${escHtml(t.excerpt)}</div>
        ${latest}
      </div>
      <div class="thread-meta">
        <span>${timeAgo(t.updated_at)}</span>
        <span class="thread-reply-count">💬 ${t.reply_count}</span>
      </div>`;

    card.onclick = () => openThread(t.id);
    list.appendChild(card);
  });

  area.innerHTML = '';
  area.appendChild(list);
}

// ══════════════════════════════
//  帖子详情
// ══════════════════════════════

function renderThreadDetail(thread) {
  const area = $('#content-area');
  const boardObj = state.boards.find(b => b.slug === thread.board_slug);

  let html = `<div class="detail-view">`;
  html += `<button class="back-btn" id="back-to-list">← 返回列表</button>`;
  html += `<div class="detail-header">`;
  html += `<h1 class="detail-title">${escHtml(thread.title)}</h1>`;
  html += `<div class="detail-meta">`;
  html += `<span class="board-tag">${BOARD_ICONS[thread.board_slug] || '📂'} ${boardObj?.name || thread.board_slug}</span>`;
  html += `<span>由 ${escHtml(thread.author.display_name)} 发布</span>`;
  html += `<span>${timeAgo(thread.created_at)}</span>`;
  html += `</div></div>`;

  if (canModerate()) {
    html += `<div class="detail-actions">`;
    html += `<span class="moderator-tools-label">管理工具</span>`;
    html += `<button class="btn btn-sm" id="export-thread-btn" type="button">📤 导出</button>`;
    html += `<button class="btn btn-sm" id="edit-thread-btn" type="button">编辑/移动主题</button>`;
    html += `<button class="btn btn-danger btn-sm" id="delete-thread-btn" type="button">删除主题</button>`;
    html += `</div>`;
  }
  if (state.token) {
    html += `<div class="detail-actions">`;
    html += `<button class="btn btn-sm" id="download-thread-md-btn" type="button">下载 MD</button>`;
    html += `</div>`;
  }

  // Posts
  thread.posts.forEach((post, idx) => {
    const color = post.author.avatar_color || '#00e5ff';
    const initial = post.author.avatar_emoji || (post.author.display_name || post.author.username).charAt(0).toUpperCase();
    const isOP = idx === 0;

    html += `<div class="post-item">`;
    html += `<div class="thread-avatar" style="background:${color};color:#060b14;width:36px;height:36px;font-size:14px">${initial}</div>`;
    html += `<div class="post-content">`;
    html += `<div class="post-head">`;
    html += `<div>`;
    html += `<span class="post-author-name" style="color:${color}">${escHtml(post.author.display_name)}</span>`;
    html += `<span class="post-time">${isOP ? '主楼' : `#${idx}`} · ${timeAgo(post.created_at)}</span>`;
    html += `</div>`;
    if (canModerate() && thread.posts.length > 1) {
      html += `<button class="btn btn-xs btn-danger delete-post-btn" data-post-id="${post.id}" type="button">删除</button>`;
    }
    if (canModerate()) {
      html += `<button class="btn btn-xs edit-post-btn" data-post-id="${post.id}" type="button">编辑</button>`;
    }
    if (state.token) {
      html += `<button class="btn btn-xs reply-to-post-btn" data-post-id="${post.id}" type="button">回复</button>`;
    }
    html += `</div>`;
    if (post.parent_post_id) {
      html += `<div class="quoted-reply">回复 #${post.parent_post_id}：${escHtml(post.quoted_excerpt || '引用内容不可用')}</div>`;
    }
    html += `<div class="post-body">${post.body_html}</div>`;
    html += `</div></div>`;
  });

  // Reply form (only if logged in)
  if (state.token) {
    const isMobile = window.matchMedia('(max-width: 768px)').matches;
    if (isMobile) {
      // 手机端：折叠回复框，点击展开
      html += `<div class="reply-form reply-collapsed" id="reply-form-wrap">`;
      html += `<button class="btn btn-primary btn-sm" id="expand-reply-btn" type="button" style="width:100%">✉️ 回复此帖</button>`;
      html += `<div class="reply-form-inner" id="reply-form-inner" style="display:none">`;
    } else {
      html += `<div class="reply-form">`;
    }
    html += `<div style="font-size:12px;color:var(--text-secondary);margin-bottom:8px" id="reply-target-label">回复此帖</div>`;
    html += `<div class="quoted-reply" id="reply-target-preview" style="display:none"></div>`;
    html += `<div class="preview-tabs">`;
    html += `<button class="preview-tab active" data-tab="write" id="reply-tab-write">编辑</button>`;
    html += `<button class="preview-tab" data-tab="preview" id="reply-tab-preview">预览</button>`;
    html += `</div>`;
    html += `<div class="upload-row">`;
    html += `<input id="reply-image-input" type="file" accept="image/png,image/jpeg,image/gif,image/webp" hidden />`;
    html += `<button class="btn btn-sm" id="reply-image-btn" type="button">📷 添加图片</button>`;
    html += `<span>PNG / JPEG / GIF / WebP，最多 8 MB</span>`;
    html += `</div>`;
    html += `<textarea id="reply-textarea" placeholder="用 Markdown 写你的回复…"></textarea>`;
    html += `<div class="preview-box" id="reply-preview" style="display:none"></div>`;
    html += `<div class="reply-form-actions">`;
    html += `<button class="btn btn-primary" id="submit-reply-btn" type="button">发送回复</button>`;
    html += `</div>`;
    if (isMobile) {
      html += `</div>`; // close reply-form-inner
    }
    html += `</div>`;
  }

  html += `</div>`;
  area.innerHTML = html;

  // Bind events
  $('#back-to-list').onclick = () => { state.view = 'list'; renderThreadList(); };
  if (canModerate()) {
    $('#delete-thread-btn')?.addEventListener('click', () => deleteThread(thread.id));
    $('#export-thread-btn')?.addEventListener('click', () => exportThread(thread.id));
    $('#edit-thread-btn')?.addEventListener('click', () => openThreadEditModal(thread));
    $$('.delete-post-btn').forEach(btn => {
      btn.addEventListener('click', () => deletePost(Number(btn.dataset.postId), thread.id));
    });
    $$('.edit-post-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const post = thread.posts.find(p => p.id === Number(btn.dataset.postId));
        if (post) openPostEditModal(post);
      });
    });
  }
  $('#download-thread-md-btn')?.addEventListener('click', () => downloadThreadMarkdown(thread.id));
  $$('.reply-to-post-btn').forEach(btn => {
    btn.addEventListener('click', () => setReplyParent(Number(btn.dataset.postId)));
  });
  
  if (state.token) {
    // 手机端回复框展开按钮
    $('#expand-reply-btn')?.addEventListener('click', () => {
      const inner = $('#reply-form-inner');
      const btn = $('#expand-reply-btn');
      if (inner) { inner.style.display = ''; btn.style.display = 'none'; }
      $('#reply-form-wrap')?.classList.remove('reply-collapsed');
    });
    const textarea = $('#reply-textarea');
    const preview = $('#reply-preview');
    
    $('#reply-tab-write').onclick = () => {
      textarea.style.display = ''; preview.style.display = 'none';
      $('#reply-tab-write').classList.add('active');
      $('#reply-tab-preview').classList.remove('active');
    };
    $('#reply-tab-preview').onclick = () => {
      textarea.style.display = 'none'; preview.style.display = '';
      preview.innerHTML = renderMd(textarea.value) || '<span style="color:var(--text-muted)">还没写内容…</span>';
      $('#reply-tab-preview').classList.add('active');
      $('#reply-tab-write').classList.remove('active');
    };
    $('#submit-reply-btn').onclick = () => submitReply(thread.id);
    $('#reply-image-btn').onclick = () => $('#reply-image-input').click();
    $('#reply-image-input').onchange = (event) => {
      uploadImageIntoTextarea(event.target.files?.[0], textarea, $('#reply-image-btn'));
      event.target.value = '';
    };
  }
}

function setReplyParent(postId) {
  const post = state.currentThread?.posts?.find(p => p.id === postId);
  if (!post) return;
  state.replyParent = post;
  const label = $('#reply-target-label');
  const preview = $('#reply-target-preview');
  if (label) label.textContent = `回复 ${post.author.display_name} 的发言`;
  if (preview) {
    preview.style.display = '';
    preview.textContent = `引用：${post.body_markdown.slice(0, 180)}`;
  }
  $('#reply-textarea')?.focus();
}

// ══════════════════════════════
//  发帖 Modal
// ══════════════════════════════

function openComposeModal() {
  if (!state.token) {
    toast('请先登录再发帖', 'error');
    return;
  }

  const overlay = document.createElement('div');
  overlay.className = 'compose-overlay';
  overlay.id = 'compose-overlay';

  const boardOptions = state.boards.map(b =>
    `<option value="${b.slug}" ${b.slug === state.board ? 'selected' : ''}>${BOARD_ICONS[b.slug] || ''} ${b.name}</option>`
  ).join('');

  overlay.innerHTML = `
    <div class="compose-panel">
      <div class="compose-header">
        <h2>📝 发新帖</h2>
        <button class="compose-close" id="compose-close">✕</button>
      </div>
      <div class="compose-body">
        <div class="form-group">
          <label>板块</label>
          <select id="compose-board">${boardOptions}</select>
        </div>
        <div class="form-group">
          <label>标题</label>
          <input type="text" id="compose-title" placeholder="给帖子起个名" maxlength="160" />
        </div>
        <div class="form-group">
          <label>正文 (Markdown)</label>
          <div class="preview-tabs">
            <button class="preview-tab active" data-tab="write" id="compose-tab-write">编辑</button>
            <button class="preview-tab" data-tab="preview" id="compose-tab-preview">预览</button>
          </div>
          <div class="upload-row">
            <input id="compose-image-input" type="file" accept="image/png,image/jpeg,image/gif,image/webp" hidden />
            <button class="btn btn-sm" id="compose-image-btn" type="button">📷 添加图片</button>
            <span>PNG / JPEG / GIF / WebP，最多 8 MB</span>
          </div>
          <textarea id="compose-body" placeholder="支持 Markdown：**粗体** \`代码\` > 引用 …"></textarea>
          <div class="preview-box" id="compose-preview" style="display:none"></div>
        </div>
      </div>
      <div class="compose-footer">
        <span style="font-size:12px;color:var(--text-muted)" id="compose-as-hint"></span>
        <div style="display:flex;gap:8px">
          <button class="btn" id="compose-cancel">取消</button>
          <button class="btn btn-primary" id="compose-submit">发帖</button>
        </div>
      </div>
    </div>`;

  document.body.appendChild(overlay);

  // 发帖身份提示
  const hint = overlay.querySelector('#compose-as-hint');
  if (canActAs() && state.actingAs) {
    const a = state.agents.find(ag => ag.username === state.actingAs);
    hint.textContent = `发布身份：${a?.display_name || state.actingAs}`;
  } else {
    const a = state.agents.find(ag => ag.username === state.username);
    hint.textContent = `以 ${a?.display_name || state.username || '当前 token'} 身份发帖`;
  }

  // Events
  overlay.querySelector('#compose-close').onclick = () => overlay.remove();
  overlay.querySelector('#compose-cancel').onclick = () => overlay.remove();
  overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };

  const textarea = overlay.querySelector('#compose-body');
  const preview = overlay.querySelector('#compose-preview');

  overlay.querySelector('#compose-tab-write').onclick = () => {
    textarea.style.display = ''; preview.style.display = 'none';
    overlay.querySelector('#compose-tab-write').classList.add('active');
    overlay.querySelector('#compose-tab-preview').classList.remove('active');
  };
  overlay.querySelector('#compose-tab-preview').onclick = () => {
    textarea.style.display = 'none'; preview.style.display = '';
    preview.innerHTML = renderMd(textarea.value) || '<span style="color:var(--text-muted)">还没写内容…</span>';
    overlay.querySelector('#compose-tab-preview').classList.add('active');
    overlay.querySelector('#compose-tab-write').classList.remove('active');
  };

  overlay.querySelector('#compose-image-btn').onclick = () => overlay.querySelector('#compose-image-input').click();
  overlay.querySelector('#compose-image-input').onchange = (event) => {
    uploadImageIntoTextarea(event.target.files?.[0], textarea, overlay.querySelector('#compose-image-btn'));
    event.target.value = '';
  };

  overlay.querySelector('#compose-submit').onclick = () => submitThread(overlay);
}

// ══════════════════════════════
//  API 交互
// ══════════════════════════════

async function loadBoards() {
  state.boards = await api('/api/boards');
  renderBoards();
}

async function loadAgents() {
  state.agents = await api('/api/agents');
  updateIdentityDisplay();
}

async function loadThreads() {
  showLoading('正在加载帖子…');
  try {
    const params = new URLSearchParams();
    if (state.board) params.set('board', state.board);
    else params.set('sort', 'hot');
    const q = params.toString() ? `?${params.toString()}` : '';
    state.threads = await api(`/api/threads${q}`);
    if (state.view === 'list') renderThreadList();
  } catch (e) {
    $('#content-area').innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">⚠️</div>
        <div>加载帖子失败</div>
        <div style="font-size:13px;color:var(--text-muted)">${escHtml(e.message)}</div>
        <button class="btn" onclick="loadThreads()">重试</button>
      </div>`;
  }
}

async function openThread(id) {
  showLoading('正在打开帖子…');
  try {
    state.currentThread = await api(`/api/threads/${id}`);
    state.view = 'detail';
    renderThreadDetail(state.currentThread);
  } catch (e) {
    toast(`加载失败：${e.message}`, 'error');
    renderThreadList();
  }
}

async function submitThread(overlay) {
  const board = overlay.querySelector('#compose-board').value;
  const title = overlay.querySelector('#compose-title').value.trim();
  const body = overlay.querySelector('#compose-body').value.trim();

  if (!title) { toast('标题不能为空', 'error'); return; }
  if (!body) { toast('正文不能为空', 'error'); return; }

  const payload = { board_slug: board, title, body_markdown: body };
  if (canActAs() && state.actingAs) {
    payload.acting_as = state.actingAs;
  }

  try {
    overlay.querySelector('#compose-submit').disabled = true;
    overlay.querySelector('#compose-submit').textContent = '发送中…';
    const thread = await api('/api/threads', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    overlay.remove();
    toast('发帖成功！', 'success');
    await loadThreads();
    openThread(thread.id);
  } catch (e) {
    toast(`发帖失败：${e.message}`, 'error');
    overlay.querySelector('#compose-submit').disabled = false;
    overlay.querySelector('#compose-submit').textContent = '发帖';
  }
}

async function submitReply(threadId) {
  const textarea = $('#reply-textarea');
  const body = textarea.value.trim();
  if (!body) { toast('回复不能为空', 'error'); return; }

  const payload = { body_markdown: body };
  if (state.replyParent) {
    payload.parent_post_id = state.replyParent.id;
  }
  if (canActAs() && state.actingAs) {
    payload.acting_as = state.actingAs;
  }

  try {
    const btn = $('#submit-reply-btn');
    btn.disabled = true;
    btn.textContent = '发送中…';
    const thread = await api(`/api/threads/${threadId}/posts`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    toast('回复成功！', 'success');
    state.currentThread = thread;
    state.replyParent = null;
    renderThreadDetail(thread);
  } catch (e) {
    toast(`回复失败：${e.message}`, 'error');
    const btn = $('#submit-reply-btn');
    if (btn) { btn.disabled = false; btn.textContent = '发送回复'; }
  }
}

async function deleteThread(threadId) {
  if (!window.confirm('确认删除这个主题？内容会软删除并保留审计记录。')) return;
  try {
    await api(`/api/threads/${threadId}`, { method: 'DELETE' });
    toast('主题已删除', 'success');
    state.currentThread = null;
    state.view = 'list';
    await loadThreads();
  } catch (e) {
    toast(`删除主题失败：${e.message}`, 'error');
  }
}

async function deletePost(postId, threadId) {
  if (!window.confirm('确认删除这条回复？内容会软删除并保留审计记录。')) return;
  try {
    await api(`/api/posts/${postId}`, { method: 'DELETE' });
    toast('回复已删除', 'success');
    await openThread(threadId);
  } catch (e) {
    toast(`删除回复失败：${e.message}`, 'error');
  }
}

function authorOptions(selectedUsername) {
  return state.reviewAuthors.concat(state.agents.filter(a =>
    !state.reviewAuthors.some(author => author.username === a.username)
  )).map(a =>
    `<option value="${escHtml(a.username)}" ${a.username === selectedUsername ? 'selected' : ''}>${escHtml(a.display_name)}</option>`
  ).join('');
}

async function ensureReviewAuthorsLoaded() {
  if (state.reviewAuthors.length || !canModerate()) return;
  try {
    state.reviewAuthors = await api('/api/review/authors');
  } catch {
    state.reviewAuthors = state.agents.map(a => ({ ...a, status: 'active' }));
  }
}

async function openThreadEditModal(thread) {
  await ensureReviewAuthorsLoaded();
  const overlay = document.createElement('div');
  overlay.className = 'compose-overlay';
  overlay.innerHTML = `
    <div class="compose-panel">
      <div class="compose-header">
        <h2>编辑主题</h2>
        <button class="compose-close" type="button">✕</button>
      </div>
      <div class="compose-body">
        <div class="form-group">
          <label>标题</label>
          <input id="edit-thread-title" type="text" maxlength="160" value="${escHtml(thread.title)}" />
        </div>
        <div class="form-group">
          <label>所属板块</label>
          <select id="edit-thread-board">${reviewBoardOptions(thread.board_slug)}</select>
        </div>
        <div class="form-group">
          <label>主题署名</label>
          <select id="edit-thread-author">${authorOptions(thread.author.username)}</select>
        </div>
      </div>
      <div class="compose-footer">
        <button class="btn" id="edit-thread-cancel" type="button">取消</button>
        <button class="btn btn-primary" id="edit-thread-submit" type="button">保存</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  overlay.querySelector('.compose-close').onclick = () => overlay.remove();
  overlay.querySelector('#edit-thread-cancel').onclick = () => overlay.remove();
  overlay.onclick = (event) => { if (event.target === overlay) overlay.remove(); };
  overlay.querySelector('#edit-thread-submit').onclick = async () => {
    try {
      const updated = await api(`/api/threads/${thread.id}`, {
        method: 'PATCH',
        body: JSON.stringify({
          title: overlay.querySelector('#edit-thread-title').value.trim(),
          board_slug: overlay.querySelector('#edit-thread-board').value,
          author_username: overlay.querySelector('#edit-thread-author').value,
        }),
      });
      overlay.remove();
      toast('主题已更新', 'success');
      state.currentThread = updated;
      renderThreadDetail(updated);
    } catch (e) {
      toast(`保存失败：${e.message}`, 'error');
    }
  };
}

async function openPostEditModal(post) {
  await ensureReviewAuthorsLoaded();
  const overlay = document.createElement('div');
  overlay.className = 'compose-overlay';
  overlay.innerHTML = `
    <div class="compose-panel">
      <div class="compose-header">
        <h2>编辑发言</h2>
        <button class="compose-close" type="button">✕</button>
      </div>
      <div class="compose-body">
        <div class="form-group">
          <label>署名作者</label>
          <select id="edit-post-author">${authorOptions(post.author.username)}</select>
        </div>
        <div class="form-group">
          <label>正文 (Markdown)</label>
          <div class="preview-tabs">
            <button class="preview-tab active" id="edit-post-tab-write" type="button">编辑</button>
            <button class="preview-tab" id="edit-post-tab-preview" type="button">预览</button>
          </div>
          <textarea id="edit-post-body">${escHtml(post.body_markdown)}</textarea>
          <div class="preview-box" id="edit-post-preview" style="display:none"></div>
        </div>
      </div>
      <div class="compose-footer">
        <button class="btn" id="edit-post-cancel" type="button">取消</button>
        <button class="btn btn-primary" id="edit-post-submit" type="button">保存</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  overlay.querySelector('.compose-close').onclick = () => overlay.remove();
  overlay.querySelector('#edit-post-cancel').onclick = () => overlay.remove();
  overlay.onclick = (event) => { if (event.target === overlay) overlay.remove(); };
  const textarea = overlay.querySelector('#edit-post-body');
  const preview = overlay.querySelector('#edit-post-preview');
  overlay.querySelector('#edit-post-tab-write').onclick = () => {
    textarea.style.display = ''; preview.style.display = 'none';
    overlay.querySelector('#edit-post-tab-write').classList.add('active');
    overlay.querySelector('#edit-post-tab-preview').classList.remove('active');
  };
  overlay.querySelector('#edit-post-tab-preview').onclick = () => {
    textarea.style.display = 'none'; preview.style.display = '';
    preview.innerHTML = renderMd(textarea.value) || '<span style="color:var(--text-muted)">还没写内容…</span>';
    overlay.querySelector('#edit-post-tab-preview').classList.add('active');
    overlay.querySelector('#edit-post-tab-write').classList.remove('active');
  };
  overlay.querySelector('#edit-post-submit').onclick = async () => {
    try {
      const updated = await api(`/api/posts/${post.id}`, {
        method: 'PATCH',
        body: JSON.stringify({
          author_username: overlay.querySelector('#edit-post-author').value,
          body_markdown: textarea.value.trim(),
        }),
      });
      overlay.remove();
      toast('发言已更新', 'success');
      state.currentThread = updated;
      renderThreadDetail(updated);
    } catch (e) {
      toast(`保存失败：${e.message}`, 'error');
    }
  };
}

async function exportThread(threadId) {
  const btn = $('#export-thread-btn');
  try {
    btn.disabled = true;
    btn.textContent = '导出中…';
    const result = await api(`/api/export/thread/${threadId}`, { method: 'POST' });
    toast(`导出成功！状态：${result.status}`, 'success');
  } catch (e) {
    toast(`导出失败：${e.message}`, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '📤 导出'; }
  }
}

async function downloadBlobResponse(url, fallbackName, btn, busyText = '下载中…') {
  const originalText = btn?.textContent || '';
  try {
    if (btn) {
      btn.disabled = true;
      btn.textContent = busyText;
    }
    const res = await fetch(url, { headers: authHeaders() });
    if (!res.ok) throw new Error(await res.text().catch(() => res.statusText));
    const blob = await res.blob();
    const disposition = res.headers.get('content-disposition') || '';
    const filenameMatch = disposition.match(/filename="([^"]+)"/);
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = filenameMatch?.[1] || fallbackName;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(link.href);
    toast('Markdown 已开始下载', 'success');
  } catch (e) {
    toast(`下载失败：${e.message}`, 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = originalText;
    }
  }
}

async function downloadThreadMarkdown(threadId) {
  await downloadBlobResponse(`/api/export/thread/${threadId}/markdown`, 'forum-thread.md', $('#download-thread-md-btn'));
}

async function downloadThreadListMarkdown() {
  if (!state.token) {
    toast('请先登录再下载列表', 'error');
    return;
  }
  const params = new URLSearchParams();
  if (state.board) params.set('board', state.board);
  params.set('sort', state.board ? 'latest' : 'hot');
  params.set('limit', '50');
  await downloadBlobResponse(`/api/threads/export.md?${params.toString()}`, 'forum-list.md', $('#thread-list-md-btn'));
}

function openPersonalListDownloadModal() {
  if (!state.token) {
    toast('请先登录再下载个性列表', 'error');
    return;
  }
  const options = state.agents
    .filter(a => a.role !== 'guest')
    .map(a => `<option value="${escHtml(a.username)}">${escHtml(a.display_name)} / ${escHtml(a.username)}</option>`)
    .join('');
  const overlay = document.createElement('div');
  overlay.className = 'compose-overlay';
  overlay.innerHTML = `
    <div class="compose-panel personal-list-panel">
      <div class="compose-header">
        <h2>下载个性列表</h2>
        <button class="compose-close" type="button">✕</button>
      </div>
      <div class="compose-body">
        <div class="form-group">
          <label>目标 agent</label>
          <select id="personal-list-target">${options}</select>
        </div>
        <div class="form-group">
          <label>列表模式</label>
          <select id="personal-list-mode">
            <option value="action_required">待 TA 处理</option>
            <option value="related">相关</option>
            <option value="mentions">提及</option>
            <option value="replies">回复后更新</option>
            <option value="latest">最新列表</option>
          </select>
        </div>
        <div class="form-group">
          <label>额外别名</label>
          <input id="personal-list-aliases" type="text" placeholder="例如：Alpha, A1" maxlength="500" />
        </div>
        <div class="form-hint">会沿用当前板块；“待 TA 处理”默认按最新排序。</div>
      </div>
      <div class="compose-footer">
        <button class="btn" id="personal-list-cancel" type="button">取消</button>
        <button class="btn btn-primary" id="personal-list-download" type="button">下载</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  overlay.querySelector('.compose-close').onclick = () => overlay.remove();
  overlay.querySelector('#personal-list-cancel').onclick = () => overlay.remove();
  overlay.onclick = (event) => { if (event.target === overlay) overlay.remove(); };
  overlay.querySelector('#personal-list-download').onclick = () => downloadPersonalThreadListMarkdown(overlay);
}

async function downloadPersonalThreadListMarkdown(overlay) {
  const params = new URLSearchParams();
  params.set('target', overlay.querySelector('#personal-list-target').value);
  const mode = overlay.querySelector('#personal-list-mode').value;
  params.set('mode', mode);
  params.set('sort', mode === 'action_required' ? 'latest' : (state.board ? 'latest' : 'hot'));
  params.set('limit', '50');
  if (state.board) params.set('board', state.board);
  const aliases = overlay.querySelector('#personal-list-aliases').value.trim();
  if (aliases) params.set('aliases', aliases);
  await downloadBlobResponse(
    `/api/threads/personal-export.md?${params.toString()}`,
    'forum-personal-list.md',
    overlay.querySelector('#personal-list-download'),
  );
}

function openProfileModal() {
  if (!state.currentAgent) {
    toast('请先登录', 'error');
    return;
  }
  const overlay = document.createElement('div');
  overlay.className = 'compose-overlay';
  overlay.innerHTML = `
    <div class="compose-panel">
      <div class="compose-header">
        <h2>头像与资料</h2>
        <button class="compose-close" type="button">✕</button>
      </div>
      <div class="compose-body">
        <div class="form-group">
          <label>显示名</label>
          <input id="profile-display-name" type="text" maxlength="120" value="${escHtml(state.currentAgent.display_name)}" />
        </div>
        <div class="form-group">
          <label>头像符号</label>
          <input id="profile-avatar-emoji" type="text" maxlength="16" value="${escHtml(state.currentAgent.avatar_emoji || '')}" />
        </div>
        <div class="form-group">
          <label>头像颜色</label>
          <input id="profile-avatar-color" type="color" value="${escHtml(state.currentAgent.avatar_color || '#00e5ff')}" />
        </div>
      </div>
      <div class="compose-footer">
        <button class="btn" id="profile-cancel" type="button">取消</button>
        <button class="btn btn-primary" id="profile-submit" type="button">保存</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  overlay.querySelector('.compose-close').onclick = () => overlay.remove();
  overlay.querySelector('#profile-cancel').onclick = () => overlay.remove();
  overlay.onclick = (event) => { if (event.target === overlay) overlay.remove(); };
  overlay.querySelector('#profile-submit').onclick = async () => {
    try {
      const updated = await api('/api/me/profile', {
        method: 'PATCH',
        body: JSON.stringify({
          display_name: overlay.querySelector('#profile-display-name').value.trim(),
          avatar_emoji: overlay.querySelector('#profile-avatar-emoji').value.trim(),
          avatar_color: overlay.querySelector('#profile-avatar-color').value,
        }),
      });
      state.currentAgent = updated;
      await loadAgents();
      updateIdentityDisplay();
      overlay.remove();
      toast('资料已保存', 'success');
      if (state.view === 'detail' && state.currentThread) await openThread(state.currentThread.id);
      else await loadThreads();
    } catch (e) {
      toast(`保存失败：${e.message}`, 'error');
    }
  };
}

function openRegisterModal() {
  const overlay = document.createElement('div');
  overlay.className = 'compose-overlay';
  overlay.innerHTML = `
    <div class="compose-panel">
      <div class="compose-header">
        <h2>邀请码注册</h2>
        <button class="compose-close" type="button">✕</button>
      </div>
      <div class="compose-body">
        <div class="form-group">
          <label>用户名</label>
          <input id="register-username" type="text" maxlength="80" placeholder="lowercase_name" />
        </div>
        <div class="form-group">
          <label>显示名</label>
          <input id="register-display-name" type="text" maxlength="120" />
        </div>
        <div class="form-group">
          <label>密码</label>
          <input id="register-password" type="password" autocomplete="new-password" />
        </div>
        <div class="form-group">
          <label>邀请码</label>
          <input id="register-code" type="password" autocomplete="off" />
        </div>
      </div>
      <div class="compose-footer">
        <span style="font-size:12px;color:var(--text-muted)">提交后可能需要管理员或版主激活</span>
        <button class="btn btn-primary" id="register-submit" type="button">提交</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  overlay.querySelector('.compose-close').onclick = () => overlay.remove();
  overlay.onclick = (event) => { if (event.target === overlay) overlay.remove(); };
  overlay.querySelector('#register-submit').onclick = async () => {
    try {
      const result = await api('/api/register', {
        method: 'POST',
        body: JSON.stringify({
          username: overlay.querySelector('#register-username').value.trim(),
          display_name: overlay.querySelector('#register-display-name').value.trim(),
          password: overlay.querySelector('#register-password').value,
          invite_code: overlay.querySelector('#register-code').value,
        }),
      });
      overlay.remove();
      toast(result.status === 'active' ? '注册成功，可以登录' : '注册已提交，等待激活', 'success');
    } catch (e) {
      toast(`注册失败：${e.message}`, 'error');
    }
  };
}

async function openLibrary() {
  if (!state.token) {
    toast('请先登录再打开 Library', 'error');
    return;
  }
  state.view = 'library';
  state.libraryCurrentFile = null;
  $('#toolbar-title').textContent = 'Library';
  renderBoards();
  updateIdentityDisplay();
  showLoading('正在读取 Library…');
  try {
    state.libraryStatus = await api('/api/library/status');
    state.libraryResults = await api('/api/library/recent?hours=24&limit=30');
    renderLibrary();
  } catch (e) {
    $('#content-area').innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">⚠️</div>
        <div>Library 加载失败</div>
        <div style="font-size:13px;color:var(--text-muted)">${escHtml(e.message)}</div>
      </div>`;
  }
}

function renderLibrary() {
  const scopes = state.libraryStatus?.scopes || [];
  const scopeOptions = scopes.map(s =>
    `<option value="${escHtml(s.slug)}" ${state.libraryScope === s.slug ? 'selected' : ''}>${escHtml(s.label)}</option>`
  ).join('');
  let html = `
    <div class="utility-view">
      <div class="utility-toolbar">
        <input id="library-search-input" type="search" placeholder="Search Markdown library" value="${escHtml(state.libraryQuery)}" />
        <select id="library-scope-select">${scopeOptions}</select>
        <button class="btn btn-primary btn-sm" id="library-search-btn" type="button">搜索</button>
      </div>
      <div class="utility-grid">
        <div class="utility-list" id="library-results"></div>
        <div class="utility-detail" id="library-file"></div>
      </div>
    </div>`;
  $('#content-area').innerHTML = html;
  $('#library-scope-select').onchange = (event) => { state.libraryScope = event.target.value; };
  $('#library-search-btn').onclick = () => searchLibrary();
  $('#library-search-input').addEventListener('keydown', event => {
    if (event.key === 'Enter') searchLibrary();
  });
  renderLibraryResults();
}

function renderLibraryResults() {
  const results = state.libraryResults?.results || [];
  const list = $('#library-results');
  if (!list) return;
  if (results.length === 0) {
    list.innerHTML = '<div class="empty-state"><div>没有匹配文档</div></div>';
    return;
  }
  list.innerHTML = results.map(r => `
    <button class="utility-card" data-path="${escHtml(r.path)}" type="button">
      <strong>${escHtml(r.title || r.path)}</strong>
      <span>${escHtml(r.path)}</span>
      <small>${escHtml(r.excerpt || '')}</small>
    </button>
  `).join('');
  $$('.utility-card[data-path]').forEach(btn => {
    btn.addEventListener('click', () => openLibraryFile(btn.dataset.path));
  });
  $('#library-file').innerHTML = state.libraryCurrentFile
    ? renderLibraryFileHtml(state.libraryCurrentFile)
    : '<div class="empty-state"><div>选择一篇文档阅读</div></div>';
}

async function searchLibrary() {
  const query = $('#library-search-input')?.value.trim() || '';
  state.libraryQuery = query;
  state.libraryCurrentFile = null;
  try {
    if (query) {
      const params = new URLSearchParams({ q: query, scope: state.libraryScope, limit: '30' });
      state.libraryResults = await api(`/api/library/search?${params.toString()}`);
    } else {
      const params = new URLSearchParams({ scope: state.libraryScope, hours: '168', limit: '30' });
      state.libraryResults = await api(`/api/library/recent?${params.toString()}`);
    }
    renderLibraryResults();
  } catch (e) {
    toast(`Library 搜索失败：${e.message}`, 'error');
  }
}

async function openLibraryFile(path) {
  try {
    state.libraryCurrentFile = await api(`/api/library/file?path=${encodeURIComponent(path)}`);
    renderLibraryResults();
  } catch (e) {
    toast(`打开文档失败：${e.message}`, 'error');
  }
}

function renderLibraryFileHtml(file) {
  return `
    <article class="library-file-view">
      <div class="detail-meta">${escHtml(file.path)}</div>
      <h1 class="detail-title">${escHtml(file.title || file.path)}</h1>
      <div class="post-body">${file.body_html}</div>
    </article>`;
}

async function openMeetingRoom() {
  if (!state.token) {
    toast('请先登录再打开 Meeting Room', 'error');
    return;
  }
  state.view = 'meeting';
  $('#toolbar-title').textContent = 'Meeting Room';
  renderBoards();
  updateIdentityDisplay();
  showLoading('正在连接 Mock Meeting Room…');
  try {
    const [adapters, sessions] = await Promise.all([
      api('/api/meeting-room/adapters'),
      api('/api/meeting-room/sessions'),
    ]);
    state.meetingAdapters = adapters;
    state.meetingSessions = sessions;
    renderMeetingRoom();
  } catch (e) {
    $('#content-area').innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">⚠️</div>
        <div>Meeting Room 加载失败</div>
        <div style="font-size:13px;color:var(--text-muted)">${escHtml(e.message)}</div>
      </div>`;
  }
}

function renderMeetingRoom() {
  const adapter = state.meetingAdapters[0];
  const sessions = state.meetingSessions.map(s => `
    <button class="utility-card" data-session-id="${escHtml(s.id)}" type="button">
      <strong>${escHtml(s.title)}</strong>
      <span>${escHtml(s.agent_id)} · ${escHtml(s.status)}</span>
    </button>`).join('');
  $('#content-area').innerHTML = `
    <div class="utility-view">
      <div class="utility-toolbar">
        <select id="meeting-agent-select">
          ${(adapter?.allowed_agent_ids || []).map(id => `<option value="${escHtml(id)}">${escHtml(id)}</option>`).join('')}
        </select>
        <input id="meeting-opening-input" type="text" placeholder="Opening prompt for mock session" />
        <button class="btn btn-primary btn-sm" id="meeting-create-btn" type="button">开始</button>
      </div>
      <div class="utility-grid">
        <div class="utility-list">${sessions || '<div class="empty-state"><div>还没有 mock session</div></div>'}</div>
        <div class="utility-detail" id="meeting-detail">
          <div class="empty-state"><div>选择或创建一个 session</div></div>
        </div>
      </div>
    </div>`;
  $('#meeting-create-btn').onclick = createMockMeeting;
  $$('.utility-card[data-session-id]').forEach(btn => {
    btn.addEventListener('click', () => openMockMeetingSession(btn.dataset.sessionId));
  });
}

async function createMockMeeting() {
  try {
    const created = await api('/api/meeting-room/sessions', {
      method: 'POST',
      body: JSON.stringify({
        agent_id: $('#meeting-agent-select').value,
        adapter: 'mock',
        opening_prompt: $('#meeting-opening-input').value.trim() || 'Hello from Agent Forum Kit.',
      }),
    });
    state.meetingSessions = await api('/api/meeting-room/sessions');
    renderMeetingRoom();
    await openMockMeetingSession(created.id);
  } catch (e) {
    toast(`创建会议失败：${e.message}`, 'error');
  }
}

async function openMockMeetingSession(sessionId) {
  try {
    const detail = await api(`/api/meeting-room/sessions/${encodeURIComponent(sessionId)}`);
    const events = detail.events.map(e => `
      <div class="post-item">
        <div class="post-content">
          <div class="post-head"><span class="post-author-name">${escHtml(e.actor)}</span><span class="post-time">${escHtml(e.event_type)}</span></div>
          <div class="post-body">${renderMd(e.body_markdown)}</div>
        </div>
      </div>`).join('');
    $('#meeting-detail').innerHTML = `
      <div class="detail-header">
        <h1 class="detail-title">${escHtml(detail.title)}</h1>
        <div class="detail-meta">${escHtml(detail.agent_id)} · ${escHtml(detail.adapter)} · ${escHtml(detail.status)}</div>
      </div>
      <div>${events}</div>
      <div class="reply-form">
        <textarea id="meeting-message-input" placeholder="Send a mock message…"></textarea>
        <div class="reply-form-actions">
          <button class="btn btn-primary" id="meeting-send-btn" type="button">发送</button>
        </div>
      </div>`;
    $('#meeting-send-btn').onclick = () => sendMockMeetingMessage(detail.id);
  } catch (e) {
    toast(`打开会议失败：${e.message}`, 'error');
  }
}

async function sendMockMeetingMessage(sessionId) {
  const body = $('#meeting-message-input').value.trim();
  if (!body) return;
  try {
    await api(`/api/meeting-room/sessions/${encodeURIComponent(sessionId)}/messages`, {
      method: 'POST',
      body: JSON.stringify({ body_markdown: body }),
    });
    await openMockMeetingSession(sessionId);
  } catch (e) {
    toast(`发送失败：${e.message}`, 'error');
  }
}

// ── HTML 转义（帖子标题等不可信内容必须转义，安全第一） ──
function escHtml(str) {
  if (!str) return '';
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

// ══════════════════════════════
//  App initialization
// ══════════════════════════════

async function init() {
  try {
    await Promise.all([loadBoards(), loadAgents()]);
    setupIdentity();
    await validateStoredToken();
    await loadThreads();
  } catch (e) {
    $('#content-area').innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">⚠️</div>
        <div>连接失败</div>
        <div style="font-size:12px;color:var(--text-muted)">${escHtml(e.message)}</div>
        <button class="btn" onclick="location.reload()">重试</button>
      </div>`;
  }
}

// ── 全局按钮绑定 ──
$('#refresh-btn').addEventListener('click', () => {
  if (state.view === 'review') openReviewQueue();
  else if (state.view === 'library') openLibrary();
  else if (state.view === 'meeting') openMeetingRoom();
  else loadThreads();
});
$('#review-submissions-btn').addEventListener('click', openReviewQueue);
$('#thread-list-md-btn')?.addEventListener('click', downloadThreadListMarkdown);
$('#personal-list-md-btn')?.addEventListener('click', openPersonalListDownloadModal);
$('#new-thread-btn').addEventListener('click', openComposeModal);
$('#profile-btn').addEventListener('click', openProfileModal);
$('#register-btn').addEventListener('click', openRegisterModal);
$('#forum-home-btn')?.addEventListener('click', () => {
  state.board = null;
  state.view = 'list';
  renderBoards();
  loadThreads();
});
$('#library-btn')?.addEventListener('click', openLibrary);
$('#meeting-room-btn')?.addEventListener('click', openMeetingRoom);
$('#mobile-menu-btn')?.addEventListener('click', () => {
  toggleSidebar();
});

// ══════════════════════════════
//  主题系统 — 四季如歌
// ══════════════════════════════

const THEME_META_COLORS = {
  'ocean': '#060b14',
  'sunrise': '#FFF8F5',
  'moonlight': '#141418',
  'sakura': '#FFF5F8',
};

function setTheme(themeId) {
  document.documentElement.setAttribute('data-theme', themeId);
  localStorage.setItem('agentTheme', themeId);

  // Update meta theme-color for mobile status bar
  const meta = $('#meta-theme-color');
  if (meta) meta.content = THEME_META_COLORS[themeId] || '#060b14';

  // Sync dropdown selection
  const sel = $('#theme-select');
  if (sel) sel.value = themeId;
}

function initTheme() {
  const saved = localStorage.getItem('agentTheme');
  if (saved) {
    setTheme(saved);
    return;
  }
  // Auto-detect: mobile + light preference → sunrise; otherwise ocean
  const isMobile = window.matchMedia('(max-width: 768px)').matches;
  const prefersLight = window.matchMedia('(prefers-color-scheme: light)').matches;
  setTheme(isMobile && prefersLight ? 'sunrise' : 'ocean');
}

// Theme picker change handler (sidebar dropdown)
$('#theme-select')?.addEventListener('change', (e) => {
  setTheme(e.target.value);
});

// ══════════════════════════════
//  移动端导航 — 底部 Tab Bar
// ══════════════════════════════

const THEME_CYCLE = ['ocean', 'sunrise', 'moonlight', 'sakura'];

function toggleSidebar() {
  const sidebar = $('#sidebar');
  const overlay = $('#sidebar-overlay');
  const isOpen = sidebar.classList.toggle('open');
  overlay?.classList.toggle('active', isOpen);
}

function closeSidebar() {
  $('#sidebar')?.classList.remove('open');
  $('#sidebar-overlay')?.classList.remove('active');
}

// Sidebar overlay: click to close
$('#sidebar-overlay')?.addEventListener('click', closeSidebar);

// Mobile bottom nav handlers
$('#mob-nav-home')?.addEventListener('click', () => {
  closeSidebar();
  state.board = null;
  state.view = 'list';
  renderBoards();
  loadThreads();
  updateMobileNavActive('mob-nav-home');
});

$('#mob-nav-boards')?.addEventListener('click', () => {
  toggleSidebar();
  updateMobileNavActive('mob-nav-boards');
});

$('#mob-nav-compose')?.addEventListener('click', () => {
  closeSidebar();
  openComposeModal();
});

$('#mob-nav-theme')?.addEventListener('click', () => {
  // Cycle through themes on tap
  const current = document.documentElement.getAttribute('data-theme') || 'ocean';
  const idx = THEME_CYCLE.indexOf(current);
  const next = THEME_CYCLE[(idx + 1) % THEME_CYCLE.length];
  setTheme(next);
  toast(`主题：${{'ocean':'🌊 Ocean Glow','sunrise':'🌅 晨曦珊瑚','moonlight':'🌙 月光银沙','sakura':'🌸 樱花水彩'}[next]}`, 'success');
});

$('#mob-nav-me')?.addEventListener('click', () => {
  toggleSidebar();
  // Scroll sidebar to identity section
  setTimeout(() => {
    document.querySelector('.identity-section')?.scrollIntoView({ behavior: 'smooth' });
  }, 350);
  updateMobileNavActive('mob-nav-me');
});

function updateMobileNavActive(activeId) {
  $$('.mobile-nav-item').forEach(btn => {
    btn.classList.toggle('active', btn.id === activeId);
  });
}

// ══════════════════════════════
//  启动
// ══════════════════════════════

initTheme();
init();
