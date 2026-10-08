/* Vendor compiler queue UI. The compiler and its diagnostics remain server-owned. */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var connection = {};
  try { connection = JSON.parse(($('connection') || {}).textContent || '{}'); } catch (_) {}
  var token = typeof connection.token === 'string' ? connection.token : '';
  var state = { tasks: [], running: false, tools: {}, selectedId: '', checked: {}, polling: false, uploading: false, submitting: false, pollTimer: null, logRequest: 0, logTaskId: '' };
  state.modes = {}; state.modeChoices = {};
  var statusNames = { uploading: '正在上传', ready: '待编译', queued: '排队中', running: '编译中', passed: '通过', failed: '失败', interrupted: '已中断' };
  var phaseNames = { uploading: '正在上传', ready: '等待编译', queued: '排队中', running: '正在运行厂商编译器', passed: '编译完成', failed: '编译失败', interrupted: '编译已中断' };

  function text(value) { return value == null ? '' : String(value); }
  function setText(id, value) { var node = $(id); if (node) node.textContent = text(value); }
  function jsonHeaders(extra) {
    var headers = new Headers(extra || {});
    headers.set('X-GUI-Session', token);
    return headers;
  }
  async function api(path, options) {
    var opts = options || {};
    var response;
    try { response = await fetch(path, Object.assign({}, opts, { headers: jsonHeaders(opts.headers) })); }
    catch (error) { throw new Error('无法连接服务：' + error.message); }
    if (!response.ok) {
      var message = 'HTTP ' + response.status;
      try { var body = await response.json(); message = body.error || body.message || message; } catch (_) {}
      throw new Error(message);
    }
    if (response.status === 204) return null;
    var type = (response.headers && response.headers.get('content-type')) || '';
    return type.indexOf('json') >= 0 ? response.json() : response.text();
  }
  function postJSON(path, body) { return api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) }); }
  function payloadState(payload) { return payload && payload.state ? payload.state : (payload || {}); }
  function taskById(id) { return state.tasks.find(function (task) { return String(task.id) === String(id); }) || null; }
  function statusKind(status) { return status === 'failed' || status === 'interrupted' ? 'danger' : status === 'queued' || status === 'running' ? 'warn' : status === 'passed' ? '' : 'muted'; }
  function canCompileTask(task) { return !!task && !!task.platform && task.status !== 'uploading' && task.status !== 'queued' && task.status !== 'running'; }
  function badge(value, kind) { var node = document.createElement('span'); node.className = 'wb-badge' + (kind ? ' wb-badge-' + kind : ''); node.textContent = text(value); return node; }
  function clear(node) { while (node && node.firstChild) node.removeChild(node.firstChild); }

  function groupFiles(files) {
    var groups = {};
    Array.prototype.forEach.call(files || [], function (file) {
      var original = file.webkitRelativePath || file.name || '';
      var parts = original.split('/').filter(function (part) { return part !== ''; });
      var root = parts.length > 1 ? parts[0] : '程序文件夹';
      var relative = parts.length > 1 ? parts.slice(1).join('/') : parts.join('/');
      if (!relative) return;
      if (!groups[root]) groups[root] = [];
      groups[root].push({ file: file, name: relative });
    });
    return Object.keys(groups).map(function (name) { return { name: name, files: groups[name] }; });
  }
  async function discard(id) {
    try { await postJSON('/api/compiler/discard', { id: id }); } catch (_) {}
  }
  async function uploadGroup(group) {
    var created = await postJSON('/api/compiler/create', { name: group.name });
    var id = created && (created.id || (created.task && created.task.id));
    if (!id) throw new Error('服务未返回编译任务编号');
    try {
      for (var index = 0; index < group.files.length; index += 1) {
        var item = group.files[index];
        setText('compiler-status', '正在上传「' + group.name + '」：' + (index + 1) + ' / ' + group.files.length);
        await api('/api/compiler/file', { method: 'POST', headers: { 'Content-Type': 'application/octet-stream', 'X-Task-Id': id, 'X-File-Name': encodeURIComponent(item.name) }, body: item.file });
      }
      await postJSON('/api/compiler/ready', { id: id });
    } catch (error) {
      await discard(id);
      throw error;
    }
  }
  async function droppedGroups(entries) {
    if (!entries.length || entries.some(function (entry) { return !entry || !entry.isDirectory; })) throw new Error('请拖入完整程序文件夹，不支持单独拖入文件。');
    var groups = [];
    for (var root of entries) {
      var group = { name: root.name, files: [] }, bytes = 0;
      async function visit(entry, prefix) {
        if (entry.isFile) {
          var file = await new Promise(function (resolve, reject) { entry.file(resolve, reject); });
          bytes += file.size;
          if (file.size > 256 * 1024 * 1024 || bytes > 2 * 1024 * 1024 * 1024 || group.files.length >= 20000) throw new Error('文件夹超过上传限制：单文件256 MiB、单任务2 GiB或20000个文件。');
          group.files.push({file:file, name:prefix + entry.name});
        } else if (entry.isDirectory) {
          var reader = entry.createReader(), batch;
          do {
            batch = await new Promise(function (resolve, reject) { reader.readEntries(resolve, reject); });
            for (var child of batch) await visit(child, prefix + entry.name + '/');
          } while (batch.length);
        }
      }
      var reader = root.createReader(), batch;
      do {
        batch = await new Promise(function (resolve, reject) { reader.readEntries(resolve, reject); });
        for (var entry of batch) await visit(entry, '');
      } while (batch.length);
      if (!group.files.length) throw new Error('文件夹「' + root.name + '」为空。');
      groups.push(group);
    }
    return groups;
  }
  async function addFolder(files, entries) {
    if (state.uploading || state.submitting) return;
    state.uploading = true; updateButtons();
    try {
      setText('compiler-status', '正在读取程序文件夹…');
      var groups = entries ? await droppedGroups(entries) : groupFiles(files);
      if (!groups.length) { setText('compiler-status', '所选文件夹没有可上传文件。'); return; }
      var failed = 0;
      for (var index = 0; index < groups.length; index += 1) {
        try { await uploadGroup(groups[index]); }
        catch (error) { failed += 1; setText('compiler-status', '「' + groups[index].name + '」上传失败：' + error.message); }
      }
      if (!failed) setText('compiler-status', '已添加 ' + groups.length + ' 个编译任务。');
      await refresh();
    } catch (error) { setText('compiler-status', '读取文件夹失败：' + error.message); }
    finally { state.uploading = false; updateButtons(); }
  }

  function renderTasks() {
    var list = $('compiler-task-list');
    if (!list) return;
    clear(list);
    setText('compiler-task-count', state.tasks.length + ' 个');
    if (!state.tasks.length) { var empty = document.createElement('div'); empty.className = 'compiler-empty'; empty.textContent = '尚未添加程序文件夹。'; list.appendChild(empty); updateButtons(); return; }
    state.tasks.forEach(function (task) {
      var row = document.createElement('article'); row.className = 'compiler-task'; row.setAttribute('data-task-id', task.id); row.setAttribute('aria-current', String(task.id) === String(state.selectedId) ? 'true' : 'false');
      var top = document.createElement('div'); top.className = 'compiler-task-top';
      var check = document.createElement('input'); check.type = 'checkbox'; check.disabled = !canCompileTask(task); check.checked = !!state.checked[task.id]; check.setAttribute('aria-label', '选择任务 ' + text(task.name)); check.addEventListener('click', function (event) { event.stopPropagation(); state.checked[task.id] = check.checked; updateButtons(); }); top.appendChild(check);
      var main = document.createElement('div'); main.className = 'compiler-task-main';
      var name = document.createElement('div'); name.className = 'compiler-task-name'; name.textContent = text(task.name || task.id); main.appendChild(name);
      var meta = document.createElement('div'); meta.className = 'compiler-task-meta'; meta.appendChild(badge(statusNames[task.status] || task.status || '未知', statusKind(task.status))); if (task.platform) meta.appendChild(badge(text(task.platform).toUpperCase())); main.appendChild(meta);
      var phase = document.createElement('p'); phase.className = 'compiler-task-phase'; phase.textContent = text(task.phase || phaseNames[task.status] || ''); main.appendChild(phase);
      if (task.error) { var err = document.createElement('p'); err.className = 'compiler-task-error'; err.textContent = text(task.error); main.appendChild(err); }
      top.appendChild(main); row.appendChild(top); row.addEventListener('click', function () { state.selectedId = task.id; state.logText = ''; state.logTaskId = ''; renderTasks(); renderDetail(); loadLog(task.id); }); list.appendChild(row);
    });
    updateButtons();
  }
  function renderModes() {
    var target = $('compiler-mode-controls');
    if (!target) return;
    clear(target);
    ['s100', 'chroma'].forEach(function (platform) {
      if (!state.modes[platform]) return;
      var label = document.createElement('label'); label.className = 'compiler-mode'; label.textContent = platform.toUpperCase() + ' 模式 ';
      var select = document.createElement('select'); select.dataset.platform = platform; select.setAttribute('aria-label', platform.toUpperCase() + ' 编译模式');
      Object.keys(state.modes[platform]).forEach(function (mode) {
        var option = document.createElement('option'); option.value = mode; option.textContent = state.modes[platform][mode]; select.appendChild(option);
      });
      select.value = state.modeChoices[platform] || 'all';
      select.disabled = state.running || state.submitting || state.uploading;
      select.addEventListener('change', function () { state.modeChoices[platform] = select.value; });
      label.appendChild(select); target.appendChild(label);
    });
  }
  function renderTools() {
    var target = $('compiler-toolbar-hint');
    if (!target || !state.tools) return;
    var names = ['chroma', 's100'].filter(function (key) { return state.tools[key]; });
    if (!names.length) return;
    target.textContent = names.map(function (key) { var tool = state.tools[key] || {}; return key.toUpperCase() + '：' + (tool.reason ? '工具链异常' : tool.available ? '已检测到' : '未找到') + (tool.path ? '（' + tool.path + '）' : ''); }).join('　');
  }
  function renderStages(result) {
    var list = document.createElement('div'); list.className = 'compiler-stage-list';
    var stages = result && Array.isArray(result.stages) ? result.stages : [];
    if (!stages.length) { var none = document.createElement('span'); none.className = 'compiler-muted'; none.textContent = '编译开始后显示阶段。'; list.appendChild(none); return list; }
    stages.forEach(function (stage) { var node = document.createElement('span'); node.className = 'compiler-stage'; node.dataset.ok = stage.ok === true ? 'true' : stage.ok === false ? 'false' : ''; node.textContent = text(stage.stage || '阶段') + (stage.ok === true ? ' · 通过' : stage.ok === false ? ' · 失败' : '') + (stage.returncode != null ? ' · 返回码 ' + stage.returncode : ''); list.appendChild(node); });
    return list;
  }
  function renderDiagnostics(result) {
    var list = document.createElement('div'); list.className = 'compiler-diagnostics';
    var diagnostics = result && Array.isArray(result.diagnostics) ? result.diagnostics : [];
    if (!diagnostics.length) { var none = document.createElement('span'); none.className = 'compiler-muted'; none.textContent = '没有编译器诊断。'; list.appendChild(none); return list; }
    var groups = [], warnings = new Map();
    diagnostics.forEach(function (diagnostic) {
      var message = text(diagnostic.message);
      if (diagnostic.file && message.indexOf(diagnostic.file) === 0) {
        var suffix = message.slice(diagnostic.file.length);
        if (/^\s*(?:\(\s*\d+\s*\)|:\s*\d+|\s+\d+)\s*:/.test(suffix)) {
          message = suffix.replace(/^\s*(?:\(\s*\d+\s*\)|:\s*\d+|\s+\d+)\s*:\s*/, '');
        }
      }
      var key = JSON.stringify([message, diagnostic.cause, diagnostic.advice]);
      var group = diagnostic.severity === 'warning' && warnings.get(key);
      if (group) { group.items.push(diagnostic); return; }
      group = { diagnostic: diagnostic, message: message, items: [diagnostic] };
      groups.push(group);
      if (diagnostic.severity === 'warning') warnings.set(key, group);
    });
    groups.forEach(function (group) {
      var diagnostic = group.diagnostic, repeated = group.items.length > 1;
      var node = document.createElement('article'); node.className = 'compiler-diagnostic'; node.dataset.severity = text(diagnostic.severity || '');
      var head = document.createElement('strong'); head.textContent = text(diagnostic.severity || '诊断').toUpperCase() + (repeated ? ' · 共 ' + group.items.length + ' 处' : (diagnostic.file ? ' · ' + diagnostic.file : '') + (diagnostic.line != null ? ':' + diagnostic.line : '')); node.appendChild(head);
      if (diagnostic.message) { var message = document.createElement('p'); message.textContent = repeated ? group.message : diagnostic.message; node.appendChild(message); }
      if (diagnostic.cause) { var cause = document.createElement('p'); cause.textContent = '原因：' + diagnostic.cause; node.appendChild(cause); }
      if (diagnostic.advice) { var advice = document.createElement('p'); advice.textContent = '建议：' + diagnostic.advice; node.appendChild(advice); }
      if (repeated) {
        var details = document.createElement('details'), summary = document.createElement('summary');
        summary.textContent = '查看全部位置与原文（' + group.items.length + '）'; details.appendChild(summary);
        group.items.forEach(function (item) {
          var original = document.createElement('p');
          original.textContent = (item.file ? item.file + (item.line != null ? ':' + item.line : '') + ' · ' : '') + text(item.message);
          details.appendChild(original);
        });
        node.appendChild(details);
      }
      list.appendChild(node);
    });
    return list;
  }
  function renderDetail() {
    var body = $('compiler-detail-body'), actions = $('compiler-detail-actions');
    if (!body) return;
    clear(body); var task = taskById(state.selectedId);
    if (!task) { if (actions) actions.hidden = true; var placeholder = document.createElement('div'); placeholder.className = 'compiler-detail-placeholder'; placeholder.textContent = '选择任务查看阶段、日志与诊断。'; body.appendChild(placeholder); return; }
    if (actions) actions.hidden = false;
    var phase = document.createElement('p'); phase.className = 'compiler-muted'; phase.textContent = text(task.phase || phaseNames[task.status] || statusNames[task.status]); body.appendChild(phase);
    if (task.result && task.result.mode) {
      var modeInfo = document.createElement('p'); modeInfo.className = 'compiler-muted';
      modeInfo.textContent = '本次模式：' + ((state.modes[task.platform] || {})[task.result.mode] || task.result.mode) + (task.result.mode === 'all' ? '' : ' · 仅验证所选阶段，下载包含依赖产物'); body.appendChild(modeInfo);
    }
    var stageTitle = document.createElement('h3'); stageTitle.textContent = '编译阶段'; body.appendChild(stageTitle); body.appendChild(renderStages(task.result));
    var diagnosticTitle = document.createElement('h3'); diagnosticTitle.textContent = '编译器诊断'; body.appendChild(diagnosticTitle); body.appendChild(renderDiagnostics(task.result));
    if (task.result && task.result.elapsed != null) { var elapsed = document.createElement('p'); elapsed.className = 'compiler-muted'; elapsed.textContent = '耗时：' + task.result.elapsed + ' 秒'; body.appendChild(elapsed); }
    var logTitle = document.createElement('h3'); logTitle.textContent = '编译日志'; body.appendChild(logTitle); var log = document.createElement('pre'); log.id = 'compiler-log'; log.className = 'compiler-log'; log.textContent = state.logText || '尚无编译日志。'; body.appendChild(log);
    var output = task.result && task.result.outputAvailable; var outputHint = document.createElement('p'); outputHint.className = 'compiler-muted'; outputHint.textContent = output ? '编译输出可下载。' : '暂无可下载的编译输出。'; body.appendChild(outputHint);
    var tools = document.createElement('div'); tools.className = 'compiler-tools'; tools.textContent = '厂商工具状态'; Object.keys(state.tools || {}).forEach(function (key) { var tool = state.tools[key]; var line = document.createElement('div'); line.textContent = key.toUpperCase() + '：' + (tool.reason || (tool.available ? '已检测到' : '未找到')) + (tool.path ? ' · ' + tool.path : ''); tools.appendChild(line); }); body.appendChild(tools);
    var downloadOutput = $('compiler-download-output'); if (downloadOutput) downloadOutput.disabled = !output;
    var startOne = $('compiler-start-one'); if (startOne) startOne.disabled = !canCompileTask(task) || state.running || state.submitting || state.uploading;
  }
  async function loadLog(id) {
    var request = ++state.logRequest;
    state.logTaskId = id;
    state.logText = '';
    if ($('compiler-detail-body')) renderDetail();
    try { var payload = await api('/api/compiler/log?id=' + encodeURIComponent(id)); if (request === state.logRequest && String(state.selectedId) === String(id)) { state.logText = payload && typeof payload === 'object' ? text(payload.text) : text(payload); renderDetail(); } }
    catch (error) { if (request === state.logRequest && String(state.selectedId) === String(id)) { state.logText = '日志读取失败：' + error.message; renderDetail(); } }
  }
  function updateButtons() { renderModes(); var clearButton = $('compiler-clear'); if (clearButton) clearButton.disabled = !state.tasks.length || state.running || state.submitting || state.uploading || state.tasks.some(function (task) { return task.status === 'uploading'; }); var selected = Object.keys(state.checked).filter(function (id) { return state.checked[id] && canCompileTask(taskById(id)); }); var start = $('compiler-start'); if (start) start.disabled = !selected.length || state.running || state.submitting || state.uploading; var pick = $('compiler-pick-folder'); if (pick) pick.disabled = state.uploading || state.submitting; var startOne = $('compiler-start-one'); if (startOne) startOne.disabled = !canCompileTask(taskById(state.selectedId)) || state.running || state.submitting || state.uploading; }
  async function refresh() {
    try {
      var incoming = payloadState(await api('/api/compiler/state'));
      if (Array.isArray(incoming.tasks)) state.tasks = incoming.tasks;
      state.running = !!incoming.running || state.tasks.some(function (task) { return task.status === 'queued' || task.status === 'running'; });
      state.tools = incoming.tools || {};
      state.modes = incoming.modes || {};
      if (!state.selectedId || !taskById(state.selectedId)) state.selectedId = state.tasks[0] ? state.tasks[0].id : '';
      Object.keys(state.checked).forEach(function (id) { if (!taskById(id)) delete state.checked[id]; });
      setText('compiler-connection', '已连接'); var badgeNode = $('compiler-connection'); if (badgeNode) badgeNode.className = 'wb-badge';
      renderTasks(); renderTools(); renderDetail();
      if (state.selectedId && taskById(state.selectedId).status !== 'uploading') await loadLog(state.selectedId);
      if (state.running) schedulePoll();
    } catch (error) { setText('compiler-connection', '未连接'); var badgeNode = $('compiler-connection'); if (badgeNode) badgeNode.className = 'wb-badge wb-badge-danger'; setText('compiler-status', error.message); schedulePoll(); }
  }
  function schedulePoll() { if (state.pollTimer) return; state.pollTimer = setTimeout(function () { state.pollTimer = null; refresh(); }, 1200); }
  async function startIds(ids) {
    if (!ids.length || state.submitting || state.uploading) return;
    state.submitting = true; updateButtons();
    try { var modes = {}; ids.forEach(function (id) { modes[id] = state.modeChoices[(taskById(id) || {}).platform] || 'all'; }); await postJSON('/api/compiler/start', { ids: ids, modes: modes }); setText('compiler-status', '已提交 ' + ids.length + ' 个任务，后台将按队列串行编译。'); await refresh(); }
    catch (error) { setText('compiler-status', '提交编译失败：' + error.message); }
    finally { state.submitting = false; updateButtons(); }
  }
  async function clearHistory() {
    if (state.running || state.submitting || state.uploading || state.tasks.some(function (task) { return task.status === 'uploading'; })) return;
    state.submitting = true; updateButtons();
    try {
      await postJSON('/api/compiler/clear', {});
      state.selectedId = ''; state.checked = {}; state.logText = ''; state.logTaskId = ''; state.logRequest += 1;
      await refresh(); setText('compiler-status', '历史列表已清空，磁盘文件已保留。');
    } catch (error) { setText('compiler-status', '清空失败：' + error.message); }
    finally { state.submitting = false; updateButtons(); }
  }
  async function startSelected() { var ids = Object.keys(state.checked).filter(function (id) { return state.checked[id] && canCompileTask(taskById(id)); }); await startIds(ids); }
  async function startOne() { var task = taskById(state.selectedId); if (task) await startIds([task.id]); }
  async function download(kind) {
    var task = taskById(state.selectedId); if (!task) return;
    try {
      var response = await fetch('/api/compiler/download?id=' + encodeURIComponent(task.id) + '&kind=' + encodeURIComponent(kind), { headers: jsonHeaders() });
      if (!response.ok) throw new Error('HTTP ' + response.status);
      var blob = await response.blob(), url = URL.createObjectURL(blob), anchor = document.createElement('a'); anchor.href = url; anchor.download = text(task.name || task.id) + (kind === 'log' ? '.log' : '.zip'); anchor.click(); setTimeout(function () { URL.revokeObjectURL(url); }, 0);
    } catch (error) { setText('compiler-status', '下载失败：' + error.message); }
  }
  function bind() {
    var dropArea = $('compiler-app'), dragDepth = 0;
    if (dropArea) {
      function fileDrag(event) { return event.dataTransfer && Array.from(event.dataTransfer.types || []).includes('Files'); }
      dropArea.addEventListener('dragenter', function (event) { if (fileDrag(event)) { event.preventDefault(); dragDepth += 1; dropArea.dataset.dragging = 'true'; } });
      dropArea.addEventListener('dragover', function (event) { if (fileDrag(event)) { event.preventDefault(); event.dataTransfer.dropEffect = state.uploading || state.submitting ? 'none' : 'copy'; } });
      dropArea.addEventListener('dragleave', function (event) { if (fileDrag(event)) { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) dropArea.dataset.dragging = 'false'; } });
      dropArea.addEventListener('drop', function (event) {
        event.preventDefault(); dragDepth = 0; dropArea.dataset.dragging = 'false';
        if (!fileDrag(event)) return;
        var entries = Array.from(event.dataTransfer.items || []).filter(function (item) { return item.kind === 'file'; }).map(function (item) { return item.webkitGetAsEntry ? item.webkitGetAsEntry() : null; });
        return addFolder(null, entries);
      });
    }
    if ($('compiler-clear')) $('compiler-clear').addEventListener('click', clearHistory);
    var picker = $('compiler-folder-picker'); if ($('compiler-pick-folder') && picker) { $('compiler-pick-folder').addEventListener('click', function () { picker.click(); }); picker.addEventListener('change', function (event) { addFolder(event.target.files); event.target.value = ''; }); }
    if ($('compiler-select-all')) $('compiler-select-all').addEventListener('click', function () { var candidates = state.tasks.filter(canCompileTask), all = candidates.length && candidates.every(function (task) { return state.checked[task.id]; }); state.tasks.forEach(function (task) { state.checked[task.id] = canCompileTask(task) ? !all : false; }); renderTasks(); });
    if ($('compiler-start')) $('compiler-start').addEventListener('click', startSelected);
    if ($('compiler-start-one')) $('compiler-start-one').addEventListener('click', startOne);
    if ($('compiler-download-log')) $('compiler-download-log').addEventListener('click', function () { download('log'); });
    if ($('compiler-download-output')) $('compiler-download-output').addEventListener('click', function () { download('output'); });
  }
  window.MCUCompiler = { state: function () { return state; }, refresh: refresh, addFolder: addFolder, start: startSelected, startOne: startOne, download: download, groupFiles: groupFiles };
  bind(); refresh();
}());
