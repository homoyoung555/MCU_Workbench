/* HEX to Pattern queue UI. Conversion remains server-owned; this page never burns a device. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var connection = {};
  try { connection = JSON.parse(($('connection') || {}).textContent || '{}'); } catch (_) {}
  var token = typeof connection.token === 'string' ? connection.token : '';
  var state = { profiles: [], options: {}, tasks: [], running: false, selectedId: '', chip: '', profileId: '', checked: {}, uploading: false, submitting: false, pollTimer: null, previewFile: '', previewText: '', previewTaskId: '' };
  var statusNames = { ready: '待转换', queued: '排队中', running: '转换中', completed: '已完成', failed: '失败' };

  function text(value) { return value == null ? '' : String(value); }
  function setText(id, value) { var node = $(id); if (node) node.textContent = text(value); }
  function headers(extra) { var result = new Headers(extra || {}); result.set('X-GUI-Session', token); return result; }
  async function api(path, options) {
    var opts = options || {}, response;
    try { response = await fetch(path, Object.assign({}, opts, { headers: headers(opts.headers) })); }
    catch (error) { throw new Error('无法连接服务：' + error.message); }
    if (!response.ok) {
      var message = 'HTTP ' + response.status;
      try { var body = await response.json(); message = body.error || body.message || message; } catch (_) {}
      throw new Error(message);
    }
    if (response.status === 204) return null;
    var type = response.headers && response.headers.get('content-type') || '';
    return type.indexOf('json') >= 0 ? response.json() : response.text();
  }
  function postJSON(path, body) { return api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) }); }
  function payloadState(value) { return value && value.state ? value.state : value || {}; }
  function taskById(id) { return state.tasks.find(function (task) { return String(task.id) === String(id); }) || null; }
  function profileById(id) { return state.profiles.find(function (profile) { return String(profile.id) === String(id); }) || null; }
  function activeProfiles() { return state.profiles.filter(function (profile) { return text(profile.chip) === text(state.chip); }); }
  function selectedProfile() { return profileById(state.profileId); }
  function currentOptions() { var profile = selectedProfile(); if (!profile) return {}; if (!state.options[profile.id]) state.options[profile.id] = {pins: profile.pins.slice(), verify: !!profile.verify, outputPlatform: profile.platform}; return state.options[profile.id]; }
  function canStart(task) { return !!task && (task.status === 'ready' || task.status === 'failed' || task.status === 'completed') && !!selectedProfile() && selectedProfile().enabled !== false; }
  function clear(node) { while (node && node.firstChild) node.removeChild(node.firstChild); }
  function badge(value, kind) { var node = document.createElement('span'); node.className = 'hex-badge'; node.dataset.kind = kind || ''; node.textContent = text(value); return node; }
  function statusKind(status) { return status === 'completed' ? 'success' : status === 'failed' ? 'danger' : status === 'queued' || status === 'running' ? 'warn' : ''; }
  function formatBytes(value) { var bytes = Number(value); return Number.isFinite(bytes) && bytes >= 1024 ? (bytes / (bytes >= 1024 * 1024 ? 1024 * 1024 : 1024)).toFixed(bytes >= 1024 * 1024 ? 1 : 0) + (bytes >= 1024 * 1024 ? ' MiB' : ' KiB') : (Number.isFinite(bytes) ? bytes + ' B' : ''); }
  function preserveSelection() {
    var chips = state.profiles.map(function (p) { return text(p.chip); }).filter(Boolean).filter(function (chip, i, list) { return list.indexOf(chip) === i; });
    if (chips.indexOf(text(state.chip)) < 0) state.chip = chips[0] || '';
    var profiles = activeProfiles();
    if (!profiles.some(function (p) { return String(p.id) === String(state.profileId) && p.enabled !== false; })) {
      var fallback = profiles.find(function (p) { return p.enabled !== false; }) || profiles[0];
      state.profileId = fallback ? fallback.id : '';
    }
  }
  function renderProfiles() {
    preserveSelection();
    var chip = $('hex-chip'), profile = $('hex-profile');
    if (!chip || !profile) return;
    clear(chip); clear(profile);
    var chips = state.profiles.map(function (p) { return text(p.chip); }).filter(Boolean).filter(function (v, i, a) { return a.indexOf(v) === i; });
    chips.forEach(function (value) { var option = document.createElement('option'); option.value = value; option.textContent = value; chip.appendChild(option); });
    chip.value = state.chip;
    activeProfiles().forEach(function (item) {
      var option = document.createElement('option'); option.value = text(item.id); option.textContent = text(item.label || item.id) + ' · ' + text(item.mode) + ' / ' + text(item.platform); option.disabled = item.enabled === false; if (item.reason) option.title = text(item.reason); profile.appendChild(option);
    });
    profile.value = text(state.profileId); profile.disabled = !activeProfiles().length || state.running || state.submitting || state.uploading;
    chip.disabled = !chips.length || state.running || state.submitting || state.uploading;
    renderProfileInfo();
  }
  function renderProfileInfo() {
    var node = $('hex-profile-info'); if (!node) return; clear(node); var profile = selectedProfile();
    if (!profile) { node.textContent = '暂无可用芯片版本。'; return; }
    var title = document.createElement('strong'); title.textContent = text(profile.chip) + ' · ' + text(profile.label || profile.id); node.appendChild(title);
    [['模式', profile.mode], ['平台', profile.platform], ['时序', profile.timeset], ['页大小', profile.pageSize], ['擦除', profile.erase]].forEach(function (entry) { if (entry[1] == null || entry[1] === '') return; var span = document.createElement('span'); span.textContent = entry[0] + '：' + (Array.isArray(entry[1]) ? entry[1].join(', ') : text(entry[1])); node.appendChild(span); });
    var options = currentOptions(), busy = state.running || state.submitting || state.uploading;
    var controls = document.createElement('div'); controls.className = 'hex-options';
    var formatLabel = document.createElement('label'); formatLabel.textContent = '输出格式'; var format = document.createElement('select'); format.id = 'hex-output-platform';
    [['chroma','Chroma PAT'],['s100','S100 SD'],['both','PAT + SD']].forEach(function(item) { if (profile.platform === 's100' && item[0] !== 's100') return; var option = document.createElement('option'); option.value = item[0]; option.textContent = item[1]; format.appendChild(option); });
    format.value = options.outputPlatform || profile.platform; format.disabled = busy || profile.enabled === false; format.addEventListener('change', function () { options.outputPlatform = format.value; }); formatLabel.appendChild(format); controls.appendChild(formatLabel);
    profile.pins.forEach(function (pin, index) {
      var label = document.createElement('label'); label.textContent = pin + ' → ';
      var input = document.createElement('input'); input.type = 'text'; input.value = options.pins[index]; input.maxLength = 64;
      input.dataset.pinIndex = String(index); input.setAttribute('aria-label', '原管脚 ' + pin + ' 映射名称'); input.disabled = busy || profile.enabled === false;
      input.addEventListener('input', function () { options.pins[index] = input.value; }); label.appendChild(input); controls.appendChild(label);
    });
    var reset = document.createElement('button'); reset.type = 'button'; reset.id = 'hex-reset-pins'; reset.className = 'wb-button'; reset.textContent = '恢复默认管脚'; reset.disabled = busy || profile.enabled === false;
    reset.addEventListener('click', function () { options.pins = profile.pins.slice(); renderProfileInfo(); }); controls.appendChild(reset);
    var verifyLabel = document.createElement('label');
    var verify = document.createElement('input'); verify.type = 'checkbox'; verify.id = 'hex-verify'; verify.checked = options.verify;
    verify.disabled = busy || profile.enabled === false || !profile.verify;
    verify.addEventListener('change', function () { options.verify = verify.checked; });
    verifyLabel.appendChild(verify); var caption = document.createElement('span'); caption.textContent = '写入后数据读回校验'; verifyLabel.appendChild(caption); controls.appendChild(verifyLabel);
    if (!profile.verify) { var unavailable = document.createElement('span'); unavailable.textContent = '原版本未启用读回，校验不可开启'; controls.appendChild(unavailable); }
    node.appendChild(controls);
    var timingNote = document.createElement('span'); timingNote.textContent = 'S100：TSn 对应 G1_n，请在工程中使用相同周期和边沿。'; node.appendChild(timingNote);
    var scope = document.createElement('span'); scope.textContent = '输入需为连续地址段，当前已验证相对地址范围为 0～64 KiB；Flash 按页、SRAM 按 4 字节对齐。'; node.appendChild(scope);
    if (profile.enabled === false || profile.reason) { var reason = document.createElement('span'); reason.className = 'hex-profile-reason'; reason.textContent = profile.enabled === false ? '不可用' + (profile.reason ? '：' + text(profile.reason) : '') : text(profile.reason); node.appendChild(reason); }
  }
  function renderTasks() {
    var list = $('hex-task-list'); if (!list) return; clear(list); setText('hex-task-count', state.tasks.length + ' 个');
    if (!state.tasks.length) { var empty = document.createElement('div'); empty.className = 'hex-empty'; empty.textContent = '尚未添加 HEX 文件。'; list.appendChild(empty); updateButtons(); return; }
    state.tasks.forEach(function (task) {
      var row = document.createElement('article'); row.className = 'hex-task'; row.dataset.taskId = text(task.id); row.setAttribute('aria-current', String(task.id) === String(state.selectedId) ? 'true' : 'false');
      var top = document.createElement('div'); top.className = 'hex-task-top'; var check = document.createElement('input'); check.type = 'checkbox'; check.checked = !!state.checked[task.id]; check.disabled = !canStart(task); check.setAttribute('aria-label', '选择任务 ' + text(task.name || task.id)); check.addEventListener('click', function (event) { event.stopPropagation(); state.checked[task.id] = check.checked; updateButtons(); }); top.appendChild(check);
      var main = document.createElement('div'); main.className = 'hex-task-main'; var name = document.createElement('div'); name.className = 'hex-task-name'; name.textContent = text(task.name || task.id); main.appendChild(name); var meta = document.createElement('div'); meta.className = 'hex-task-meta'; meta.appendChild(badge(statusNames[task.status] || task.status || '未知', statusKind(task.status))); if (task.bytes != null) meta.appendChild(badge(formatBytes(task.bytes))); if (task.profileId) meta.appendChild(badge(text(task.profileId))); main.appendChild(meta); if (task.error) { var error = document.createElement('p'); error.className = 'hex-task-error'; error.textContent = text(task.error); main.appendChild(error); } if (task.summary && task.summary.segments) { var summary = document.createElement('p'); summary.className = 'hex-task-summary'; summary.textContent = '段数：' + task.summary.segments.length; main.appendChild(summary); } top.appendChild(main); row.appendChild(top); row.addEventListener('click', function () { state.selectedId = task.id; state.previewFile = ''; state.previewText = ''; state.previewTaskId = ''; renderTasks(); renderDetail(); }); list.appendChild(row);
    });
    updateButtons();
  }
  function renderDetail() {
    var body = $('hex-detail-body'), actions = $('hex-detail-actions'); if (!body) return; clear(body); var task = taskById(state.selectedId); if (!task) { if (actions) actions.hidden = true; var placeholder = document.createElement('div'); placeholder.className = 'hex-placeholder'; placeholder.textContent = '选择任务查看结果、日志与文件预览。'; body.appendChild(placeholder); return; }
    if (actions) actions.hidden = false; var grid = document.createElement('div'); grid.className = 'hex-result-grid'; var summary = document.createElement('div'); summary.className = 'hex-summary'; var summaryTitle = document.createElement('strong'); summaryTitle.textContent = '转换摘要'; summary.appendChild(summaryTitle); [['状态', statusNames[task.status] || task.status], ['输入字节', formatBytes(task.bytes)], ['版本', task.profileId], ['输出格式', task.profile && (task.profile.outputPlatform || task.profile.platform)], ['管脚', task.profile && task.profile.pins.join(', ')], ['数据读回校验', task.profile ? (task.profile.verify ? '开启' : '关闭') : '']].forEach(function (item) { if (item[1] == null || item[1] === '') return; var line = document.createElement('div'); line.textContent = item[0] + '：' + text(item[1]); summary.appendChild(line); }); if (task.summary && task.summary.segments) { var segments = document.createElement('div'); segments.textContent = '地址段：' + task.summary.segments.map(function (s) { return text(s.start) + '–' + text(s.end); }).join(', '); summary.appendChild(segments); } grid.appendChild(summary);
    var files = document.createElement('div'); files.className = 'hex-files'; var filesTitle = document.createElement('strong'); filesTitle.textContent = '输出文件'; files.appendChild(filesTitle); var outputs = task.result && Array.isArray(task.result.files) ? task.result.files : []; if (!outputs.length) { var none = document.createElement('span'); none.className = 'hex-muted'; none.textContent = '暂无输出文件。'; files.appendChild(none); } outputs.forEach(function (item) { var file = document.createElement('div'); file.className = 'hex-file'; var button = document.createElement('button'); button.type = 'button'; button.textContent = text(item.name); button.dataset.previewFile = text(item.name); button.addEventListener('click', function () { loadPreview(task.id, item.name); }); file.appendChild(button); var size = document.createElement('span'); size.className = 'hex-muted'; size.textContent = formatBytes(item.size); file.appendChild(size); files.appendChild(file); }); grid.appendChild(files); body.appendChild(grid);
    var previewTitle = document.createElement('h3'); previewTitle.textContent = '文件预览'; body.appendChild(previewTitle); var preview = document.createElement('pre'); preview.className = 'hex-preview'; preview.textContent = state.previewTaskId === String(task.id) && state.previewFile ? state.previewText || '正在读取预览…' : '点击输出文件查看文本预览。'; body.appendChild(preview);
    var logTitle = document.createElement('h3'); logTitle.textContent = '转换日志'; body.appendChild(logTitle); var log = document.createElement('pre'); log.className = 'hex-log'; log.textContent = Array.isArray(task.logs) ? task.logs.map(text).join('\n') || '暂无日志。' : text(task.logs || '暂无日志。'); body.appendChild(log);
    var download = $('hex-download'); if (download) download.disabled = !(task.result && Array.isArray(task.result.files) && task.result.files.length) || task.status !== 'completed';
  }
  async function loadPreview(taskId, fileName) { state.previewTaskId = String(taskId); state.previewFile = text(fileName); state.previewText = '正在读取预览…'; renderDetail(); try { var value = await api('/api/hex/preview?task=' + encodeURIComponent(taskId) + '&file=' + encodeURIComponent(fileName)); if (state.previewTaskId === String(taskId) && state.previewFile === text(fileName)) { state.previewText = typeof value === 'string' ? value : text(value); renderDetail(); } } catch (error) { state.previewText = '预览读取失败：' + error.message; renderDetail(); } }
  function updateButtons() { var selected = Object.keys(state.checked).filter(function (id) { return state.checked[id] && canStart(taskById(id)); }); var start = $('hex-start'); if (start) start.disabled = !selected.length || state.running || state.submitting || state.uploading; var clearButton = $('hex-clear'); if (clearButton) clearButton.disabled = !state.tasks.length || state.running || state.submitting || state.uploading; }
  function schedulePoll() { if (state.pollTimer) return; state.pollTimer = setTimeout(function () { state.pollTimer = null; refresh(); }, 1200); }
  async function refresh() { try { var incoming = payloadState(await api('/api/hex/state')); if (Array.isArray(incoming.profiles)) state.profiles = incoming.profiles; if (Array.isArray(incoming.tasks)) state.tasks = incoming.tasks; state.running = !!incoming.running || state.tasks.some(function (task) { return task.status === 'queued' || task.status === 'running'; }); if (!state.selectedId || !taskById(state.selectedId)) state.selectedId = state.tasks[0] ? state.tasks[0].id : ''; Object.keys(state.checked).forEach(function (id) { if (!taskById(id)) delete state.checked[id]; }); renderProfiles(); renderTasks(); renderDetail(); setText('hex-connection', '已连接'); var conn = $('hex-connection'); if (conn) conn.className = 'wb-badge'; if (state.running) schedulePoll(); } catch (error) { var conn = $('hex-connection'); if (conn) { conn.className = 'wb-badge wb-badge-danger'; conn.textContent = '未连接'; } setText('hex-status', error.message); var status = $('hex-status'); if (status) status.dataset.kind = 'error'; schedulePoll(); } }
  async function uploadFile(file) { var name = file && file.name || ''; if (!name) return; setText('hex-status', '正在上传「' + name + '」…'); var result = await api('/api/hex/input', { method: 'POST', headers: { 'Content-Type': 'application/octet-stream', 'X-File-Name': encodeURIComponent(name) }, body: file }); var task = result && (result.task || result); if (!task || !task.id) throw new Error('服务未返回HEX任务编号'); }
  async function addFiles(files) { if (state.uploading || state.submitting) return; var selected = Array.prototype.filter.call(files || [], function (file) { return file && file.name; }); if (!selected.length) { setText('hex-status', '没有可上传的 HEX 文件。'); return; } state.uploading = true; var failed = []; var status = $('hex-status'); if (status) status.dataset.kind = ''; updateButtons(); try { for (var i = 0; i < selected.length; i += 1) { try { await uploadFile(selected[i]); } catch (error) { failed.push('「' + selected[i].name + '」：' + error.message); } } await refresh(); if (failed.length) { setText('hex-status', '上传失败：' + failed.join('；')); if (status) status.dataset.kind = 'error'; } else setText('hex-status', '已添加 ' + selected.length + ' 个 HEX 任务。'); } finally { state.uploading = false; renderProfiles(); updateButtons(); } }
  async function startIds(ids) { if (!ids.length || state.submitting || state.uploading || !selectedProfile() || selectedProfile().enabled === false) return; state.submitting = true; state.previewTaskId = ''; state.previewFile = ''; state.previewText = ''; updateButtons(); try { await postJSON('/api/hex/start', { taskIds: ids, profileId: state.profileId, pins: currentOptions().pins.slice(), verify: currentOptions().verify, outputPlatform: currentOptions().outputPlatform }); setText('hex-status', '已提交 ' + ids.length + ' 个任务，后台将按队列串行转换。'); var status = $('hex-status'); if (status) status.dataset.kind = ''; await refresh(); } catch (error) { setText('hex-status', '提交转换失败：' + error.message); var status = $('hex-status'); if (status) status.dataset.kind = 'error'; } finally { state.submitting = false; renderProfiles(); updateButtons(); } }
  async function startSelected() { await startIds(Object.keys(state.checked).filter(function (id) { return state.checked[id] && canStart(taskById(id)); })); }
  async function clearHistory() { if (state.running || state.submitting || state.uploading) return; state.submitting = true; updateButtons(); try { await postJSON('/api/hex/clear', {}); state.selectedId = ''; state.checked = {}; state.previewFile = ''; state.previewText = ''; await refresh(); setText('hex-status', '历史列表已清空。'); } catch (error) { setText('hex-status', '清空失败：' + error.message); } finally { state.submitting = false; renderProfiles(); updateButtons(); } }
  async function download() { var task = taskById(state.selectedId); if (!task) return; try { var response = await fetch('/api/hex/download?task=' + encodeURIComponent(task.id), { headers: headers() }); if (!response.ok) throw new Error('HTTP ' + response.status); var blob = await response.blob(), url = URL.createObjectURL(blob), anchor = document.createElement('a'); anchor.href = url; anchor.download = text(task.name || task.id).replace(/\.hex$/i, '') + '.zip'; anchor.click(); setTimeout(function () { URL.revokeObjectURL(url); }, 0); } catch (error) { setText('hex-status', '下载失败：' + error.message); } }
  function bind() { var app = $('hex-app'), depth = 0; function isFileDrag(event) { return event.dataTransfer && Array.prototype.indexOf.call(event.dataTransfer.types || [], 'Files') >= 0; } if (app) { app.addEventListener('dragenter', function (event) { if (isFileDrag(event)) { event.preventDefault(); depth += 1; app.dataset.dragging = 'true'; } }); app.addEventListener('dragover', function (event) { if (isFileDrag(event)) { event.preventDefault(); event.dataTransfer.dropEffect = state.uploading || state.submitting ? 'none' : 'copy'; } }); app.addEventListener('dragleave', function (event) { if (isFileDrag(event)) { depth = Math.max(0, depth - 1); if (!depth) app.dataset.dragging = 'false'; } }); app.addEventListener('drop', function (event) { if (!isFileDrag(event)) return; event.preventDefault(); depth = 0; app.dataset.dragging = 'false'; addFiles(event.dataTransfer.files); }); } var picker = $('hex-picker'); if ($('hex-pick') && picker) { $('hex-pick').addEventListener('click', function () { picker.click(); }); picker.addEventListener('change', function (event) { addFiles(event.target.files); event.target.value = ''; }); } if ($('hex-chip')) $('hex-chip').addEventListener('change', function (event) { state.chip = event.target.value; renderProfiles(); renderTasks(); }); if ($('hex-profile')) $('hex-profile').addEventListener('change', function (event) { state.profileId = event.target.value; renderProfileInfo(); renderTasks(); }); if ($('hex-select-all')) $('hex-select-all').addEventListener('click', function () { var candidates = state.tasks.filter(canStart), all = candidates.length && candidates.every(function (task) { return state.checked[task.id]; }); state.tasks.forEach(function (task) { state.checked[task.id] = canStart(task) ? !all : false; }); renderTasks(); }); if ($('hex-start')) $('hex-start').addEventListener('click', startSelected); if ($('hex-clear')) $('hex-clear').addEventListener('click', clearHistory); if ($('hex-download')) $('hex-download').addEventListener('click', download); }
  window.MCUHex = { assistantSnapshot: function () { if (!selectedProfile()) return null; return {request: {taskIds: Object.keys(state.checked).filter(function(id){return state.checked[id] && canStart(taskById(id));}), profileId:state.profileId, pins:currentOptions().pins.slice(), verify:currentOptions().verify, outputPlatform:currentOptions().outputPlatform}}; }, state: function () { return state; }, refresh: refresh, addFiles: addFiles, start: startSelected, download: download };
  bind(); refresh();
}());
