/* AI Office mobile client — talks only to the original server's real APIs. */
(function () {
  'use strict';

  var SPECIALISTS = [
    { id: 'opencode-ceo',        name: 'CEO / Manager', emoji: '👔', role: 'Delegates to specialists and delivers the final report', x: 50, y: 26 },
    { id: 'opencode-programmer', name: 'Programmer',    emoji: '💻', role: 'Writes, edits and verifies real code',               x: 18, y: 48 },
    { id: 'opencode-researcher', name: 'Researcher',    emoji: '🔎', role: 'Searches sources and returns evidence',             x: 38, y: 62 },
    { id: 'opencode-designer',   name: 'Designer',      emoji: '🎨', role: 'Designs mobile-first interfaces',                  x: 62, y: 62 },
    { id: 'opencode-writer',     name: 'Writer',        emoji: '✍️', role: 'Writes documentation and clear copy',              x: 82, y: 48 },
    { id: 'opencode-analyst',    name: 'Analyst',       emoji: '📊', role: 'Analyses options, risks and trade-offs',           x: 50, y: 78 }
  ];

  var state = {
    agents: [], status: {}, chatAgent: '', chatController: null, busy: false,
    projects: [], project: null, pendingWorkflow: null, zoom: 1, panX: 0, panY: 0,
    toastTimer: null
  };

  var $ = function (id) { return document.getElementById(id); };

  function toast(message, isError) {
    var el = $('toast');
    el.textContent = message;
    el.className = 'toast show' + (isError ? ' error' : '');
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(function () { el.className = 'toast'; }, 3200);
  }

  async function api(path, options) {
    options = options || {};
    var init = { method: options.method || 'GET', headers: {}, signal: options.signal };
    if (options.body !== undefined) {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(options.body);
    }
    var response = await fetch(path, init);
    var data;
    try { data = await response.json(); }
    catch (e) { throw new Error('Server returned an invalid response (' + response.status + ')'); }
    if (!response.ok || data.ok === false) throw new Error(data.error || ('Request failed (' + response.status + ')'));
    return data;
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
    });
  }

  // ── Navigation ────────────────────────────────────────────────────────
  function switchView(name) {
    var views = document.querySelectorAll('.view');
    var navs = document.querySelectorAll('.nav-item');
    views.forEach(function (v) { v.classList.toggle('active', v.id === 'view-' + name); });
    navs.forEach(function (n) { n.classList.toggle('active', n.dataset.view === name); });
    if (name === 'tasks') refreshProjects();
    if (name === 'agents') renderAgentCards();
    if (name === 'settings') refreshSettings();
    if (name === 'chat' && !state.chatAgent) loadChatHistory();
  }

  $('bottomNav').addEventListener('click', function (event) {
    var btn = event.target.closest('.nav-item');
    if (btn) switchView(btn.dataset.view);
  });

  // ── Agents / office ───────────────────────────────────────────────────
  function agentStatus(id) {
    var key = id.replace('opencode-', '');
    var match = (state.status.agents || []).find(function (a) {
      return a.id === id || a.providerAgentId === key || a.profile === key;
    });
    if (!match) return 'connected';
    var s = String(match.connectionState || '');
    if (s === 'connected' || s === 'online') return 'connected';
    return 'offline';
  }

  function renderOffice() {
    var host = $('officeAgents');
    host.innerHTML = SPECIALISTS.map(function (a) {
      var st = agentStatus(a.id);
      return '<button class="office-agent ' + (st === 'offline' ? 'offline' : '') + '" data-agent="' + a.id + '" style="left:' + a.x + '%;top:' + a.y + '%">' +
        '<span class="avatar">' + a.emoji + '</span><span class="name">' + escapeHtml(a.name) + '</span><span class="mini-dot"></span></button>';
    }).join('');
    host.querySelectorAll('.office-agent').forEach(function (btn) {
      btn.addEventListener('click', function () {
        if (officeDragged) return;
        state.chatAgent = btn.dataset.agent;
        $('chatAgent').value = state.chatAgent;
        switchView('chat');
        loadChatHistory();
      });
    });
    $('officeLegend').innerHTML = SPECIALISTS.map(function (a) {
      return '<span class="legend-chip">' + a.emoji + ' ' + escapeHtml(a.name.replace(' / Manager', '')) + '</span>';
    }).join('');
  }

  function applyTransform() {
    $('officeWorld').style.transform = 'translate(' + state.panX + 'px,' + state.panY + 'px) scale(' + state.zoom + ')';
    $('zoomLabel').textContent = Math.round(state.zoom * 100) + '%';
  }
  function setZoom(next) { state.zoom = Math.max(0.6, Math.min(2.2, next)); applyTransform(); }
  $('zoomIn').addEventListener('click', function () { setZoom(state.zoom + 0.15); });
  $('zoomOut').addEventListener('click', function () { setZoom(state.zoom - 0.15); });
  $('officeRecenter').addEventListener('click', function () {
    state.zoom = 1; state.panX = 0; state.panY = 0; applyTransform();
  });

  var officeDrag = null, officeDragged = false, pinch = null;
  var stage = $('officeStage');
  stage.addEventListener('touchstart', function (e) {
    if (e.touches.length === 2) {
      var dx = e.touches[0].clientX - e.touches[1].clientX;
      var dy = e.touches[0].clientY - e.touches[1].clientY;
      pinch = { dist: Math.hypot(dx, dy), zoom: state.zoom };
      officeDrag = null; return;
    }
    if (e.touches.length === 1) {
      officeDragged = false;
      officeDrag = { x: e.touches[0].clientX - state.panX, y: e.touches[0].clientY - state.panY };
    }
  }, { passive: true });
  stage.addEventListener('touchmove', function (e) {
    if (e.touches.length === 2 && pinch) {
      var dx = e.touches[0].clientX - e.touches[1].clientX;
      var dy = e.touches[0].clientY - e.touches[1].clientY;
      setZoom(pinch.zoom * (Math.hypot(dx, dy) / Math.max(1, pinch.dist)));
      e.preventDefault();
    } else if (e.touches.length === 1 && officeDrag) {
      var nx = e.touches[0].clientX - officeDrag.x;
      var ny = e.touches[0].clientY - officeDrag.y;
      if (Math.abs(nx - state.panX) + Math.abs(ny - state.panY) > 4) officeDragged = true;
      state.panX = nx; state.panY = ny; applyTransform();
      e.preventDefault();
    }
  }, { passive: false });
  stage.addEventListener('touchend', function () { officeDrag = null; pinch = null; setTimeout(function () { officeDragged = false; }, 120); });
  stage.addEventListener('pointerdown', function (e) {
    if (e.pointerType !== 'mouse') return;
    officeDrag = { x: e.clientX - state.panX, y: e.clientY - state.panY };
  });
  stage.addEventListener('pointermove', function (e) {
    if (!officeDrag || e.pointerType !== 'mouse' || !e.buttons) return;
    state.panX = e.clientX - officeDrag.x; state.panY = e.clientY - officeDrag.y; applyTransform();
  });

  function renderAgentCards() {
    var host = $('agentCards');
    host.innerHTML = SPECIALISTS.map(function (a) {
      var st = agentStatus(a.id);
      return '<button class="agent-card" data-agent="' + a.id + '">' +
        '<span class="avatar">' + a.emoji + '</span>' +
        '<span class="meta"><strong>' + escapeHtml(a.name) + '</strong><small>' + escapeHtml(a.role) + '</small></span>' +
        '<span class="state ' + (st === 'offline' ? 'offline' : '') + '">' + (st === 'offline' ? 'offline' : 'online') + '</span></button>';
    }).join('');
    host.querySelectorAll('.agent-card').forEach(function (btn) {
      btn.addEventListener('click', function () {
        state.chatAgent = btn.dataset.agent;
        $('chatAgent').value = state.chatAgent;
        switchView('chat');
        loadChatHistory();
      });
    });
    $('agentsFootnote').textContent = 'These are real OpenCode agents with their own instructions. The CEO can delegate work to the other five using OpenCode subagents. Your My Virtual Office demo license shows up to three agents in its own roster; that limit is not bypassed here.';
  }

  // ── Chat ──────────────────────────────────────────────────────────────
  function populateAgentSelects() {
    var chat = $('chatAgent'), task = $('taskAgent');
    var html = SPECIALISTS.map(function (a) {
      return '<option value="' + a.id + '">' + a.emoji + ' ' + escapeHtml(a.name) + '</option>';
    }).join('');
    chat.innerHTML = html; task.innerHTML = html;
    if (!state.chatAgent) state.chatAgent = SPECIALISTS[0].id;
    chat.value = state.chatAgent;
    task.value = 'opencode-ceo';
  }

  function addMessage(role, text, agentId, retryText) {
    var wrap = document.createElement('div');
    wrap.className = 'msg ' + role;
    if (role === 'assistant') {
      var a = SPECIALISTS.find(function (s) { return s.id === agentId; });
      wrap.innerHTML = '<span class="agent-tag">' + escapeHtml(a ? a.name : 'Agent') + '</span>' + escapeHtml(text);
    } else if (role === 'error') {
      wrap.innerHTML = escapeHtml(text) + (retryText !== undefined ? '<button type="button">Retry</button>' : '');
      if (retryText !== undefined) wrap.querySelector('button').addEventListener('click', function () { sendMessage(retryText); });
    } else {
      wrap.textContent = text;
    }
    $('chatMessages').appendChild(wrap);
    $('chatMessages').scrollTop = $('chatMessages').scrollHeight;
  }

  async function loadChatHistory() {
    var agent = state.chatAgent;
    if (!agent) return;
    var box = $('chatMessages');
    box.innerHTML = '<div class="chat-empty">Loading conversation…</div>';
    try {
      var data = await api('/api/provider-history?agentId=' + encodeURIComponent(agent));
      box.innerHTML = '';
      var messages = data.messages || [];
      if (!messages.length) box.innerHTML = '<div class="chat-empty">No messages yet. Say hello to ' + escapeHtml(agent.replace('opencode-', '')) + '.</div>';
      messages.forEach(function (m) {
        var role = m.role === 'user' ? 'user' : (m.role === 'assistant' ? 'assistant' : null);
        if (role) addMessage(role, m.text || '', agent);
      });
      $('chatNote').textContent = messages.length + ' saved message(s) on this device · session ' + (data.activeSessionId || 'new');
    } catch (err) {
      box.innerHTML = '';
      addMessage('error', 'Could not load history: ' + err.message);
    }
  }

  $('chatAgent').addEventListener('change', function () {
    state.chatAgent = this.value; loadChatHistory();
  });
  $('chatNew').addEventListener('click', function () {
    $('chatMessages').innerHTML = '<div class="chat-empty">New conversation. Send a message to begin.</div>';
    $('chatNote').textContent = 'Messages and replies are saved on this device.';
    $('chatInput').focus();
  });
  $('chatInput').addEventListener('input', function () {
    this.style.height = 'auto'; this.style.height = Math.min(120, this.scrollHeight) + 'px';
  });

  async function sendMessage(text) {
    if (state.busy) return;
    text = String(text || '').trim();
    if (!text) return;
    var agent = state.chatAgent;
    var container = $('chatMessages');
    var empty = container.querySelector('.chat-empty');
    if (empty) empty.remove();
    addMessage('user', text);
    $('chatInput').value = ''; $('chatInput').style.height = 'auto';
    state.busy = true;
    $('chatSend').classList.add('hidden');
    $('chatStop').classList.remove('hidden');
    $('chatTyping').classList.remove('hidden');
    $('chatTyping').lastChild.textContent = ' working…';
    state.chatController = new AbortController();
    try {
      var data = await api('/api/provider-chat', {
        method: 'POST', signal: state.chatController.signal,
        body: { agentId: agent, message: text, fromType: 'human', fromDisplayName: 'User', sourceApp: 'virtual-office', sourceSurface: 'mobile' }
      });
      addMessage('assistant', data.reply || '(empty response)', agent);
      $('chatNote').textContent = 'Saved · session ' + (data.sessionId || 'unknown') +
        (data.tools && data.tools.length ? ' · ' + data.tools.length + ' tool call(s)' : '');
    } catch (err) {
      if (err.name === 'AbortError') addMessage('error', 'Stopped waiting. The agent may still finish in the background.');
      else addMessage('error', 'Error: ' + err.message, null, text);
    } finally {
      state.busy = false; state.chatController = null;
      $('chatSend').classList.remove('hidden');
      $('chatStop').classList.add('hidden');
      $('chatTyping').classList.add('hidden');
    }
  }

  $('chatForm').addEventListener('submit', function (e) {
    e.preventDefault(); sendMessage($('chatInput').value);
  });
  $('chatStop').addEventListener('click', async function () {
    if (!state.busy) return;
    toast('Stopping ' + state.chatAgent.replace('opencode-', '') + '…');
    try {
      await api('/api/provider-interrupt', { method: 'POST', body: { agentId: state.chatAgent } });
    } catch (err) { /* the abort below still stops waiting */ }
    if (state.chatController) state.chatController.abort();
  });

  // ── Tasks / projects / workflow ───────────────────────────────────────
  $('taskTabs').addEventListener('click', function (e) {
    var btn = e.target.closest('.seg'); if (!btn) return;
    document.querySelectorAll('.seg').forEach(function (s) { s.classList.toggle('active', s === btn); });
    $('taskPanelProjects').classList.toggle('hidden', btn.dataset.taskTab !== 'projects');
    $('taskPanelNew').classList.toggle('hidden', btn.dataset.taskTab !== 'new');
  });
  $('refreshTasks').addEventListener('click', refreshProjects);

  async function refreshProjects() {
    var host = $('projectList');
    host.innerHTML = '<div class="empty-state">Loading projects…</div>';
    try {
      var data = await api('/api/projects');
      state.projects = data.projects || [];
      if (!state.projects.length) {
        host.innerHTML = '<div class="empty-state">No projects yet. Create one in the “New task” tab.</div>';
      } else {
        var out = '';
        for (var i = 0; i < state.projects.length; i++) {
          var p = await api('/api/projects/' + encodeURIComponent(state.projects[i].id));
          out += projectHtml(p.project || p);
        }
        host.innerHTML = out;
        wireProjectButtons(host);
      }
      var sel = $('taskProject');
      sel.innerHTML = state.projects.map(function (p) {
        return '<option value="' + p.id + '">' + escapeHtml(p.title) + '</option>';
      }).join('');
    } catch (err) {
      host.innerHTML = '';
      var e = document.createElement('div'); e.className = 'msg error'; e.textContent = 'Error: ' + err.message;
      host.appendChild(e);
    }
  }

  function projectHtml(p) {
    var columns = p.columns || [];
    var tasks = p.tasks || [];
    var active = !!p.workflowActive;
    var cards = tasks.map(function (t) {
      var col = columns.find(function (c) { c.id === t.columnId });
      var outputs = (t.comments || []).filter(function (c) {
        return /response|summary|complete|failed|error/i.test(c.text || '');
      });
      var out = outputs.length ? '<div class="task-out">' + escapeHtml(outputs.map(function (c) { return c.text; }).join('\n\n')) + '</div>' : '';
      return '<div class="task-row"><div class="task-title"><span>' + escapeHtml(t.title) + '</span>' +
        '<span class="task-col">' + escapeHtml(col ? col.title : 'Task') + '</span></div>' + out + '</div>';
    }).join('');
    return '<article class="project-card"><div class="project-top"><div><h3>' + escapeHtml(p.title) + '</h3>' +
      '<small>' + tasks.length + ' task(s) · ' + escapeHtml(p.status || 'active') + '</small></div>' +
      '<span class="workflow-pill ' + (active ? 'running' : '') + '">' + (active ? 'Running' : 'Idle') + '</span></div>' +
      (cards || '<div class="task-row" style="color:var(--muted);font-size:12px">No tasks yet.</div>') +
      '<div class="task-row"><div class="task-actions">' +
      (active
        ? '<button class="mini-btn" data-stop="' + p.id + '">Stop workflow</button>'
        : '<button class="mini-btn primary" data-start="' + p.id + '">Run workflow</button>') +
      '<button class="mini-btn" data-status="' + p.id + '">Status</button></div></div></article>';
  }

  function wireProjectButtons(host) {
    host.querySelectorAll('[data-start]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var p = state.projects.find(function (x) { return x.id === btn.dataset.start; });
        approval('Run the workflow for “' + (p ? p.title : 'this project') + '”?',
          'The workflow may create, edit or delete files through the assigned AI agent. Review its output before trusting it.',
          function () { startWorkflow(btn.dataset.start); });
      });
    });
    host.querySelectorAll('[data-stop]').forEach(function (btn) {
      btn.addEventListener('click', async function () {
        try { await api('/api/projects/' + encodeURIComponent(btn.dataset.stop) + '/workflow/stop', { method: 'POST', body: {} }); toast('Workflow stop requested'); }
        catch (err) { toast(err.message, true); }
        refreshProjects();
      });
    });
    host.querySelectorAll('[data-status]').forEach(function (btn) {
      btn.addEventListener('click', async function () {
        try {
          var s = await api('/api/projects/' + encodeURIComponent(btn.dataset.status) + '/workflow/status');
          toast('Phase: ' + (s.phase || 'idle') + ' · active: ' + !!s.active + (s.error ? ' · ' + s.error : ''));
        } catch (err) { toast(err.message, true); }
      });
    });
  }

  function approval(title, detail, onConfirm) {
    $('approvalText').textContent = title + ' ' + detail;
    $('approvalCard').classList.remove('hidden');
    state.pendingWorkflow = onConfirm;
    $('approvalCard').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
  $('approvalCancel').addEventListener('click', function () {
    $('approvalCard').classList.add('hidden'); state.pendingWorkflow = null;
  });
  $('approvalConfirm').addEventListener('click', function () {
    $('approvalCard').classList.add('hidden');
    var fn = state.pendingWorkflow; state.pendingWorkflow = null;
    if (fn) fn();
  });

  async function startWorkflow(id) {
    try {
      await api('/api/projects/' + encodeURIComponent(id) + '/workflow/start', { method: 'POST', body: { autoMode: false } });
      toast('Workflow started');
      refreshProjects();
      var poll = setInterval(async function () {
        try {
          var s = await api('/api/projects/' + encodeURIComponent(id) + '/workflow/status');
          if (!s.active) { clearInterval(poll); refreshProjects(); toast('Workflow finished: ' + (s.phase || 'done')); }
        } catch (e) { clearInterval(poll); }
      }, 2500);
    } catch (err) { toast(err.message, true); }
  }

  $('projectForm').addEventListener('submit', async function (e) {
    e.preventDefault();
    var title = $('projectTitle').value.trim(); if (!title) return;
    try {
      var data = await api('/api/projects', { method: 'POST', body: { title: title, description: 'Created from mobile office', createdBy: 'user' } });
      $('projectTitle').value = ''; toast('Project created');
      await refreshProjects(); $('taskProject').value = data.project.id;
    } catch (err) { toast(err.message, true); }
  });

  $('taskForm').addEventListener('submit', async function (e) {
    e.preventDefault();
    var pid = $('taskProject').value;
    var title = $('taskTitle').value.trim();
    var desc = $('taskDesc').value.trim();
    if (!pid || !title || !desc) { toast('Fill in project, title and instructions', true); return; }
    try {
      await api('/api/projects/' + encodeURIComponent(pid) + '/tasks', {
        method: 'POST',
        body: { title: title, description: desc, assignee: $('taskAgent').value, priority: 'medium', by: 'user' }
      });
      $('taskTitle').value = ''; $('taskDesc').value = '';
      toast('Task created');
      document.querySelector('.seg[data-task-tab="projects"]').click();
      refreshProjects();
    } catch (err) { toast(err.message, true); }
  });

  // ── Settings / boot ───────────────────────────────────────────────────
  async function refreshSettings() {
    try {
      var health = await api('/health');
      var version = await api('/api/version');
      var layer = await api('/api/office/provider-layer');
      var access = await api('/api/access/status');
      $('setEngine').textContent = version.version || health.version || 'unknown';
      $('setOffice').textContent = location.host;
      $('setLayer').textContent = layer.running ? ('running (Node ' + (layer.node || '?') + ')') : (layer.message || 'off');
      $('setAccess').textContent = access.protected ? (access.authenticated ? 'signed in' : 'locked') : 'open (local device)';
    } catch (err) {
      $('setEngine').textContent = 'Unavailable: ' + err.message;
    }
  }
  $('recheckSettings').addEventListener('click', refreshSettings);

  async function boot() {
    populateAgentSelects();
    renderOffice();
    applyTransform();
    try {
      var health = await api('/health');
      $('headerStatus').className = 'header-status online';
      $('headerStatusText').textContent = 'Connected · v' + (health.version || '?');
      $('headerSubtitle').textContent = 'Virtual Office · ' + (health.version || 'mobile');
    } catch (err) {
      $('headerStatus').className = 'header-status offline';
      $('headerStatusText').textContent = 'Disconnected';
      toast('Office server is unreachable: ' + err.message, true);
    }
    try {
      var agents = await api('/api/agents');
      state.status = { agents: agents.agents || [] };
    } catch (e) { /* office still works; provider status is best effort */ }
    renderOffice(); renderAgentCards();
    loadChatHistory(); refreshProjects(); refreshSettings();
  }

  boot();
})();
