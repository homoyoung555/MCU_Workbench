/* Formal workbench UI. It owns view state only; conversion remains a server concern. */
(function () {
  'use strict';

  var $ = function (selector) { return document.querySelector(selector); };
  var $$ = function (selector) { return Array.prototype.slice.call(document.querySelectorAll(selector)); };
  var connection = {};
  try { connection = JSON.parse($('#connection') ? $('#connection').textContent : '{}'); } catch (_) { connection = {}; }
  var token = typeof connection.token === 'string' ? connection.token : '';
  var state = {
    page: 'home',
    program: { loaded: false, name: '', sha256: '', revision: 0, dirty: false, busy: false },
    scan: { inputs: [], configuration: null, job: null, associations: [] },
    removedInputs: {},
    runSnapshot: null,
    previewFile: null,
    previewKind: 'pattern',
    previewCache: {},
    previewRequest: 0,
    inputRenderKey: '',
    cp: '',
    targets: [],
    polling: false,
    frameStarted: false,
    refreshingIdentity: false,
    initialized: false,
    offline: false,
    manualPins: { key: '', pins: [], inputs: [], selected: {}, status: 'idle', error: '', request: 0 }
  };
  var toastTimer = null;
  var programPollTimer = null;

  function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (ch) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch];
    });
  }
  function notify(message) {
    var el = $('#wb-toast');
    if (!el) return;
    el.textContent = message;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.hidden = true; }, 3600);
  }
  function badge(text, kind) { return '<span class="wb-badge ' + (kind ? 'wb-badge-' + kind : '') + '">' + escapeHtml(text) + '</span>'; }
  function setBadge(id, text, kind) {
    var el = $('#' + id);
    if (!el) return;
    el.className = 'wb-badge ' + (kind ? 'wb-badge-' + kind : '');
    el.textContent = text;
  }
  function jsonBody(body) { return { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) }; }
  async function api(path, options) {
    var opts = options || {};
    var headers = new Headers(opts.headers || {});
    headers.set('X-GUI-Session', token);
    var response;
    try { response = await fetch(path, Object.assign({}, opts, { headers: headers })); }
    catch (error) { state.offline = true; throw error; }
    if (!response.ok) {
      var message = 'HTTP ' + response.status;
      try { var body = await response.json(); message = body.error || body.message || message; } catch (_) {}
      throw new Error(message);
    }
    state.offline = false;
    if (response.status === 204) return null;
    var type = response.headers.get('content-type') || '';
    return type.indexOf('json') >= 0 ? response.json() : response.text();
  }
  function scanPart(payload) { return payload && payload.scan ? payload.scan : (payload || {}); }
  function resourceSignature() {
    var job = state.scan.job;
    return JSON.stringify({ job: job && { id: job.id, stale: !!job.stale, reason: job.reason || '' }, associations: state.scan.associations.map(function (a) { return [a.cp, a.item, a.kind, a.row, a.jobId, !!a.stale].join('|'); }) });
  }
  function notifyProgramResourcesChanged(before) {
    if (!state.initialized || before === resourceSignature()) return;
    var apiObject = currentFrameApi();
    try { if (apiObject && typeof apiObject.resourcesChanged === 'function') apiObject.resourcesChanged(); } catch (_) {}
  }
  function mergeWorkbench(payload) {
    if (payload && payload.program) state.program = Object.assign({}, state.program, payload.program);
    mergeScan(payload);
  }
  function mergeScan(payload, options) {
    var beforeResources = resourceSignature();
    var incoming = scanPart(payload);
    if (Array.isArray(incoming.inputs)) {
      if (options && options.appendInputs) {
        var current = state.scan.inputs.slice();
        incoming.inputs.forEach(function (item) {
          if (!item || item.id == null) return;
          delete state.removedInputs[item.id];
          var index = current.findIndex(function (existing) { return existing.id === item.id; });
          if (index < 0) current.push(item); else current[index] = item;
        });
        state.scan.inputs = current.filter(function (item) { return !state.removedInputs[item.id]; });
      } else state.scan.inputs = incoming.inputs.filter(function (item) { return !state.removedInputs[item.id]; });
    }
    if (Object.prototype.hasOwnProperty.call(incoming, 'configuration')) state.scan.configuration = incoming.configuration;
    if (Object.prototype.hasOwnProperty.call(incoming, 'job')) {
      state.scan.job = incoming.job;
      if (incoming.job) state.runSnapshot = { inputIds: (incoming.job.inputIds || []).slice(), adapt: !!incoming.job.adapt, source: incoming.job.source || 'current', cp: incoming.job.cp == null ? null : incoming.job.cp, manualPins: Array.isArray(incoming.job.manualPins) ? incoming.job.manualPins.slice() : null };
    }
    if (Array.isArray(incoming.associations)) state.scan.associations = incoming.associations;
    notifyProgramResourcesChanged(beforeResources);
  }
  function currentFrameApi() {
    var frame = $('#wb-program-frame');
    try { return frame && frame.contentWindow && frame.contentWindow.MCUProgram ? frame.contentWindow.MCUProgram : null; } catch (_) { return null; }
  }
  async function programStatus() {
    var apiObject = currentFrameApi();
    if (!apiObject || typeof apiObject.status !== 'function') return null;
    try { return await apiObject.status(); } catch (_) { return null; }
  }
  async function currentDraft() {
    var apiObject = currentFrameApi();
    if (!apiObject || typeof apiObject.draftPayload !== 'function') return null;
    try { return await apiObject.draftPayload(); } catch (_) { return null; }
  }
  function forwardDesktopBridge() {
    var frame = $('#wb-program-frame');
    if (!frame || !window.pywebview || !frame.contentWindow) return;
    try {
      frame.contentWindow.pywebview = window.pywebview;
      frame.contentWindow.dispatchEvent(new Event('pywebviewready'));
    } catch (_) {}
  }
  window.desktopPreviewClosed = function () {
    var frame = $('#wb-program-frame');
    try { if (frame && frame.contentWindow && typeof frame.contentWindow.desktopPreviewClosed === 'function') frame.contentWindow.desktopPreviewClosed(); } catch (_) {}
  };
  async function refreshProgramStatus() {
    var before = [state.program.loaded, state.program.name, state.program.sha256].join('|');
    var frameStatus = await programStatus();
    if (frameStatus && typeof frameStatus === 'object') state.program = Object.assign({}, state.program, frameStatus);
    updateProgramUI();
    updateScanUI();
    updateHomeUI();
    var after = [state.program.loaded, state.program.name, state.program.sha256].join('|');
    if (before !== after && state.frameStarted && !state.refreshingIdentity) {
      state.refreshingIdentity = true;
      try { mergeWorkbench(await api('/api/workbench')); updateAll(); }
      catch (_) { /* the bridge state remains usable until the next poll */ }
      finally { state.refreshingIdentity = false; }
    }
  }
  function scheduleProgramStatus() {
    if (programPollTimer || !state.frameStarted) return;
    programPollTimer = setTimeout(async function () {
      programPollTimer = null;
      await refreshProgramStatus();
      scheduleProgramStatus();
    }, 1800);
  }
  function ensureProgramFrame() {
    var frame = $('#wb-program-frame');
    if (!frame) return;
    if (!state.frameStarted) {
      frame.src = frame.getAttribute('data-src') || '/program';
      state.frameStarted = true;
      frame.hidden = false;
      frame.addEventListener('load', function () { forwardDesktopBridge(); refreshProgramStatus(); }, { once: false });
    }
    frame.hidden = false;
    forwardDesktopBridge();
    scheduleProgramStatus();
    $('#wb-program-empty').hidden = true;
  }
  function showPage(page) {
    if (page === 'compiler') { notify('V0.5 程序编译暂未开放'); return; }
    state.page = page;
    document.body.classList.toggle('wb-tool-open', page !== 'home');
    document.body.classList.toggle('wb-program-open', page === 'program');
    var main = document.querySelector('.wb-main'), programPanel = $('#wb-program-panel'), frame = $('#wb-program-frame');
    if (main) main.style.padding = page === 'program' ? '0' : '';
    if (programPanel) { programPanel.style.border = page === 'program' ? '0' : ''; programPanel.style.borderRadius = page === 'program' ? '0' : ''; }
    if (frame && page === 'program') { frame.style.height = 'calc(100vh - 66px)'; frame.style.minHeight = '0'; }
    document.body.classList.toggle('wb-program-open', page === 'program');
    $$('[data-page-view]').forEach(function (view) { view.hidden = view.getAttribute('data-page-view') !== page; });
    $$('[data-page]').forEach(function (button) {
      var active = button.getAttribute('data-page') === page;
      button.setAttribute('aria-current', active ? 'page' : 'false');
      if (button.classList.contains('wb-nav-item')) button.hidden = page !== 'home' && button.getAttribute('data-page') !== 'home';
    });
    if (page === 'program') ensureProgramFrame();
    if (page === 'swd') { var swdFrame = $('#wb-swd-frame'); if (!swdFrame.getAttribute('src')) swdFrame.src = swdFrame.dataset.src; }
    if (page === 'hex') { var hexFrame = $('#wb-hex-frame'); if (!hexFrame.getAttribute('src')) hexFrame.src = hexFrame.dataset.src; }
    if (page === 'compiler') { var compilerFrame = $('#wb-compiler-frame'); if (!compilerFrame.getAttribute('src')) compilerFrame.src = compilerFrame.dataset.src; }
    updateAll();
  }
  // Keep the originating program resource visible while using a generation tool.
  function openPatternTool(page, label, context) {
    var banner = document.getElementById('wb-pattern-return');
    if (!banner) {
      banner = document.createElement('div'); banner.id = 'wb-pattern-return';
      banner.style.cssText = 'position:fixed;bottom:16px;left:50%;transform:translateX(-50%);z-index:40;background:#e7f4ee;border:1px solid #90bdb1;border-radius:9px;padding:10px 14px;box-shadow:0 4px 20px #153c3820;display:flex;align-items:center;gap:14px;max-width:95vw';
      var text = document.createElement('span'); text.setAttribute('data-pattern-context', ''); banner.appendChild(text);
      var button = document.createElement('button'); button.textContent = '返回程序并选择结果';
      button.onclick = async function () { banner.remove(); showPage('program'); var frameApi = currentFrameApi(); if (frameApi && frameApi.resumePatternLink) await frameApi.resumePatternLink(); };
      banner.appendChild(button);
      var cancel = document.createElement('button'); cancel.textContent = '取消返回提示'; cancel.onclick = function () { banner.remove(); }; banner.appendChild(cancel);
      document.body.appendChild(banner);
    }
    banner.querySelector('[data-pattern-context]').textContent = '关联目标：' + label;
    banner.hidden = false; showPage(page);
    banner.querySelector('button').textContent = page === 'swd' ? '返回程序并关联步骤' : '返回程序并选择结果';
    if (page === 'swd' && context) {
      var frame = $('#wb-swd-frame');
      var open = function () { var api = frame.contentWindow.MCUSWD; if (api && api.openProgramSource) api.openProgramSource(context); };
      if (frame.contentWindow.MCUSWD) open(); else frame.addEventListener('load', open, { once: true });
    }
  }
  function activeInputs() { return state.scan.inputs.filter(function (x) { return !state.removedInputs[x.id]; }); }
  function manualInputKey() { return activeInputs().map(function (item) { return String(item.id) + '|' + String(item.sha256 || ''); }).join(';;'); }
  function pinKey(pin) { return String(pin == null ? '' : pin).trim().toLowerCase(); }
  function selectedManualPins() { return state.manualPins.pins.filter(function (pin) { return state.manualPins.selected[pin]; }); }
  function manualPinsValid() {
    var manual = state.manualPins;
    if (manual.status !== 'ready' || !selectedManualPins().length) return false;
    return activeInputs().every(function (input) {
      var found = manual.inputs.find(function (item) { return item.id === input.id; });
      return !!(found && found.pins.some(function (pin) { return manual.pins.some(function (selected) { return manual.selected[selected] && pinKey(selected) === pinKey(pin); }); }));
    });
  }
  function renderManualPins() {
    var wrap = $('#wb-manual-pins-wrap'), list = $('#wb-pin-list'), status = $('#wb-pin-status');
    var enabled = $('#wb-manual-pins').checked, manual = state.manualPins;
    wrap.hidden = !enabled;
    if (!enabled) return;
    var search = ($('#wb-pin-search').value || '').trim().toLowerCase();
    var pins = manual.pins.filter(function (pin) { return !search || pin.toLowerCase().indexOf(search) >= 0; });
    var key = [manual.key, manual.status, search, pins.map(function (pin) { return pin + ':' + !!manual.selected[pin]; }).join('|')].join('~');
    if (list.getAttribute('data-wb-render-key') !== key) {
      list.setAttribute('data-wb-render-key', key);
      list.innerHTML = pins.map(function (pin) { return '<label class="wb-check"><input type="checkbox" data-pin="' + escapeHtml(pin) + '"' + (manual.selected[pin] ? ' checked' : '') + '> ' + escapeHtml(pin) + '</label>'; }).join('') || (manual.status === 'ready' ? '<p class="wb-hint">没有匹配的管脚。</p>' : '');
    }
    status.textContent = manual.status === 'loading' ? '正在读取已导入 WGL 的管脚…' : manual.status === 'error' ? '读取管脚失败：' + manual.error : manual.status === 'ready' ? '已读取 ' + manual.pins.length + ' 个管脚，已选 ' + selectedManualPins().length + ' 个。' : '添加 WGL 后读取管脚。';
  }
  async function loadManualPins() {
    if (!$('#wb-manual-pins').checked) return;
    var key = manualInputKey(), inputs = activeInputs();
    if (!inputs.length) { state.manualPins = Object.assign({}, state.manualPins, { key: key, pins: [], inputs: [], status: 'idle', error: '' }); renderManualPins(); return; }
    if (state.manualPins.key === key && ['loading', 'ready', 'error'].indexOf(state.manualPins.status) >= 0) return;
    var request = state.manualPins.request + 1;
    state.manualPins = Object.assign({}, state.manualPins, { key: key, status: 'loading', error: '', request: request });
    renderManualPins(); updateStartUI();
    try {
      var response = await api('/api/scan/pins', jsonBody({ inputIds: inputs.map(function (item) { return item.id; }) }));
      if (!$('#wb-manual-pins').checked || request !== state.manualPins.request || key !== manualInputKey()) return;
      var seen = {}, pins = [];
      function addPin(pin) { pin = String(pin == null ? '' : pin).trim(); var key = pinKey(pin); if (pin && !seen[key]) { seen[key] = true; pins.push(pin); } }
      (response.pins || []).forEach(addPin);
      var pinInputs = (response.inputs || []).map(function (item) { var itemPins = []; (item.pins || []).forEach(function (pin) { pin = String(pin == null ? '' : pin).trim(); if (pin) { itemPins.push(pin); addPin(pin); } }); return { id: item.id, name: item.name, pins: itemPins }; });
      pins.forEach(function (pin) { if (!Object.prototype.hasOwnProperty.call(state.manualPins.selected, pin)) state.manualPins.selected[pin] = true; });
      state.manualPins = Object.assign({}, state.manualPins, { pins: pins, inputs: pinInputs, status: 'ready', error: '' });
    } catch (error) {
      if ($('#wb-manual-pins').checked && request === state.manualPins.request && key === manualInputKey()) state.manualPins = Object.assign({}, state.manualPins, { status: 'error', error: error.message || String(error) });
    }
    renderManualPins(); updateStartUI();
  }
  function result() { return state.scan.job && state.scan.job.result ? state.scan.job.result : null; }
  function jobRunning() { return !!(state.scan.job && state.scan.job.status === 'running'); }
  function resultStale() {
    var r = result();
    if (!r) return false;
    if (r.stale || (state.scan.job && state.scan.job.stale)) return true;
    return false;
  }
  function updateProgramUI() {
    var p = state.program;
    var name = p.loaded ? (p.name || '已打开程序') : '未打开程序';
    $('#wb-program-name').textContent = name;
    $('#wb-program-name').title = p.sha256 ? name + ' · SHA-256 ' + p.sha256 : name;
    setBadge('wb-program-badge', p.loaded ? (p.dirty ? '草稿有修改' : '已载入') : '可独立使用', p.dirty ? 'warn' : p.loaded ? '' : 'muted');
    $('#wb-program-empty').hidden = state.frameStarted;
  }
  function updateHomeUI() {
    var p = state.program;
    var job = state.scan.job;
    var r = result();
    setBadge('wb-home-program-status', p.loaded ? (p.dirty ? '草稿有修改' : '已载入') : '未打开', p.dirty ? 'warn' : p.loaded ? '' : 'muted');
    $('#wb-home-program-file').textContent = p.loaded ? (p.name || '已打开程序') : '没有已打开的程序';
    $('#wb-home-program-sha').textContent = p.loaded ? (p.sha256 ? 'SHA-256 ' + p.sha256 : '程序配置已载入') : '程序生成可以稍后打开';
    var status = job ? (job.status === 'running' ? '进行中' : job.status === 'failed' ? '失败' : resultStale() ? '需更新' : '已完成') : '暂无任务';
    setBadge('wb-home-scan-status', status, job && job.status === 'failed' ? 'danger' : resultStale() ? 'warn' : job ? '' : 'muted');
    $('#wb-home-scan-detail').textContent = job && job.status === 'running' ? '转换仍在后台运行，切换工具不会中断。' : r ? ((r.files || []).length + ' 个输出文件') : '转换记录会出现在这里。';
    $('#wb-home-scan-association').textContent = state.scan.associations.length ? '已有 ' + state.scan.associations.length + ' 个测试项关联。' : '结果由您主动关联到 SCAN / MBIST 测试项。';
    $('#wb-home-scan-open').hidden = !job;
  }
  function updateInputsUI() {
    var list = $('#wb-input-list');
    var inputs = activeInputs();
    $('#wb-input-count').textContent = inputs.length + ' 个 WGL';
    var inputKey = inputs.map(function (item) { return [item.id, item.name, item.size, item.sha256].join('|'); }).join(';;');
    if (list.getAttribute('data-wb-render-key') === inputKey) return;
    list.setAttribute('data-wb-render-key', inputKey);
    list.innerHTML = inputs.map(function (item) {
      return '<div class="wb-file-row" data-input-id="' + escapeHtml(item.id) + '"><div><div class="wb-file-title">' + escapeHtml(item.name || item.path || 'WGL 文件') + '</div><small>' + escapeHtml(item.size != null ? item.size + ' bytes' : '已导入副本') + (item.sha256 ? ' · SHA-256 ' + escapeHtml(item.sha256) : '') + '</small></div><button class="wb-button" data-remove-input="' + escapeHtml(item.id) + '" aria-label="移除 ' + escapeHtml(item.name || 'WGL 文件') + '">移除</button></div>';
    }).join('');
  }
  function updateConfigUI() {
    var adapt = $('#wb-adapt').checked;
    var manual = $('#wb-manual-pins').checked;
    var source = $('#wb-source').value;
    $('#wb-config-source-wrap').hidden = !adapt;
    $('#wb-current-config').hidden = !adapt || source !== 'current';
    $('#wb-other-config').hidden = !adapt || source !== 'other';
    var p = state.program;
    var currentDetail = p.loaded ? (p.name || '当前程序') + (p.sha256 ? ' · SHA-256 ' + p.sha256 : '') : '当前没有已载入程序，请打开程序后再使用适配。';
    if ($('#wb-current-config').getAttribute('data-wb-value') !== currentDetail) {
      $('#wb-current-config').innerHTML = '<small>' + escapeHtml(currentDetail) + '</small>';
      $('#wb-current-config').setAttribute('data-wb-value', currentDetail);
    }
    var config = state.scan.configuration;
    $('#wb-config-file').textContent = config ? (config.name || '已选择配置') + (config.sha256 ? ' · SHA-256 ' + config.sha256 : '') : '';
    var cpSource = source === 'other' ? config : p;
    var cps = cpSource && Array.isArray(cpSource.cps) ? cpSource.cps : [];
    if (cps.indexOf(state.cp) < 0) state.cp = cps[0] || '';
    var cpSelect = $('#wb-cp');
    var cpKey = source + '|' + cps.join('|');
    if (cpSelect.getAttribute('data-wb-options') !== cpKey) {
      cpSelect.innerHTML = cps.map(function (cp) { return '<option value="' + escapeHtml(cp) + '">' + escapeHtml(cp) + '</option>'; }).join('');
      cpSelect.setAttribute('data-wb-options', cpKey);
    }
    cpSelect.value = state.cp;
    cpSelect.disabled = !cps.length;
    renderManualPins();
    if (manual) loadManualPins();
    var modeKey = adapt + '|' + source + '|' + manual;
    if ($('#wb-mode-summary').getAttribute('data-wb-value') !== modeKey) {
      $('#wb-mode-summary').innerHTML = manual ? '<strong>手动管脚 · 独立转换</strong><p>仅使用已导入 WGL 读取的管脚；无需程序 Excel。</p>' : adapt ? '<strong>按程序配置适配</strong><p>统一管脚名称、筛选与排序向量列，适配程序与时序引用。波形与周期均来自 WGL。</p>' : '<strong>Full Pin · 独立转换</strong><p>保留 WGL 完整管脚，无需程序 Excel。波形与周期均来自 WGL。</p>';
      $('#wb-mode-summary').setAttribute('data-wb-value', modeKey);
    }
    setBadge('wb-scan-mode-badge', manual ? '当前设置 · 手动管脚' : adapt ? '当前设置 · 程序适配' : '当前设置 · Full Pin', 'muted');
  }
  function labelSettings() {
    var marker = $('#wb-label-marker').value.trim();
    var base = $('#wb-label-base').value.trim();
    if (!marker && !base) return { valid: true, marker: null, base: null };
    if (!marker || !base) return { valid: false, marker: marker || null, base: base || null, error: '启用标签时必须同时填写识别标记文本和 Label 名前缀。' };
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(base)) return { valid: false, marker: marker, base: base, error: 'Label 名前缀必须以字母或下划线开头，且只能包含字母、数字和下划线。' };
    return { valid: true, marker: marker, base: base };
  }
  function frozenLabelSettings(job) {
    var hasJobLabels = job && (Object.prototype.hasOwnProperty.call(job, 'labelMarker') || Object.prototype.hasOwnProperty.call(job, 'labelBase'));
    var source = hasJobLabels ? job : state.runSnapshot;
    return source && source.labelMarker && source.labelBase ? { marker: source.labelMarker, base: source.labelBase } : { marker: null, base: null };
  }
  function updateStartUI() {
    var adapt = $('#wb-adapt').checked;
    var manual = $('#wb-manual-pins').checked;
    var source = $('#wb-source').value;
    var platforms = $$('input[data-platform]').filter(function (x) { return x.checked; }).map(function (x) { return x.value; });
    var labels = labelSettings();
    var valid = activeInputs().length > 0 && platforms.length > 0 && (!adapt || (source === 'current' ? state.program.loaded : !!state.scan.configuration)) && (!adapt || !!$('#wb-cp').value) && (!manual || manualPinsValid()) && labels.valid;
    var button = $('#wb-start-scan');
    button.disabled = !valid || jobRunning();
    button.textContent = jobRunning() ? '转换进行中…' : resultStale() ? '重新转换' : '开始转换';
    var hint = '';
    if (!activeInputs().length) hint = '请添加至少一个 WGL 文件。';
    else if (!platforms.length) hint = '请选择至少一个目标平台。';
    else if (adapt && source === 'current' && !state.program.loaded) hint = '当前没有已载入程序，请进入程序生成后打开程序。';
    else if (adapt && source === 'other' && !state.scan.configuration) hint = '请选择用于适配的程序 Excel。';
    else if (adapt && !$('#wb-cp').value) hint = '请选择适配 CP。';
    else if (manual && state.manualPins.status === 'loading') hint = '正在读取 WGL 管脚。';
    else if (manual && state.manualPins.status === 'error') hint = '管脚读取失败，请变更输入后重试。';
    else if (manual && !manualPinsValid()) hint = '每个输入 WGL 至少选择一个管脚。';
    else if (!labels.valid) hint = labels.error;
    else if (resultStale()) hint = '旧结果将保留关联，但重新转换后才可用于生成程序。';
    $('#wb-start-hint').textContent = hint;
  }
  function kindOf(file) {
    var text = ((file.kind || '') + ' ' + (file.path || file.name || '')).toLowerCase();
    return text.indexOf('tim') >= 0 ? 'timing' : text.indexOf('code') >= 0 || text.indexOf('prg') >= 0 ? 'code' : 'pattern';
  }
  function filesByPlatform(files) {
    var groups = {};
    (files || []).forEach(function (file) { var platform = file.platform || 'output'; (groups[platform] = groups[platform] || []).push(file); });
    return groups;
  }
  function renderOutputs(r) {
    var files = (r && r.files) || [];
    var groups = filesByPlatform(files);
    return Object.keys(groups).map(function (platform) {
      return '<div class="wb-output-group"><h3>' + escapeHtml(platform) + '</h3>' + groups[platform].map(function (file) {
        var path = file.path || file.name || '';
        return '<div class="wb-output-file"><button data-output-file="' + escapeHtml(path) + '" title="预览 ' + escapeHtml(path) + '">' + escapeHtml(path) + '</button><button class="wb-button" data-download-file="' + escapeHtml(path) + '">下载</button></div>';
      }).join('') + '</div>';
    }).join('') || '<div class="wb-empty wb-result-empty">服务未返回输出文件。</div>';
  }
  function renderAssociations() {
    if (!state.scan.associations.length) return '<p class="wb-hint wb-associations">尚未关联测试项。转换完成后可手动选择 SCAN / MBIST 行。</p>';
    return '<div class="wb-associations">' + state.scan.associations.map(function (a) { return '<span class="wb-association">' + badge('已关联') + '<strong>' + escapeHtml(a.item || a.name || ('行 ' + (a.row || ''))) + '</strong>' + (a.stale ? badge('需更新', 'warn') : '') + '</span>'; }).join('') + '</div>';
  }
  function renderLogs(job) {
    var logs = job && Array.isArray(job.logs) ? job.logs : [];
    return logs.length ? '<details class="wb-logs"><summary>任务日志（' + logs.length + '）</summary><pre class="wb-code">' + escapeHtml(logs.join('\n')) + '</pre></details>' : '';
  }
  function snapshotLabel(job, r) {
    var manualPins = job && Array.isArray(job.manualPins) ? job.manualPins : state.runSnapshot && Array.isArray(state.runSnapshot.manualPins) ? state.runSnapshot.manualPins : null;
    var mode = manualPins ? '手动管脚 · ' + manualPins.length + ' 个' : job && job.adapt ? '程序适配 · CP ' + (job.cp || '未指定') + ' · ' + (job.source === 'other' ? '另选程序 Excel' : '当前工作台配置') : 'Full Pin · 独立转换';
    var platforms = (job && job.platforms || r && r.platforms || []).join(' + ');
    var count = job && Array.isArray(job.inputIds) ? job.inputIds.length : state.runSnapshot && state.runSnapshot.inputIds ? state.runSnapshot.inputIds.length : 0;
    var labels = frozenLabelSettings(job);
    var labelSummary = labels.marker ? ' · 标签识别：' + labels.marker + ' · Label 名前缀：' + labels.base : '';
    return mode + ' · 平台 ' + (platforms || '未返回') + ' · ' + count + ' 个输入 WGL' + labelSummary;
  }
  function updateResultUI() {
    var job = state.scan.job, r = result(), stale = resultStale(), statusEl = $('#wb-result-status');
    var status = job ? (job.status === 'running' ? '进行中' : job.status === 'failed' ? '失败' : stale ? '需要重新转换' : '转换完成') : '等待转换';
    setBadge('wb-result-status', status, job && job.status === 'failed' ? 'danger' : stale ? 'warn' : job ? '' : 'muted');
    var body = $('#wb-result-body');
    var renderKey = JSON.stringify({ previewKind: state.previewKind, id: job && job.id, status: job && job.status, error: job && job.error, stale: stale, reason: job && job.reason, logs: job && job.logs, files: r && r.files, labels: frozenLabelSettings(job), associations: state.scan.associations });
    if (body.getAttribute('data-wb-render-key') === renderKey) return;
    body.setAttribute('data-wb-render-key', renderKey);
    if (!job && !r) { body.innerHTML = '<div class="wb-empty wb-result-empty">转换完成后，在这里查看文件、代码、时序和关联状态。</div>'; return; }
    if (job && job.status === 'running') { body.innerHTML = '<p>正在生成 Pattern、程序代码片段和时序定义…</p><div class="wb-mode-summary"><strong>任务在后台运行</strong><p>' + escapeHtml(snapshotLabel(job, r)) + '</p><p>已固定启动时的输入与配置快照，切换工具不会中断。</p></div>' + renderLogs(job); return; }
    if (job && job.status === 'failed' && !r) { body.innerHTML = '<div class="wb-alert">' + escapeHtml(job.error || '转换失败，请检查日志后重试。') + '</div>' + renderLogs(job) + '<button class="wb-button wb-primary" data-retry-scan>重试转换</button>'; return; }
    var warning = stale ? '<div class="wb-alert">' + escapeHtml((r && r.reason) || '输入或配置已变化。关联仍保留，生成程序前必须重新转换。') + '</div>' : '';
    var canLink = !stale && job && job.id && !jobRunning() && state.program.loaded;
    body.innerHTML = warning + '<div class="wb-result-summary"><div><strong>本次任务快照</strong><p>' + escapeHtml(snapshotLabel(job, r)) + '</p><p>' + escapeHtml((r && r.files || []).length + ' 个输出文件 · Pattern、程序代码片段和时序定义') + '</p></div><button class="wb-button wb-primary" data-open-link ' + (canLink ? '' : 'disabled') + '>关联到测试项</button></div><div class="wb-result-grid"><div>' + renderOutputs(r) + '</div><div><div class="wb-output-actions"><button class="wb-button" data-preview-kind="pattern" aria-pressed="' + (state.previewKind === 'pattern' ? 'true' : 'false') + '">Pattern</button><button class="wb-button" data-preview-kind="code" aria-pressed="' + (state.previewKind === 'code' ? 'true' : 'false') + '">程序片段</button><button class="wb-button" data-preview-kind="timing" aria-pressed="' + (state.previewKind === 'timing' ? 'true' : 'false') + '">时序</button></div><pre id="wb-output-preview" class="wb-code">选择输出文件查看内容。</pre></div></div>' + renderAssociations();
    pickPreviewFile();
  }
  function pickPreviewFile() {
    var files = result() && result().files || [];
    if (!files.length) return;
    var current = files.find(function (f) { return (f.path || f.name) === state.previewFile; });
    var candidates = files.filter(function (f) { return kindOf(f) === state.previewKind; });
    var selected = candidates.find(function (f) { return f === current; }) || candidates.find(function (f) { return current && current.sourceName && f.sourceName === current.sourceName && f.platform === current.platform; }) || candidates[0];
    if (!selected) { $('#wb-output-preview').textContent = '没有此类型的输出文件。'; return; }
    state.previewFile = selected.path || selected.name;
    loadPreview(selected);
  }
  async function loadPreview(file) {
    var pre = $('#wb-output-preview');
    if (!pre || !file) return;
    state.previewFile = file.path || file.name;
    var expectedJobId = state.scan.job && state.scan.job.id || '';
    var cacheKey = expectedJobId + '|' + state.previewFile + '|' + (file.sha256 || '');
    if (Object.prototype.hasOwnProperty.call(state.previewCache, cacheKey)) { pre.textContent = state.previewCache[cacheKey]; return; }
    var requestId = ++state.previewRequest;
    pre.textContent = '正在读取输出…';
    try {
      var job = state.scan.job;
      var query = '?id=' + encodeURIComponent(job.id) + '&file=' + encodeURIComponent(state.previewFile);
      var data = await api('/api/scan/output' + query);
      var text = data && typeof data === 'object' ? (data.text || '') : String(data || '');
      state.previewCache[cacheKey] = text;
      if (requestId === state.previewRequest && state.scan.job && state.scan.job.id === expectedJobId && state.previewFile === (file.path || file.name)) pre.textContent = text;
    } catch (error) { pre.textContent = '无法读取输出：' + error.message; }
  }
  function updateScanUI() { updateInputsUI(); updateConfigUI(); updateStartUI(); updateResultUI(); }
  function updateAll() { updateProgramUI(); updateHomeUI(); updateScanUI(); }
  async function statusRequest() {
    var draft = await currentDraft();
    return api('/api/scan/status', jsonBody(draft && typeof draft === 'object' ? { draft: draft } : {}));
  }
  async function refreshWorkbench() {
    try { mergeWorkbench(await api('/api/workbench')); await refreshProgramStatus(); updateAll(); state.initialized = true; if (state.scan.job) schedulePoll(); }
    catch (error) { notify('无法读取工作台状态：' + error.message); updateAll(); }
  }
  var pollTimer = null;
  function schedulePoll() {
    if (pollTimer || !state.scan.job) return;
    pollTimer = setTimeout(async function () {
      pollTimer = null;
      if (!state.scan.job) return;
      try { mergeWorkbench(await statusRequest()); await refreshProgramStatus(); updateAll(); }
      catch (error) { notify('读取 SCAN 任务状态失败：' + error.message); }
      if (state.scan.job) schedulePoll();
    }, jobRunning() ? 1500 : 4000);
  }
  async function uploadWglFiles(fileList) {
    var files = Array.prototype.slice.call(fileList || []).filter(function (file) { return /\.wgl$/i.test(file.name); });
    if (!files.length) { notify('请选择 WGL 文件。'); return; }
    var rejected = (fileList || []).length - files.length;
    if (rejected) notify('已忽略 ' + rejected + ' 个非 WGL 文件。');
    for (var i = 0; i < files.length; i += 1) {
      try { var uploaded = await api('/api/scan/input', { method: 'POST', headers: { 'Content-Type': 'application/octet-stream', 'X-File-Name': encodeURIComponent(files[i].name) }, body: await files[i].arrayBuffer() }); mergeScan({ inputs: [uploaded && uploaded.input ? uploaded.input : uploaded] }, { appendInputs: true }); }
      catch (error) { notify('导入 ' + files[i].name + ' 失败：' + error.message); }
    }
    updateAll();
  }
  async function chooseWgl() {
    var bridge = window.pywebview && window.pywebview.api;
    if (bridge && typeof bridge.select_scan_files === 'function') {
      try {
        var selected = await bridge.select_scan_files();
        var paths = (selected || []).map(function (item) { return typeof item === 'string' ? item : item.path; }).filter(Boolean);
        if (paths.length) mergeScan(await api('/api/scan/register', jsonBody({ paths: paths })), { appendInputs: true });
        updateAll();
        if (paths.length) return;
      } catch (error) { notify('桌面文件选择失败，已切换到浏览器选择。'); }
    }
    $('#wb-file-picker').click();
  }
  async function uploadConfig(file) {
    if (!file) return;
    if (!/\.(xlsx|xls)$/i.test(file.name)) { notify('请选择 Excel 配置文件。'); return; }
    try { var response = await api('/api/scan/config', { method: 'POST', headers: { 'Content-Type': 'application/octet-stream', 'X-File-Name': encodeURIComponent(file.name) }, body: await file.arrayBuffer() }); state.scan.configuration = response.configuration || response; $('#wb-source').value = 'other'; updateAll(); }
    catch (error) { notify('导入程序 Excel 失败：' + error.message); }
  }
  async function startScan() {
    if (jobRunning()) return;
    var manual = $('#wb-manual-pins').checked;
    var adapt = manual ? false : $('#wb-adapt').checked, source = $('#wb-source').value;
    var draft = adapt && source === 'current' ? await currentDraft() : null;
    var inputIds = activeInputs().map(function (item) { return item.id; });
    var platforms = $$('input[data-platform]').filter(function (x) { return x.checked; }).map(function (x) { return x.value; });
    var manualPins = manual ? selectedManualPins() : null;
    var labels = labelSettings();
    if ((manual && !manualPinsValid()) || !labels.valid) { updateStartUI(); return; }
    var response;
    try {
      response = await api('/api/scan/start', jsonBody({ inputIds: inputIds, platforms: platforms, adapt: adapt, source: source, cp: adapt ? $('#wb-cp').value : null, draft: draft, manualPins: manualPins, labelMarker: labels.marker, labelBase: labels.base }));
      state.runSnapshot = { inputIds: inputIds.slice(), adapt: adapt, source: adapt ? source : 'full', cp: adapt ? $('#wb-cp').value : null, manualPins: manualPins && manualPins.slice(), labelMarker: labels.marker, labelBase: labels.base, programRevision: state.program.revision, configurationSha: adapt && source === 'other' && state.scan.configuration ? state.scan.configuration.sha256 : null };
      state.scan.job = { id: response.jobId, status: 'running', logs: [], adapt: adapt, source: source, manualPins: manualPins, labelMarker: labels.marker, labelBase: labels.base };
      state.previewFile = null;
      updateAll();
      schedulePoll();
    } catch (error) { notify('无法启动 SCAN 转换：' + error.message); }
  }
  async function openLinkDialog() {
    var job = state.scan.job;
    if (!job || !job.id || resultStale() || !state.program.loaded) return;
    try {
      var response = await api('/api/scan/targets', jsonBody({ draft: await currentDraft() }));
      state.targets = response.targets || [];
      var select = $('#wb-target-select');
      select.innerHTML = state.targets.map(function (target, index) { return '<option value="' + index + '">' + escapeHtml((target.cp || '') + ' · ' + (target.item || '') + ' · ' + (target.kind || '') + ' · 行 ' + (target.row || '')) + '</option>'; }).join('');
      if (!state.targets.length) { notify('当前程序没有可关联的 SCAN / MBIST 测试项。'); return; }
      $('#wb-link-dialog').showModal();
    } catch (error) { notify('无法读取测试项：' + error.message); }
  }
  async function confirmLink(event) {
    event.preventDefault();
    var index = Number($('#wb-target-select').value), target = state.targets[index], button = $('#wb-confirm-link');
    if (!target) return;
    button.disabled = true;
    try { mergeScan(await api('/api/scan/link', jsonBody({ jobId: state.scan.job.id, row: target.row, draft: await currentDraft() }))); $('#wb-link-dialog').close(); notify('已建立测试项关联。'); updateAll(); }
    catch (error) { notify('建立关联失败：' + error.message); }
    finally { button.disabled = false; }
  }
  async function downloadFile(path) {
    try {
      var response = await fetch('/api/scan/download?id=' + encodeURIComponent(state.scan.job.id) + '&file=' + encodeURIComponent(path), { headers: { 'X-GUI-Session': token } });
      if (!response.ok) throw new Error('HTTP ' + response.status);
      var blob = await response.blob(), url = URL.createObjectURL(blob), link = document.createElement('a');
      link.href = url; link.download = path.split('/').pop() || 'scan-output'; document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url);
    } catch (error) { notify('下载输出失败：' + error.message); }
  }
  function bind() {
    document.addEventListener('click', function (event) {
      var target = event.target.closest('button');
      if (!target || target.disabled) return;
      if (target.id === 'wb-assistant') {
        if (window.pywebview && window.pywebview.api) window.pywebview.api.open_assistant().catch(function (e) { notify(e.message); });
        else window.open('/assistant', 'mcu-assistant', 'width=1000,height=820');
        return;
      }
      if (target.dataset.page) { event.preventDefault(); showPage(target.dataset.page); return; }
      if (target.id === 'wb-pick-files') { event.preventDefault(); chooseWgl(); return; }
      if (target.id === 'wb-pick-folder') { event.preventDefault(); $('#wb-folder-picker').click(); return; }
      if (target.id === 'wb-program-open') { event.preventDefault(); showPage('program'); return; }
      if (target.id === 'wb-start-scan' || target.dataset.retryScan) { event.preventDefault(); startScan(); return; }
      if (target.id === 'wb-select-all-pins' || target.id === 'wb-clear-pins') { state.manualPins.pins.forEach(function (pin) { state.manualPins.selected[pin] = target.id === 'wb-select-all-pins'; }); renderManualPins(); updateStartUI(); return; }
      if (target.dataset.removeInput) { state.removedInputs[target.dataset.removeInput] = true; state.scan.inputs = activeInputs(); updateAll(); return; }
      if (target.dataset.openLink) { event.preventDefault(); openLinkDialog(); return; }
      if (target.dataset.outputFile) { var f = (result().files || []).find(function (x) { return (x.path || x.name) === target.dataset.outputFile; }); if (f) { state.previewFile = f.path || f.name; state.previewKind = kindOf(f); $('#wb-result-body').setAttribute('data-wb-render-key', ''); updateResultUI(); } return; }
      if (target.dataset.downloadFile) { downloadFile(target.dataset.downloadFile); return; }
      if (target.dataset.previewKind) { state.previewKind = target.dataset.previewKind; updateResultUI(); return; }
    });
    $('#wb-file-picker').addEventListener('change', function (event) { uploadWglFiles(event.target.files); event.target.value = ''; });
    $('#wb-folder-picker').addEventListener('change', function (event) { uploadWglFiles(event.target.files); event.target.value = ''; });
    $('#wb-config-picker').addEventListener('change', function (event) { uploadConfig(event.target.files[0]); event.target.value = ''; });
    $('#wb-pick-config').addEventListener('click', function () { $('#wb-config-picker').click(); });
    $('#wb-adapt').addEventListener('change', function () {
      if ($('#wb-adapt').checked) {
        $('#wb-manual-pins').checked = false;
        if (state.manualPins.status === 'loading') state.manualPins = Object.assign({}, state.manualPins, { status: 'idle', request: state.manualPins.request + 1 });
      }
      updateAll();
    });
    $('#wb-manual-pins').addEventListener('change', function () {
      if ($('#wb-manual-pins').checked) $('#wb-adapt').checked = false;
      else if (state.manualPins.status === 'loading') state.manualPins = Object.assign({}, state.manualPins, { status: 'idle', request: state.manualPins.request + 1 });
      updateAll();
    });
    $('#wb-source').addEventListener('change', updateAll);
    $('#wb-cp').addEventListener('change', function () { state.cp = $('#wb-cp').value; updateStartUI(); });
    $('#wb-platform-chroma').addEventListener('change', updateStartUI);
    $('#wb-platform-s100').addEventListener('change', updateStartUI);
    $('#wb-label-marker').addEventListener('input', updateStartUI);
    $('#wb-label-base').addEventListener('input', updateStartUI);
    $('#wb-pin-search').addEventListener('input', renderManualPins);
    $('#wb-pin-list').addEventListener('change', function (event) { var pin = event.target && event.target.dataset && event.target.dataset.pin; if (!pin) return; state.manualPins.selected[pin] = !!event.target.checked; renderManualPins(); updateStartUI(); });
    $('#wb-confirm-link').addEventListener('click', confirmLink);
    window.addEventListener('pywebviewready', forwardDesktopBridge);
    var drop = $('#wb-dropzone');
    drop.addEventListener('dragover', function (event) { event.preventDefault(); drop.classList.add('wb-drag'); });
    drop.addEventListener('dragleave', function () { drop.classList.remove('wb-drag'); });
    drop.addEventListener('drop', function (event) { event.preventDefault(); drop.classList.remove('wb-drag'); uploadWglFiles(event.dataTransfer.files); });
  }
  function assistantContext() {
    var program = currentFrameApi(), swdFrame = $('#wb-swd-frame');
    var swd = swdFrame && swdFrame.contentWindow && swdFrame.contentWindow.MCUSWD;
    var hexFrame = $('#wb-hex-frame'), hex = hexFrame && hexFrame.contentWindow && hexFrame.contentWindow.MCUHex;
    var manual = $('#wb-manual-pins').checked, adapt = !manual && $('#wb-adapt').checked, labels = labelSettings();
    return { page: state.page, program: program && program.assistantSnapshot ? program.assistantSnapshot() : null,
      swd: swd && swd.assistantSnapshot ? swd.assistantSnapshot() : {},
      hex: hex && hex.assistantSnapshot ? hex.assistantSnapshot() : null,
      scan: { job: state.scan.job, configuration: state.scan.configuration, request: {
        inputIds:activeInputs().map(function(item){return item.id;}),
        platforms:$$('input[data-platform]').filter(function(x){return x.checked;}).map(function(x){return x.value;}),
        adapt:adapt,source:$('#wb-source').value,cp:adapt?$('#wb-cp').value:null,
        draft:adapt && $('#wb-source').value==='current' && program ? program.draftPayload():null,
        manualPins:manual?selectedManualPins():null,labelMarker:labels.marker,labelBase:labels.base} } };
  }
  function assistantJob(value) {
    showPage(value.page);
    if (value.page === 'program') { var program = currentFrameApi(); if (program) program.assistantJob(value.jobId); }
    else if (value.page === 'hex') { var frame = $('#wb-hex-frame'); if (frame.contentWindow.MCUHex) frame.contentWindow.MCUHex.refresh(); }
    else refreshWorkbench();
  }
  function receiveAssistant(value) {
    var frame = $('#wb-swd-frame'), swd = frame && frame.contentWindow && frame.contentWindow.MCUSWD;
    if (!swd) { showPage('swd'); throw new Error('已打开 SWD 页面，请在页面就绪后基于当前草稿重新提问'); }
    if (JSON.stringify(assistantContext()) !== JSON.stringify(value.context)) throw new Error('主窗口草稿或对象已改变，拒绝应用旧候选');
    if (value.edit) return swd.applyAssistantEdit(value.edit);
    var config = swd.state().config;
    if (!value.config || ['PT104', 'PCD009'].indexOf(config.chip) < 0 || Object.keys(value.config.pins).some(function (key) { return config.pins[key] !== value.config.pins[key]; })) throw new Error('当前SWD管脚配置与候选不同，请核对配置后重新生成');
    var result = swd.receiveAssistant(value.document); showPage('swd'); return result;
  }
  function undoAssistant() {
    var frame = $('#wb-swd-frame'), swd = frame && frame.contentWindow && frame.contentWindow.MCUSWD;
    if (!swd) throw new Error('SWD 编辑器尚未打开');
    return swd.undoAssistant();
  }
  window.MCUWorkbench = { assistantJob: assistantJob, receiveAssistant: receiveAssistant, undoAssistant: undoAssistant, assistantContext: assistantContext, refresh: refreshWorkbench, state: function () { return state; }, draftPayload: currentDraft, open: showPage, openPatternTool: openPatternTool, resourcesChanged: function () { var frameApi = currentFrameApi(); if (frameApi && frameApi.resourcesChanged) frameApi.resourcesChanged(); } };
  bind();
  showPage('home');
  refreshWorkbench();
}());
