(function () {
  'use strict';

  var $ = function (selector) { return document.querySelector(selector); };
  var $$ = function (selector) { return Array.prototype.slice.call(document.querySelectorAll(selector)); };
  var connection = {};
  try { connection = JSON.parse($('#connection') ? $('#connection').textContent : '{}'); } catch (_) { connection = {}; }
  var token = typeof connection.token === 'string' ? connection.token : '';
  var columns = [
    { key: 'addr', label: 'addr' }, { key: 'data', label: 'data' },
    { key: 'step', label: 'step' }, { key: 'reset value', label: 'reset value' }, { key: 'type', label: 'type' },
    { key: 'continue', label: 'continue' }, { key: 'description', label: 'description' }
  ];
  var state = { documents: [], config: { chip: 'PT104', pins: { swc: 'PA14', swd: 'PA13', reset: 'NRST', trig: 'TRIGPIN' } }, generations: [], materials: {}, documentId: '', pattern: '', selectedRowId: '', dirty: false, configDirty: false, busy: false, previewKey: '' };
  var checkedPatterns = new Map(), lastBatch = null, hiddenGenerations = new Set();
  try { hiddenGenerations = new Set(JSON.parse(localStorage.getItem('swd-hidden-generations') || '[]')); } catch (_) {}
  var cacheCatalog = [{ id: 'py32f420', label: 'PY32F420', sha256: 'c068e728cdc121cce63abbb909cdb9a50e1bc2dd19c2e2bcfa1fab8c2ebcb2fa', endpoint: '/api/swd/cache' }];
  var toastTimer = null, newRowNumber = 0, registerPicker = null, changedCells = {};
  var authoring = null, draggedRegister = '', floatingDrag = null, draggedStep = null, dragScrollTimer = null;
  var assistantUndo = null, assistantApplied = new Set();
  var draftFields = { 'swd-step-addr': 'addr', 'swd-step-data': 'data', 'swd-step-shift': 'step', 'swd-step-reset': 'reset value', 'swd-step-continue': 'continue', 'swd-step-type': 'type', 'swd-step-description': 'description' };

  function esc(value) { return String(value == null ? '' : value).replace(/[&<>"']/g, function (ch) { return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch]; }); }
  function notify(message) { var el = $('#swd-toast'); if (!el) return; el.textContent = message; el.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(function () { el.hidden = true; }, 3600); }
  function setText(id, text) { var el = $('#' + id); if (el) el.textContent = text || ''; }
  function setStatus(id, text, kind) { var el = $('#' + id); if (!el) return; el.className = 'swd-status swd-hint' + (kind ? ' ' + kind : ''); el.textContent = text || ''; }
  function jsonBody(body) { return { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) }; }

  async function api(path, options) {
    var opts = options || {}, headers = new Headers(opts.headers || {});
    headers.set('X-GUI-Session', token);
    var response;
    try { response = await fetch(path, Object.assign({}, opts, { headers: headers })); } catch (error) { throw new Error('无法连接服务：' + error.message); }
    if (!response.ok) {
      var message = 'HTTP ' + response.status;
      try { var body = await response.json(); message = body.error || body.message || message; } catch (_) {}
      throw new Error(message);
    }
    if (response.status === 204) return null;
    var type = response.headers.get('content-type') || '';
    return type.indexOf('json') >= 0 ? response.json() : response.text();
  }
  function payloadState(payload) { return payload && payload.state ? payload.state : (payload || {}); }
  function applyState(payload, keepDrafts) {
    var incoming = payloadState(payload);
    if (Array.isArray(incoming.documents) && !(keepDrafts && state.dirty)) state.documents = incoming.documents;
    if (incoming.config) state.config = Object.assign({}, state.config, incoming.config, { pins: Object.assign({}, state.config.pins, incoming.config.pins || {}) });
    if (Array.isArray(incoming.generations)) state.generations = incoming.generations;
    if (Array.isArray(incoming.materials)) state.materials = Object.assign({}, state.materials, { materials: incoming.materials });
    else if (incoming.materials && typeof incoming.materials === 'object') state.materials = incoming.materials;
    ['registers', 'conflicts', 'confirmations'].forEach(function (key) { if (Object.prototype.hasOwnProperty.call(incoming, key)) state.materials[key] = incoming[key]; });
    if (!state.documentId || !state.documents.some(function (doc) { return String(doc.id) === String(state.documentId); })) state.documentId = state.documents[0] ? state.documents[0].id : '';
    var doc = selectedDocument();
    var patterns = patternNames(doc);
    if (!state.pattern || patterns.indexOf(state.pattern) < 0) state.pattern = patterns[0] || '';
    renderAll();
  }
  function selectedDocument() { return state.documents.find(function (doc) { return String(doc.id) === String(state.documentId); }) || null; }
  function patternNames(doc) {
    if (!doc) return [];
    var names = Array.isArray(doc.patterns) ? doc.patterns.slice() : [];
    (doc.rows || []).forEach(function (row) { if (row.pattern != null && String(row.pattern) && names.indexOf(String(row.pattern)) < 0) names.push(String(row.pattern)); });
    return names;
  }
  function rowsForPattern(doc) {
    var rows = (doc && Array.isArray(doc.rows)) ? doc.rows : [], current = '';
    return rows.filter(function (row) {
      if (row.pattern != null && String(row.pattern).trim()) current = String(row.pattern);
      return !state.pattern || current === String(state.pattern);
    });
  }
  function rowId(row, index) { return row && row.row != null ? row.row : (row && row._uiRowId ? row._uiRowId : (row && row.id != null ? row.id : index + 1)); }
  function editRow(row, key, value) { row[key] = value; changedCells[rowId(row, 0) + '|' + key] = true; state.dirty = true; renderProvenance(); updateButtons(); setText('swd-editor-state', '有未保存修改'); }
  function provenanceLabel(doc) {
    var value = doc && doc.provenance || {}, status = value.status || 'unknown';
    if (state.dirty || draftHasChanges()) return '当前草稿已修改；已保存来源状态仅对应保存版本';
    if (status === 'consistent') return 'AI 来源元数据一致（未签名，未验证）' + (value.productProfileId ? ' · ' + value.productProfileId : '');
    if (status === 'missing') return '无 AI 来源元数据（未验证）';
    if (status === 'modified') return 'AI 来源已修改，历史验证不适用';
    return 'AI 来源未知，不能据此信任或复用验证';
  }
  function renderProvenance() { var doc = selectedDocument(); setText('swd-document-provenance', doc ? provenanceLabel(doc) : ''); }
  function renderDocuments() {
    var list = $('#swd-document-list'), doc = selectedDocument();
    list.innerHTML = state.documents.length ? state.documents.map(function (item) { return '<option value="' + esc(item.id) + '">' + esc(item.name || item.id) + '</option>'; }).join('') : '<option value="">尚未载入 Excel</option>';
    list.value = state.documentId;
    setText('swd-document-count', doc ? patternNames(doc).length + ' 个 Pattern' : '');
    renderProvenance();
  }
  function checkedForDocument() {
    var key = String(state.documentId), names = patternNames(selectedDocument()), checked = checkedPatterns.get(key) || new Set();
    checked.forEach(function (name) { if (names.indexOf(name) < 0) checked.delete(name); });
    checkedPatterns.set(key, checked); return checked;
  }
  function generationNames() {
    var names = patternNames(selectedDocument()), scope = $('#swd-generation-scope').value;
    return scope === 'all' ? names : scope === 'selected' ? names.filter(function (name) { return checkedForDocument().has(name); }) : names.filter(function (name) { return name === state.pattern; });
  }
  function renderConfig() {
    if (state.configDirty) return;
    var config = state.config || {}, pins = config.pins || {};
    $('#swd-chip').value = config.chip || 'PT104';
    $('#swd-pin-swc').value = pins.swc || '';
    $('#swd-pin-swd').value = pins.swd || '';
    $('#swd-pin-reset').value = pins.reset || '';
    $('#swd-pin-trig').value = pins.trig || '';
  }
  function renderPatternList() {
    var query = $('#swd-pattern-search').value.trim().toLowerCase(), checked = checkedForDocument();
    setText('swd-pattern-selection', '已勾选 ' + checked.size + ' 项');
    $('#swd-pattern-list').innerHTML = patternNames(selectedDocument()).filter(function (name) { return name.toLowerCase().indexOf(query) >= 0; }).map(function (name) {
      return '<div class="swd-pattern-choice"><input type="checkbox" data-pattern-check="' + esc(name) + '" aria-label="勾选 ' + esc(name) + '" ' + (checked.has(name) ? 'checked ' : '') + (state.busy ? 'disabled ' : '') + '><button type="button" class="swd-pattern-item" data-pattern-name="' + esc(name) + '" aria-current="' + (name === state.pattern) + '">' + esc(name) + '</button></div>';
    }).join('') || '<div class="swd-empty">没有匹配的 Pattern。</div>';
  }
  function renderEditor() {
    var doc = selectedDocument(), select = $('#swd-pattern'), body = $('#swd-step-body');
    var names = patternNames(doc);
    select.disabled = !doc;
    select.innerHTML = doc ? (names.length ? names : ['']).map(function (name) { return '<option value="' + esc(name) + '">' + esc(name || '全部步骤') + '</option>'; }).join('') : '<option value="">请先选择步骤文件</option>';
    select.value = state.pattern;
    var enabled = !!doc;
    ['swd-add-row', 'swd-delete-row', 'swd-save', 'swd-download-excel', 'swd-generate'].forEach(function (id) { $('#' + id).disabled = !enabled; });
    setText('swd-editor-state', !doc ? '未选择文件' : (state.dirty ? '有未保存修改' : '已保存'));
    if (!doc) { body.innerHTML = '<tr><td colspan="8" class="swd-empty">载入 Excel 或创建 Pattern。</td></tr>'; return; }
    var rows = rowsForPattern(doc);
    if (!rows.length) { body.innerHTML = '<tr><td colspan="8" class="swd-empty">当前 Pattern 没有步骤。</td></tr>'; return; }
    body.innerHTML = rows.map(function (row, index) {
      var id = rowId(row, index);
      var fields = columns.map(function (column) {
        var control = '<input class="cell-input" type="text" readonly ' + (state.busy ? 'disabled ' : '') + 'title="双击或按 F2 编辑" data-row-id="' + esc(id) + '" data-field="' + esc(column.key) + '" value="' + esc(row[column.key]) + '" aria-label="' + esc(column.label + ' row ' + id) + '">';
        return '<td class="editable' + (changedCells[id + '|' + column.key] ? ' swd-changed' : '') + '">' + control + '</td>';
      }).join('');
      return '<tr data-row-id="' + esc(id) + '" class="' + (String(id) === String(state.selectedRowId) ? 'swd-selected-row' : '') + '"><td><button type="button" class="swd-row-number" data-select-row="' + esc(id) + '" title="选择第 ' + (index + 1) + ' 步">' + (index + 1) + '</button></td>' + fields + '</tr>';
    }).join('');
  }
  function generationStale(generation) {
    if (generation.stale) return true;
    var doc = state.documents.find(function (item) { return String(item.id) === String(generation.documentId); });
    return !!(doc && generation.revision != null && doc.revision != null && String(generation.revision) !== String(doc.revision));
  }
  function renderGenerations() {
    var list = $('#swd-generation-list');
    var visible = state.generations.filter(function (item) { return !hiddenGenerations.has(item.id); });
    $('#swd-generation-clear').disabled = state.busy || !visible.length;
    if (!visible.length) { list.innerHTML = '<div class="swd-empty">生成完成后在这里下载或预览。</div>'; return; }
    list.innerHTML = visible.slice().reverse().map(function (generation) {
      var stale = generationStale(generation), files = Array.isArray(generation.files) ? generation.files : [];
      return '<article class="swd-generation' + (stale ? ' swd-is-stale' : '') + '"><div class="swd-row swd-between"><h3>' + esc(generation.pattern || '') + '</h3><span class="wb-badge ' + (stale ? 'wb-badge-danger' : '') + '">' + (stale ? '已过期' : '当前') + '</span></div><p>rev ' + esc(generation.revision == null ? '' : generation.revision) + (generation.id ? ' · ' + esc(generation.id) : '') + '</p><div class="swd-files">' + (files.length ? files.map(function (file) { var path = file.path || file.name || ''; return '<div class="swd-file"><span class="swd-file-name">' + esc(file.platform || '') + ' / ' + esc(path) + '</span><span class="swd-file-actions"><button type="button" class="wb-button" data-preview-generation="' + esc(generation.id) + '" data-preview-file="' + esc(path) + '">预览</button><button type="button" class="wb-button" data-download-generation="' + esc(generation.id) + '" data-download-file="' + esc(path) + '">下载</button></span></div>'; }).join('') : '<div class="swd-empty">没有可下载文件。</div>') + '</div></article>';
    }).join('');
  }
  function materialRecords() {
    var value = state.materials || {};
    return Array.isArray(value) ? value : (value.materials || value.documents || value.files || value.items || []);
  }
  function sourceRecords(value) {
    return (value.registers || []).reduce(function (all, register) { return all.concat(register.sources || []); }, []);
  }
  function sourceLabel(value, source) {
    if (typeof source === 'string') {
      var found = sourceRecords(value).find(function (item) { return item.id === source; });
      source = found || { id: source };
    }
    var material = materialRecords().find(function (item) { return item.id === source.materialId; });
    var name = material && (material.originalName || material.name) || source.file || source.source || source.materialId || source.id || '来源';
    var detail = source.peripheral && source.name ? ' · ' + source.peripheral + '.' + source.name : '';
    return name + detail;
  }
  function readable(value) { return typeof value === 'string' ? value : JSON.stringify(value); }
  function renderMaterials() {
    var records = materialRecords(), value = state.materials || {}, list = $('#swd-material-list');
    setText('swd-material-count', records.length + ' 个文件');
    list.innerHTML = records.length ? records.map(function (item) { return '<div class="swd-material-item"><strong>' + esc(item.name || item.filename || item.originalName || item.id || '') + '</strong><small>' + esc(item.kind || item.type || item.sheet || '') + (item.revision != null ? ' · rev ' + esc(item.revision) : '') + '</small></div>'; }).join('') : '<div class="swd-empty">尚未导入资料。</div>';
    $('#swd-cache-list').innerHTML = cacheCatalog.map(function (cache) { var loaded = records.some(function (item) { return item.sha256 === cache.sha256; }); return '<div class="swd-cache-entry"><strong>' + esc(cache.label) + '</strong><small>' + (loaded ? '已载入' : '可载入') + '</small><button type="button" class="wb-button" data-cache-id="' + esc(cache.id) + '" ' + (loaded || state.busy ? 'disabled' : '') + '>载入</button></div>'; }).join('');
    var registers = value.registers || [], sourceMarkup = registers.map(function (item) { var sources = (item.sources || []).map(function (source) { return sourceLabel(value, source); }).join('，'); return (item.address || item.name || '') + ' ← ' + sources; });
    $('#swd-material-columns').innerHTML = sourceMarkup.length ? '<p><strong>列来源</strong>：' + esc(sourceMarkup.join('；')) + '</p>' : '';
    var conflicts = value.conflicts || [], confirmations = value.confirmations || {};
    $('#swd-material-conflicts').innerHTML = conflicts.length ? conflicts.map(function (item) {
      var id = item.id == null ? '' : String(item.id), resolved = confirmations[id], sources = item.sourceIds || item.sources || [], values = Array.isArray(item.values) ? item.values : [item.values].filter(function (value) { return value != null; });
      return '<div class="swd-conflict"><strong>冲突：' + esc(item.kind || readable(item.field) || id) + '</strong><ul><li>' + esc(item.address || readable(item.field) || '') + (values.length ? ' · 值：' + esc(values.map(readable).join(' / ')) : '') + '</li><li>来源：' + esc(sources.map(function (source) { return sourceLabel(value, source); }).join('、')) + '</li></ul>' + (resolved ? '<p>已确认保留' + (resolved.sourceId ? '：' + esc(sourceLabel(value, resolved.sourceId)) : '') + (resolved.note ? '，备注：' + esc(resolved.note) : '') + '</p>' : '<label>保留来源<select class="swd-select" data-conflict-source="' + esc(id) + '">' + (sources.length ? sources.map(function (source) { var sourceId = typeof source === 'string' ? source : (source.id || source.sourceId || ''); return '<option value="' + esc(sourceId) + '">' + esc(sourceLabel(value, source)) + '</option>'; }).join('') : '<option value="">由服务端决定</option>') + '</select></label><textarea data-conflict-note="' + esc(id) + '" placeholder="保留理由或来源备注"></textarea><button type="button" class="wb-button wb-primary" data-confirm-material="' + esc(id) + '">确认保留并备注</button>') + '</div>';
    }).join('') : '';
  }
  function updateButtons() { var doc = selectedDocument(); ['swd-save', 'swd-add-row', 'swd-delete-row', 'swd-download-excel', 'swd-generate', 'swd-pick-register', 'swd-edit-pattern'].forEach(function (id) { $('#' + id).disabled = !doc || state.busy; }); ['swd-save-config', 'swd-create-pattern', 'swd-pick-folder', 'swd-pick-material', 'swd-pick-excel', 'swd-draft-apply', 'swd-create-confirm'].forEach(function (id) { $('#' + id).disabled = state.busy; });
    ['swd-document-list', 'swd-generation-scope', 'swd-pattern-select-all', 'swd-pattern-clear'].forEach(function (id) { $('#' + id).disabled = state.busy; });
    var count = generationNames().length;
    $('#swd-generate').disabled = state.busy || !count;
    setText('swd-generate', '生成 Pattern' + (count ? '（' + count + '）' : '')); 
    $('#swd-generation-retry').hidden = !(lastBatch && lastBatch.documentId === state.documentId && lastBatch.failures.length);
    $('#swd-generation-retry').disabled = state.busy;
    $$('[data-pattern-check], #swd-step-body input').forEach(function (node) { node.disabled = state.busy; });
  }
  function renderAll() { renderDocuments(); renderPatternList(); renderConfig(); renderEditor(); renderGenerations(); renderMaterials(); updateButtons(); setText('swd-status-badge', state.busy ? '处理中' : '就绪'); }
  function changedConfig() { state.configDirty = true; setText('swd-config-status', '有未保存修改'); }
  function notifyParent() { try { var apiObject = window.parent && window.parent.MCUWorkbench; if (apiObject && typeof apiObject.resourcesChanged === 'function') apiObject.resourcesChanged(); } catch (_) {} }
  async function refresh() { try { applyState(await api('/api/swd/state'), true); setStatus('swd-document-status', ''); } catch (error) { setText('swd-status-badge', '读取失败'); setStatus('swd-document-status', error.message, 'swd-danger'); } }
  async function importBinary(path, file, statusId) {
    if (state.dirty) { notify('当前步骤有未保存修改，请先保存后再导入文件。'); return; }
    var headers = { 'Content-Type': 'application/octet-stream', 'X-File-Name': encodeURIComponent(file.name) };
    try { applyState(await api(path, { method: 'POST', headers: headers, body: await file.arrayBuffer() })); setStatus(statusId, '已导入 ' + file.name); notify('已导入 ' + file.name); notifyParent(); }
    catch (error) { setStatus(statusId, '导入失败：' + error.message, 'swd-danger'); notify('导入失败：' + error.message); }
  }
  async function importMaterials(files) {
    if (state.busy) return;
    if (state.dirty) { notify('请先保存当前步骤，再导入资料。'); return; }
    var supported = files.filter(function (file) { return /\.(svd|xlsx|h|c)$/i.test(file.name); }), failures = [], count = 0;
    state.busy = true; updateButtons();
    try {
      for (var i = 0; i < supported.length; i += 1) {
        var file = supported[i], name = file.webkitRelativePath || file.name;
        setStatus('swd-material-status', '正在导入 ' + (i + 1) + '/' + supported.length + '：' + name);
        try { applyState(await api('/api/swd/material', { method: 'POST', headers: { 'Content-Type': 'application/octet-stream', 'X-File-Name': encodeURIComponent(name) }, body: await file.arrayBuffer() })); count += 1; }
        catch (error) { failures.push(name + '：' + error.message); }
      }
      setStatus('swd-material-status', '已导入 ' + count + ' 个文件，跳过 ' + (files.length - supported.length) + ' 个不支持的文件。' + (failures.length ? '\n失败 ' + failures.length + ' 个：\n' + failures.join('\n') : ''), failures.length ? 'swd-danger' : '');
      if (count) notifyParent();
    } finally { state.busy = false; renderAll(); }
  }
  async function useCache(id) {
    var cache = cacheCatalog.find(function (item) { return item.id === id; }); if (!cache) return;
    if (state.busy) return;
    state.busy = true; updateButtons();
    try { applyState(await api(cache.endpoint, jsonBody({})), true); setStatus('swd-material-status', '已载入 ' + cache.label + ' 缓存，可在编辑 Pattern 时从 SVD 添加。'); notifyParent(); }
    catch (error) { setStatus('swd-material-status', error.message, 'swd-danger'); }
    finally { state.busy = false; renderAll(); }
  }
  async function saveDocument() {
    var doc = selectedDocument(); if (!doc || state.busy) return false;
    state.busy = true; renderAll();
    try { var rows = (doc.rows || []).map(function (row) { var copy = Object.assign({}, row); delete copy._uiRowId; return copy; }); applyState(await api('/api/swd/save', jsonBody({ documentId: doc.id, rows: rows }))); state.dirty = false; changedCells = {}; setStatus('swd-editor-status', '已保存。'); setText('swd-editor-state', '已保存'); notifyParent(); return true; }
    catch (error) { setStatus('swd-editor-status', '保存失败：' + error.message, 'swd-danger'); notify('保存失败：' + error.message); return false; }
    finally { state.busy = false; renderAll(); }
  }
  async function saveConfig() {
    if (state.busy) return false;
    state.config = { chip: $('#swd-chip').value, pins: { swc: $('#swd-pin-swc').value, swd: $('#swd-pin-swd').value, reset: $('#swd-pin-reset').value, trig: $('#swd-pin-trig').value } };
    state.busy = true; renderAll();
    try { applyState(await api('/api/swd/config', jsonBody(state.config)), true); state.configDirty = false; setStatus('swd-config-status', '已保存。'); notifyParent(); return true; }
    catch (error) { setStatus('swd-config-status', '保存失败：' + error.message, 'swd-danger'); notify('配置保存失败：' + error.message); return false; }
    finally { state.busy = false; renderAll(); }
  }
  function addRow() {
    var doc = selectedDocument(); if (!doc) return;
    var id = 'new-' + Date.now() + '-' + (++newRowNumber), rows = Array.isArray(doc.rows) ? doc.rows : [], row = { row: null, _uiRowId: id, pattern: state.pattern, addr: '', data: '', step: '', 'reset value': '', type: '', continue: '', description: '' }, current = '', insertAt = rows.length;
    rows.forEach(function (item, index) { if (item.pattern != null && String(item.pattern).trim()) current = String(item.pattern); if (current === String(state.pattern)) insertAt = index + 1; });
    rows.splice(insertAt, 0, row); doc.rows = rows; state.selectedRowId = id; state.dirty = true; renderProvenance(); renderEditor(); updateButtons(); setText('swd-editor-state', '有未保存修改');
  }
  function deleteRow(id) {
    var doc = selectedDocument(); if (!doc) return;
    var rows = doc.rows || [], targetIndex = rows.findIndex(function (row, index) { return String(rowId(row, index)) === String(id); });
    if (targetIndex < 0) return;
    var target = rows[targetIndex], targetPattern = target.pattern != null && String(target.pattern).trim() ? String(target.pattern) : '';
    if (targetPattern && rows[targetIndex + 1] && !(rows[targetIndex + 1].pattern != null && String(rows[targetIndex + 1].pattern).trim())) rows[targetIndex + 1].pattern = targetPattern;
    doc.rows = rows.filter(function (_, index) { return index !== targetIndex; }); state.selectedRowId = ''; state.dirty = true; renderProvenance(); renderEditor(); updateButtons(); setText('swd-editor-state', '有未保存修改');
  }
  async function generate(retry) {
    if (!selectedDocument() || state.busy) return;
    if (state.dirty) { notify('请先保存步骤，再生成 Pattern。'); return; }
    var doc = selectedDocument(), names = retry === true && lastBatch && lastBatch.documentId === doc.id ? lastBatch.failures.map(function (item) { return item.pattern; }) : generationNames();
    if (!names.length) { notify('请先勾选要生成的 Pattern。'); return; }
    if (state.configDirty && !(await saveConfig())) return;
    lastBatch = { documentId: doc.id, failures: [] }; state.busy = true; renderAll();
    var passed = 0;
    try {
      for (var i = 0; i < names.length; i += 1) {
        var progress = '正在生成 ' + (i + 1) + ' / ' + names.length + '：' + names[i];
        setStatus('swd-batch-status', progress); setStatus('swd-generation-status', progress);
        try { applyState(await api('/api/swd/generate', jsonBody({ documentId: doc.id, pattern: names[i] }))); passed += 1; }
        catch (error) { lastBatch.failures.push({ pattern: names[i], error: error.message }); }
      }
      var summary = '生成完成：成功 ' + passed + ' / ' + names.length + '，失败 ' + lastBatch.failures.length + '。' + (lastBatch.failures.length ? '\n' + lastBatch.failures.map(function (item) { return item.pattern + '：' + item.error; }).join('\n') : '（Chroma + S100）');
      setStatus('swd-batch-status', summary, lastBatch.failures.length ? 'swd-danger' : ''); setStatus('swd-generation-status', summary); notify('Pattern 生成完成，成功 ' + passed + '，失败 ' + lastBatch.failures.length + '。');
    } finally { state.busy = false; renderAll(); }
  }
  async function download(path, id, preview) {
    try {
      var query = '?id=' + encodeURIComponent(id);
      if (preview.file) query += '&file=' + encodeURIComponent(preview.file);
      var response = await fetch(path + query, { headers: { 'X-GUI-Session': token } });
      if (!response.ok) throw new Error('HTTP ' + response.status);
      var blob = await response.blob();
      if (preview.read) { var bytes = await blob.arrayBuffer(), text; try { text = new TextDecoder('gb18030').decode(bytes); } catch (_) { text = new TextDecoder().decode(bytes); } $('#swd-preview').hidden = false; $('#swd-preview').textContent = text; state.previewKey = id + '|' + preview.file; return; }
      var url = URL.createObjectURL(blob), link = document.createElement('a'); link.href = url; link.download = preview.downloadName || (preview.file ? preview.file.split('/').pop() : 'swd-output'); document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url);
    } catch (error) { notify((preview.read ? '预览' : '下载') + '失败：' + error.message); }
  }
  async function downloadExcel() {
    if (state.dirty) { notify('请先保存步骤，再下载 Excel。'); return; }
    var doc = selectedDocument(); if (doc) download('/api/swd/excel', doc.id, { downloadName: doc.name || 'swd.xlsx', read: false });
  }
  async function confirmMaterial(conflictId) {
    var note = $$('[data-conflict-note]').find(function (item) { return item.getAttribute('data-conflict-note') === String(conflictId); });
    var source = $$('[data-conflict-source]').find(function (item) { return item.getAttribute('data-conflict-source') === String(conflictId); });
    if (!note) return;
    var noteValue = note.value, sourceValue = source ? source.value || null : null;
    try { applyState(await api('/api/swd/confirm', jsonBody({ conflictId: conflictId, sourceId: sourceValue, note: noteValue })), true); setStatus('swd-material-status', '冲突已确认并保存备注。'); notifyParent(); }
    catch (error) { setStatus('swd-material-status', '冲突确认失败：' + error.message, 'swd-danger'); notify('冲突确认失败：' + error.message); }
  }
  function blankStep() { return { row: null, pattern: state.pattern, addr: '', data: '', step: '', 'reset value': '', type: 'W', continue: '', description: '' }; }
  function openPatternEditor() {
    var doc = selectedDocument(); if (!doc || state.busy) return;
    authoring = { documentId: doc.id, pattern: state.pattern, rows: rowsForPattern(doc).map(function (row) { return Object.assign({}, row); }), index: 0, sources: new Map() };
    if (!authoring.rows.length) authoring.rows.push(blankStep());
    authoring.initialRows = authoring.rows.slice(); authoring.baselines = new Map();
    authoring.rows.forEach(rememberDraftStep);
    setText('swd-pattern-edit-title', '编辑 Pattern · ' + state.pattern);
    setText('swd-draft-status', ''); renderDraft(); $('#swd-pattern-dialog').showModal();
  }
  function draftRow() { return authoring && authoring.rows[authoring.index]; }
  function rememberDraftStep(row) {
    if (!authoring.baselines.has(row)) authoring.baselines.set(row, { row: Object.assign({}, row), source: authoring.sources.get(row) });
  }
  function draftStepChanged(row) {
    var baseline = authoring.baselines.get(row);
    return !!baseline && Object.keys(draftFields).some(function (id) { var key = draftFields[id]; return String(row[key] == null ? '' : row[key]) !== String(baseline.row[key] == null ? '' : baseline.row[key]); });
  }
  function draftHasChanges() {
    return !!authoring && (authoring.rows.length !== authoring.initialRows.length || authoring.rows.some(function (row, index) { return row !== authoring.initialRows[index] || draftStepChanged(row); }));
  }
  function restoreDraftStep() {
    var row = draftRow(); if (!row || state.busy) return;
    var baseline = authoring.baselines.get(row); if (!baseline) return;
    Object.keys(row).forEach(function (key) { delete row[key]; }); Object.assign(row, baseline.row);
    if (baseline.source) authoring.sources.set(row, baseline.source); else authoring.sources.delete(row);
    renderDraft(); setText('swd-draft-status', authoring.initialRows.indexOf(row) >= 0 ? '当前步骤已恢复到打开编辑器时的内容，尚未保存。' : '当前新增步骤已恢复到创建时的内容，尚未保存。');
  }
  function copyDraftStep() {
    var row = draftRow(); if (!row || state.busy) return;
    var copy = Object.assign({}, row, { row: null, pattern: authoring.pattern }); delete copy._uiRowId; delete copy.id;
    if (authoring.sources.has(row)) authoring.sources.set(copy, authoring.sources.get(row));
    authoring.index += 1; authoring.rows.splice(authoring.index, 0, copy);
    renderDraft(); revealDraftStep(); setText('swd-draft-status', '已复制到下一步，尚未保存。');
  }
  function cancelPatternDraft() {
    if (state.busy) return;
    if (draftHasChanges()) { if (!$('#swd-discard-dialog').open) $('#swd-discard-dialog').showModal(); $('#swd-discard-keep').focus(); return; }
    discardPatternDraft();
  }
  function discardPatternDraft() {
    if (state.busy) return;
    $('#swd-discard-dialog').close(); closeRegisterPicker(); authoring = null; renderProvenance(); $('#swd-pattern-dialog').close();
  }
  function bitmapData() {
    var row = draftRow();
    if (!row || !/^(W|R|CAP|C_H|C_L|SRAM)$/i.test(row.type || '')) return null;
    var value = String(row.data || '').trim(), shifts = String(row.step || '').trim();
    if (!shifts || shifts === '/') return !value ? { value: 0 } : (/^(?:0x)?[0-9a-f]{1,8}$/i.test(value) ? { value: parseInt(value.replace(/^0x/i, ''), 16) } : null);
    var reset = String(row['reset value'] || '').trim();
    if (!/^(?:0x)?[0-9a-f]{8}$/i.test(reset)) return null;
    var positions = shifts.split(',').map(function (s) { return s.trim(); }), values = value.split(',').map(function (s) { return s.trim(); });
    // Match the existing generator: unequal counts mean one-bit writes of 1.
    if (values.length !== positions.length) values = positions.map(function () { return '1'; });
    var result = BigInt('0x' + reset.replace(/^0x/i, '')), fields = [];
    for (var i = 0; i < positions.length; i += 1) {
      var text = values[i], shift = Number(positions[i]);
      if (!/^\d+$/.test(positions[i]) || shift > 31 || !/^(?:0x[0-9a-f]+|0b[01]+|\d+)$/i.test(text)) return null;
      var number = BigInt(text), width = /^0x/i.test(text) ? (text.length - 2) * 4 : /^0b/i.test(text) ? text.length - 2 : Math.max(number.toString(2).length, 1);
      if (width > 32 || number > 0xFFFFFFFFn) return null;
      var mask = ((1n << BigInt(width)) - 1n) << BigInt(shift);
      result = ((result & ~mask) | (number << BigInt(shift))) & 0xFFFFFFFFn;
      fields.push({ number: number, width: width, shift: shift });
    }
    return { value: Number(result), fields: fields, values: values, positions: positions };
  }
  function bitmapValue() { var bitmap = bitmapData(); return bitmap === null ? null : bitmap.value; }
  function toggleDraftBit(bit) {
    var bitmap = bitmapData(), row = draftRow();
    if (!bitmap || state.busy || !Number.isInteger(bit) || bit < 0 || bit > 31) return;
    if (!bitmap.fields) row.data = '0x' + ((bitmap.value ^ Math.pow(2, bit)) >>> 0).toString(16).toUpperCase().padStart(8, '0');
    else {
      var index = -1;
      bitmap.fields.forEach(function (field, i) { if (bit >= field.shift && bit < field.shift + field.width) index = i; });
      if (index >= 0) {
        var field = bitmap.fields[index];
        bitmap.values[index] = '0b' + (field.number ^ (1n << BigInt(bit - field.shift))).toString(2).padStart(field.width, '0');
      } else { bitmap.positions.push(String(bit)); bitmap.values.push(Math.floor(bitmap.value / Math.pow(2, bit)) % 2 ? '0b0' : '0b1'); }
      row.data = bitmap.values.join(','); row.step = bitmap.positions.join(',');
    }
    $('#swd-step-data').value = row.data; $('#swd-step-shift').value = row.step; renderDraftList(); renderBits();
  }
  function fieldRange(field) { var offset = Number(field.bitOffset), width = Number(field.bitWidth); return Number.isInteger(offset) && Number.isInteger(width) && width > 0 ? [offset, offset + width - 1] : null; }
  function browsedRegister() { return registerPicker && svdRegisters().find(function (source) { return source.id === registerPicker.active; }); }
  function registerMatchesDraft(source) {
    var row = draftRow();
    return !!(source && row && /^0x[0-9a-f]{1,8}$/i.test(String(row.addr || '').trim()) && /^0x[0-9a-f]{1,8}$/i.test(source.address) && BigInt(String(row.addr).trim()) === BigInt(source.address));
  }
  function registerFieldsMarkup(fields) {
    return fields.length ? '<div class="swd-field-tools"><button type="button" class="wb-button" data-field-expand="true">全部展开</button><button type="button" class="wb-button" data-field-expand="false">全部收起</button><span>点击字段名定位 bit，不改数据</span></div><table><thead><tr><th>位</th><th>字段</th><th>说明</th></tr></thead><tbody>' + fields.map(function (field, index) {
      var range = fieldRange(field), text = String(field.description || '资料未提供说明'), short = text.replace(/\s+/g, ' '), valid = range && range[0] >= 0 && range[1] < 32;
      return '<tr><td>' + esc(range ? range[1] + ':' + range[0] : field.bits || '') + '</td><td><button type="button" class="swd-field-link" data-field-index="' + index + '" ' + (!valid || !registerMatchesDraft(browsedRegister()) ? 'disabled ' : '') + '>' + esc(field.name) + '</button></td><td>' + (short.length > 90 ? '<details class="swd-field-description"><summary>' + esc(short.slice(0, 90)) + '…</summary><div>' + esc(text) + '</div></details>' : esc(text)) + '</td></tr>';
    }).join('') + '</tbody></table>' : '<p class="swd-hint">资料没有提供位字段。</p>';
  }
  function renderBits() {
    var row = draftRow(), value = bitmapValue(), browsed = browsedRegister(), matchesDraft = registerMatchesDraft(browsed);
    setText('swd-editing-context', row ? '正在编辑 · 第 ' + (authoring.index + 1) + ' 步 · ' + (row.addr || '未设地址') : '未选择步骤');
    setText('swd-register-context', browsed ? '正在浏览 · ' + registerName(browsed) + ' · ' + browsed.address + (matchesDraft ? ' · 与当前步骤地址一致' : ' · 尚未应用到当前步骤，字段定位不可用') : '选择寄存器浏览字段；不会自动修改当前步骤。');
    $('#swd-register-context').className = 'swd-reference-context' + (browsed && !matchesDraft ? ' swd-reference-mismatch' : '');
    var focus = registerPicker && registerPicker.focusedField;
    if (focus && (!matchesDraft || focus.row !== row || focus.sourceId !== browsed.id)) { registerPicker.focusedField = null; focus = null; setText('swd-draft-status', ''); }
    $$('[data-field-index]').forEach(function (button) { var field = browsed && (browsed.fields || [])[Number(button.dataset.fieldIndex)], range = field && fieldRange(field); button.disabled = !matchesDraft || !range || range[0] < 0 || range[1] > 31; });
    var source = row && authoring.sources.get(row);
    if (!source && row) { var matches = svdRegisters().filter(function (item) { return String(item.address).toLowerCase() === String(row.addr).toLowerCase(); }); if (matches.length === 1) source = matches[0]; }
    var fields = source && source.fields || [];
    $('#swd-bit-grid').innerHTML = Array.from({ length: 32 }, function (_, index) {
      var bit = 31 - index, on = value !== null && Math.floor(value / Math.pow(2, bit)) % 2 === 1;
      var labels = fields.filter(function (field) { var range = fieldRange(field); return range && bit >= range[0] && bit <= range[1]; }).map(function (field) { return field.name; });
      return '<button type="button" class="swd-bit' + (focus && bit >= focus.range[0] && bit <= focus.range[1] ? ' swd-field-highlight' : '') + '" data-bit-index="' + bit + '" aria-pressed="' + on + '" ' + (value === null ? 'disabled ' : '') + 'title="Bit ' + bit + (labels.length ? ' · ' + esc(labels.join(', ')) : '') + '"><small>' + bit + '</small><strong>' + (value === null ? '—' : (on ? '1' : '0')) + '</strong></button>';
    }).join('');
    setText('swd-bit-status', value === null ? '无法解析为 32 位数据，请检查 data、step 与八位十六进制 reset；原数据保持不变。' : ('结果 0x' + value.toString(16).toUpperCase().padStart(8, '0') + ' · ' + (!String(row.step || '').trim() || row.step === '/' ? '点击 0 / 1 修改对应位。' : '点击修改位域，保留 reset 与掩码宽度；未覆盖的位追加单个位移。')));
  }
  function renderDraftList() {
    if (!authoring) return;
    var count = 0;
    $('#swd-draft-steps').innerHTML = authoring.rows.map(function (row, index) {
      rememberDraftStep(row);
      var title = (index + 1) + ' · ' + (row.addr || '未设地址');
      count += 1;
      var marker = authoring.initialRows.indexOf(row) < 0 ? '新增' : draftStepChanged(row) ? '已修改' : '';
      return '<div class="swd-draft-item" data-draft-step="' + index + '"><button type="button" draggable="true" class="swd-draft-handle" data-draft-drag="' + index + '" aria-label="拖动第 ' + (index + 1) + ' 步排序" title="拖动排序；Alt + 上下键移动">⠿</button><button type="button" class="swd-draft-step" data-draft-step="' + index + '" aria-current="' + (index === authoring.index) + '" title="' + esc(title + '\n' + (row.description || '')) + '"><strong>' + esc(title) + '</strong><span>' + (marker ? '<em class="swd-change-badge">' + marker + '</em> ' : '') + esc(row.type || '未设操作') + (row.description ? ' · ' + esc(row.description) : '') + '</span></button><button type="button" class="swd-draft-remove" data-draft-delete="' + index + '" aria-label="删除第 ' + (index + 1) + ' 步" title="删除此步骤">−</button></div>';
    }).join('') || '<div class="swd-empty">没有匹配的步骤。</div>';
    setText('swd-draft-count', '显示 ' + count + ' / ' + authoring.rows.length + ' 步 · 当前第 ' + (authoring.index + 1) + ' 步');
    setText('swd-draft-dirty', draftHasChanges() ? '有未保存修改' : '本次编辑无修改');
    $('#swd-draft-restore').disabled = !draftRow() || !draftStepChanged(draftRow()) || state.busy;
  }
  function revealDraftStep() {
    var selected = $('#swd-draft-steps [aria-current="true"]');
    if (selected) selected.scrollIntoView({ block: 'nearest' });
  }
  function renderDraft() {
    if (!authoring) return;
    renderProvenance();
    renderDraftList();
    var row = draftRow();
    var types = ['W', 'R', 'CAP', 'C_H', 'C_L', 'SRAM', 'US', 'MS'];
    if (row && types.indexOf(row.type || '') < 0) types.unshift(row.type || '');
    $('#swd-step-type').innerHTML = types.map(function (value) { return '<option value="' + esc(value) + '">' + esc(value || '请选择') + '</option>'; }).join('');
    Object.keys(draftFields).forEach(function (id) { $('#' + id).value = row ? row[draftFields[id]] || '' : ''; $('#' + id).disabled = !row; });
    $('#swd-draft-copy').disabled = !row || state.busy;
    renderBits();
  }
  function changeDraftOrder(direction) {
    if (!authoring || state.busy) return;
    var next = authoring.index + direction;
    if (next < 0 || next >= authoring.rows.length) return;
    var row = authoring.rows.splice(authoring.index, 1)[0]; authoring.rows.splice(next, 0, row); authoring.index = next; renderDraft();
  }
  async function savePatternDraft() {
    if (!authoring || state.busy) return;
    var doc = selectedDocument(), draft = authoring;
    if (!doc || doc.id !== draft.documentId || state.pattern !== draft.pattern) return;
    var selected = rowsForPattern(doc), first = (doc.rows || []).indexOf(selected[0]), rows = (doc.rows || []).filter(function (row) { return selected.indexOf(row) < 0; });
    var replacements = (draft.rows.length ? draft.rows : [blankStep()]).map(function (row) { var copy = Object.assign({}, row, { pattern: draft.pattern }); delete copy._uiRowId; return copy; });
    rows.splice.apply(rows, [first < 0 ? rows.length : first, 0].concat(replacements));
    rows = rows.map(function (row) { var copy = Object.assign({}, row); delete copy._uiRowId; return copy; });
    state.busy = true; updateButtons();
    try { applyState(await api('/api/swd/save', jsonBody({ documentId: doc.id, rows: rows }))); state.dirty = false; changedCells = {}; closeRegisterPicker(); authoring = null; $('#swd-pattern-dialog').close(); notifyParent(); setStatus('swd-editor-status', 'Pattern 已保存。'); }
    catch (error) { setText('swd-draft-status', '保存失败：' + error.message); }
    finally { state.busy = false; renderAll(); }
  }
  async function createPattern() {
    if (state.busy) return;
    var name = $('#swd-new-pattern-name').value.replace(/\s+/g, ''), doc = selectedDocument();
    if (patternNames(doc).indexOf(name) >= 0) { setText('swd-create-status', '当前文件或草稿已存在同名 Pattern。'); return; }
    setText('swd-create-status', '正在创建 Pattern 草稿…');
    state.busy = true; updateButtons();
    try {
      var result = await api('/api/swd/create', jsonBody({ documentId: state.documentId || undefined, name: name }));
      var created = result.documents.find(function (item) { return item.id === result.createdDocumentId; });
      var row = Object.assign({}, created.rows[created.rows.length - 1], { _uiRowId: 'new-' + Date.now() + '-' + (++newRowNumber) });
      if (doc && doc.id === created.id) { doc.rows.push(row); doc.patterns = patternNames(doc); }
      else { created.rows = [row]; state.documents.push(created); }
      state.documentId = result.createdDocumentId; state.pattern = result.createdPattern; state.selectedRowId = ''; state.dirty = true; renderAll(); $('#swd-create-dialog').close();
      state.busy = false; openPatternEditor();
    } catch (error) { setText('swd-create-status', error.message); }
    finally { state.busy = false; renderAll(); }
  }
  function svdRegisters() {
    var materials = materialRecords();
    return sourceRecords(state.materials || {}).filter(function (source) {
      return ['svd', 'svd_cache'].indexOf(source.kind) >= 0 || materials.some(function (item) { return item.id === source.materialId && ['svd', 'svd_cache'].indexOf(item.kind) >= 0; });
    });
  }
  function registerName(source) { return (source.peripheral ? source.peripheral + '.' : '') + source.name; }
  function registerDescription(source) { return registerName(source) + (source.description ? ': ' + source.description : ''); }
  function openRegisterPicker(targetId) {
    if (!selectedDocument() || state.busy) return;
    if ($('#swd-register-dialog').open) { $('#swd-register-search').focus(); return; }
    registerPicker = { documentId: state.documentId, pattern: state.pattern, targetId: targetId == null ? null : String(targetId), selected: [], active: '', query: '', source: '', peripheral: '' };
    setText('swd-register-title', targetId == null ? '从 SVD 添加步骤' : '为当前步骤选择寄存器');
    setText('swd-register-status', authoring ? '拖到属性区替换，拖到步骤之间插入；也可使用下方按钮。' : '选择明确来源后应用；不会覆盖已有步骤的数据、操作和位移。');
    $('#swd-register-search').value = '';
    var materials = materialRecords().filter(function (item) { return ['svd', 'svd_cache'].indexOf(item.kind) >= 0; });
    $('#swd-register-source').innerHTML = '<option value="">全部 SVD 来源</option>' + materials.map(function (item) { return '<option value="' + esc(item.id) + '">' + esc(item.originalName || item.name || item.id) + '</option>'; }).join('');
    $('#swd-register-source').value = '';
    var names = Array.from(new Set(svdRegisters().map(function (source) { return source.peripheral || ''; }))).sort();
    $('#swd-register-peripheral').innerHTML = '<option value="">全部外设</option>' + names.filter(Boolean).map(function (name) { return '<option value="' + esc(name) + '">' + esc(name) + '</option>'; }).join('');
    $('#swd-register-peripheral').value = '';
    (authoring ? $('#swd-draft-form') : $('#swd-register-body')).appendChild($('#swd-register-preview'));
    renderRegisterPicker();
    (authoring ? $('#swd-pattern-dialog') : $('#swd-app')).appendChild($('#swd-register-dialog'));
    $('#swd-register-head').title = authoring ? 'SVD 寄存器 · 拖动寄存器到右侧编辑区' : '拖动标题栏移动窗口';
    $('#swd-register-dialog').show();
    $('#swd-register-search').focus();
  }
  function renderRegisterPicker() {
    if (!registerPicker) return;
    var picker = registerPicker, all = svdRegisters();
    var matches = all.filter(function (source) {
      return (!picker.source || source.materialId === picker.source) && (!picker.peripheral || source.peripheral === picker.peripheral) &&
        (!picker.query || [registerName(source), source.address, source.description || '', sourceLabel(state.materials, source)].join(' ').toLowerCase().indexOf(picker.query) >= 0);
    });
    var showSource = new Set(matches.map(function (source) { return source.materialId; })).size > 1;
    var list = $('#swd-register-list'), scroll = list.scrollTop;
    var opened = $$('#swd-register-list details[open]').map(function (node) { return node.dataset.peripheral; });
    var groups = {};
    matches.forEach(function (source) { var name = source.peripheral || '未分组'; (groups[name] || (groups[name] = [])).push(source); });
    $('#swd-register-list').innerHTML = matches.length ? Object.keys(groups).map(function (name) {
      return '<details class="swd-peripheral-group" data-peripheral="' + esc(name) + '" ' + (opened.indexOf(name) >= 0 || picker.query || picker.peripheral || groups[name].some(function (source) { return picker.selected.indexOf(source.id) >= 0; }) ? 'open' : '') + '><summary>' + esc(name) + ' · ' + groups[name].length + '</summary>' + groups[name].map(function (source) {
      var selected = picker.selected.indexOf(source.id) >= 0;
      return '<div class="swd-register-row"><button type="button" draggable="true" class="swd-register-result" data-register-select="' + esc(source.id) + '" title="' + esc(sourceLabel(state.materials, source)) + '" aria-pressed="' + selected + '"><strong>' + esc(registerName(source)) + '</strong><code>' + esc(source.address) + '</code>' + (showSource ? '<small>' + esc(sourceLabel(state.materials, source)) + '</small>' : '') + '</button>' + (authoring && picker.active === source.id ? '<span class="swd-register-inline"><button type="button" class="wb-button" data-register-replace="' + esc(source.id) + '">替换</button><button type="button" class="wb-button" data-register-insert="' + esc(source.id) + '">插入</button></span>' : '') + '</div>';
      }).join('') + '</details>';
    }).join('') : '<div class="swd-empty">' + (all.length ? '没有匹配的寄存器。' : '请先导入 SVD 或使用 PY32F420 缓存。') + '</div>';
    list.scrollTop = scroll;
    setText('swd-register-selection', '匹配 ' + matches.length + ' 个 · 已选择 ' + picker.selected.length + ' 个' + (picker.targetId === null ? ' · 按选择顺序插入当前 Pattern' : ' · 替换当前步骤的寄存器'));
    $('#swd-register-apply').disabled = !picker.selected.length;
    $('#swd-register-replace').hidden = !authoring;
    $('#swd-register-replace').disabled = picker.selected.length !== 1 || !draftRow();
    setText('swd-register-apply', picker.targetId === null ? '插入选中寄存器' : '应用到当前步骤');
    var source = all.find(function (item) { return item.id === picker.active; });
    $('#swd-register-preview').hidden = !source;
    $('#swd-register-detail').hidden = !source; $('#swd-register-back').hidden = !source;
    $('#swd-register-detail').innerHTML = source ? '<h3>' + esc(registerName(source)) + '</h3><p>' + esc(source.address) + '</p><p>复位值：' + esc(source.resetValue || '资料未提供') + ' · 访问：' + esc(source.access || '资料未提供') + '</p>' + registerFieldsMarkup(source.fields || []) + '<details><summary>寄存器说明与来源</summary><p>' + esc(source.description || '资料未提供寄存器说明') + '</p><p>' + esc(sourceLabel(state.materials, source)) + '</p></details>' : '<p class="swd-hint">选择寄存器查看地址、复位值、字段和来源。相同地址的不同来源分别保留。</p>';
    renderBits();
  }
  function selectRegister(sourceId) {
    if (!registerPicker || !svdRegisters().some(function (source) { return source.id === sourceId; })) return;
    var picker = registerPicker, index = picker.selected.indexOf(sourceId);
    if (authoring || picker.targetId !== null) picker.selected = [sourceId];
    else if (index >= 0) picker.selected.splice(index, 1);
    else picker.selected.push(sourceId);
    picker.active = sourceId; picker.focusedField = null;
    renderRegisterPicker();
  }
  function closeRegisterPicker() {
    $('#swd-register-preview').hidden = true;
    $('#swd-register-dialog').close(); registerPicker = null; draggedRegister = ''; floatingDrag = null; renderBits();
  }
  function applyDraftRegister(source, at) {
    if (!authoring || state.busy || !source || !/^0x[0-9a-f]+$/i.test(source.address)) return;
    if (at === null) {
      var row = draftRow(); if (!row) return;
      row.addr = source.address; row['reset value'] = source.resetValue || ''; row.description = registerDescription(source); authoring.sources.set(row, source);
    } else {
      var step = Object.assign(blankStep(), { addr: source.address, 'reset value': source.resetValue || '', type: 'R', description: registerDescription(source) });
      authoring.sources.set(step, source); authoring.rows.splice(at, 0, step); authoring.index = at;
    }
    renderDraft(); revealDraftStep();
    setText('swd-draft-status', at === null ? '已替换当前寄存器；data / type / step 保留，尚未保存。' : '已插入寄存器步骤，请填写 data 后保存。');
  }
  function applyRegisters() {
    var picker = registerPicker, doc = selectedDocument();
    if (!picker || !doc || state.busy || String(doc.id) !== String(picker.documentId) || state.pattern !== picker.pattern) return;
    var all = svdRegisters(), selected = picker.selected.map(function (id) { return all.find(function (source) { return source.id === id; }); });
    if (!selected.length || selected.some(function (source) { return !source || !/^0x[0-9a-f]+$/i.test(source.address); })) { setText('swd-register-status', '资料已变化或寄存器地址无效，请重新选择。'); return; }
    if (authoring) {
      var added = selected.map(function (source) { var step = Object.assign(blankStep(), { addr: source.address, 'reset value': source.resetValue || '', type: 'R', description: registerDescription(source) }); authoring.sources.set(step, source); return step; });
      var at = authoring.index + 1;
      var currentDraft = draftRow();
      if (authoring.rows.length === 1 && currentDraft && !currentDraft.addr && !currentDraft.data && !currentDraft.description) { authoring.rows = []; at = 0; }
      authoring.rows.splice.apply(authoring.rows, [at, 0].concat(added)); authoring.index = at;
      renderDraft(); revealDraftStep(); return;
    }
    if (picker.targetId !== null) {
      var row = (doc.rows || []).find(function (item, index) { return String(rowId(item, index)) === picker.targetId; });
      if (!row) { setText('swd-register-status', '当前步骤已不存在，请关闭后重新选择。'); return; }
      row.addr = selected[0].address; row['reset value'] = selected[0].resetValue || ''; row.description = registerDescription(selected[0]);
      ['addr', 'reset value', 'description'].forEach(function (key) { changedCells[picker.targetId + '|' + key] = true; });
      state.selectedRowId = picker.targetId;
    } else {
      var rows = doc.rows || [], current = '', at = rows.length;
      rows.forEach(function (row, index) { if (row.pattern != null && String(row.pattern).trim()) current = String(row.pattern); if (current === state.pattern) at = index + 1; });
      var visible = rowsForPattern(doc), anchor = visible.find(function (row, index) { return String(rowId(row, index)) === String(state.selectedRowId); });
      if (anchor) at = rows.indexOf(anchor) + 1;
      var inserted = selected.map(function (source) {
        return { row: null, _uiRowId: 'new-' + Date.now() + '-' + (++newRowNumber), pattern: state.pattern, addr: source.address, data: '', step: '', 'reset value': source.resetValue || '', type: 'R', continue: '', description: registerDescription(source) };
      });
      rows.splice.apply(rows, [at, 0].concat(inserted)); doc.rows = rows;
      state.selectedRowId = inserted[0]._uiRowId;
    }
    state.dirty = true;
    renderProvenance(); renderEditor(); updateButtons();
    setStatus('swd-editor-status', picker.targetId === null ? '已插入 ' + selected.length + ' 个寄存器。请填写 data 并核对 type 后保存。' : '已更新寄存器地址、复位值和描述；数据、操作与位移已保留。');
    closeRegisterPicker();
  }
  function bind() {
    $('#swd-discard-keep').addEventListener('click', function () { $('#swd-discard-dialog').close(); });
    $('#swd-discard-confirm').addEventListener('click', discardPatternDraft);
    $('#swd-draft-copy').addEventListener('click', copyDraftStep);
    $('#swd-draft-restore').addEventListener('click', restoreDraftStep);
    $('#swd-register-back').addEventListener('click', function () { if (registerPicker) { registerPicker.active = ''; renderRegisterPicker(); } });
    $('#swd-register-replace').addEventListener('click', function () { if (registerPicker && registerPicker.selected.length === 1) applyDraftRegister(svdRegisters().find(function (source) { return source.id === registerPicker.selected[0]; }), null); });
    var registerHead = $('#swd-register-head'), panel = $('#swd-register-dialog');
    registerHead.addEventListener('pointerdown', function (event) {
      if (authoring || event.button !== 0 || event.target.closest('button')) return;
      var rect = panel.getBoundingClientRect(); floatingDrag = { x: event.clientX - rect.left, y: event.clientY - rect.top };
      registerHead.setPointerCapture(event.pointerId); event.preventDefault();
    });
    registerHead.addEventListener('pointermove', function (event) {
      if (!floatingDrag) return;
      panel.style.left = Math.max(0, Math.min(window.innerWidth - panel.offsetWidth, event.clientX - floatingDrag.x)) + 'px';
      panel.style.top = Math.max(0, Math.min(window.innerHeight - 48, event.clientY - floatingDrag.y)) + 'px';
    });
    registerHead.addEventListener('pointerup', function () { floatingDrag = null; });
    registerHead.addEventListener('lostpointercapture', function () { floatingDrag = null; });
    $('#swd-register-dialog').addEventListener('dragstart', function (event) {
      var source = event.target.closest('[data-register-select]');
      if (!source || !authoring || state.busy) { event.preventDefault(); return; }
      draggedRegister = source.dataset.registerSelect; event.dataTransfer.setData('application/x-swd-register', draggedRegister); event.dataTransfer.effectAllowed = 'copy';
    });
    function clearDropHint() { $$('[data-swd-drop]').forEach(function (node) { node.removeAttribute('data-swd-drop'); }); }
    function stopDragScroll() { clearInterval(dragScrollTimer); dragScrollTimer = null; }
    function finishDrag() { draggedStep = null; draggedRegister = ''; stopDragScroll(); clearDropHint(); }
    $('#swd-register-dialog').addEventListener('dragend', finishDrag);
    $('#swd-draft-steps').addEventListener('dragstart', function (event) {
      var handle = event.target.closest('[data-draft-drag]');
      if (!handle || !authoring || state.busy) { event.preventDefault(); return; }
      draggedStep = authoring.rows[Number(handle.dataset.draftDrag)]; draggedRegister = '';
      event.dataTransfer.setData('application/x-swd-step', String(handle.dataset.draftDrag)); event.dataTransfer.effectAllowed = 'move';
    });
    $('#swd-draft-steps').addEventListener('dragend', finishDrag);
    $('#swd-draft-steps').addEventListener('keydown', function (event) {
      var handle = event.target.closest('[data-draft-drag]');
      if (!handle || !authoring || !event.altKey || ['ArrowUp', 'ArrowDown'].indexOf(event.key) < 0) return;
      event.preventDefault(); authoring.index = Number(handle.dataset.draftDrag); changeDraftOrder(event.key === 'ArrowUp' ? -1 : 1); revealDraftStep();
      var moved = $('#swd-draft-steps [data-draft-drag="' + authoring.index + '"]'); if (moved) moved.focus();
    });
    ['swd-draft-form', 'swd-draft-steps'].forEach(function (id) {
      var zone = $('#' + id);
      zone.addEventListener('dragover', function (event) {
        if ((!draggedRegister && !(draggedStep && id === 'swd-draft-steps')) || !authoring || state.busy) return;
        event.preventDefault(); event.dataTransfer.dropEffect = draggedStep ? 'move' : 'copy'; clearDropHint();
        var step = id === 'swd-draft-steps' && event.target.closest('[data-draft-step]');
        (step || zone).setAttribute('data-swd-drop', step ? (event.clientY < step.getBoundingClientRect().top + step.offsetHeight / 2 ? 'before' : 'after') : 'inside');
        stopDragScroll();
        if (id === 'swd-draft-steps') {
          var rect = zone.getBoundingClientRect(), direction = event.clientY < rect.top + 32 ? -1 : event.clientY > rect.bottom - 32 ? 1 : 0;
          if (direction) dragScrollTimer = setInterval(function () { zone.scrollTop += direction * 12; }, 30);
        }
      });
      zone.addEventListener('dragleave', function (event) { if (!zone.contains(event.relatedTarget)) { stopDragScroll(); clearDropHint(); } });
      zone.addEventListener('drop', function (event) {
        event.preventDefault(); stopDragScroll(); clearDropHint();
        if (!authoring || state.busy) return;
        var at = null;
        if (id === 'swd-draft-steps') {
          var step = event.target.closest('[data-draft-step]');
          at = step ? Number(step.dataset.draftStep) + (event.clientY < step.getBoundingClientRect().top + step.offsetHeight / 2 ? 0 : 1) : authoring.rows.length;
        }
        if (draggedStep) {
          var from = authoring.rows.indexOf(draggedStep);
          if (at !== null && from >= 0 && event.dataTransfer.getData('application/x-swd-step') !== '') {
            authoring.rows.splice(from, 1); if (at > from) at -= 1;
            authoring.rows.splice(at, 0, draggedStep); authoring.index = at; renderDraft(); revealDraftStep();
          }
        } else if (draggedRegister && event.dataTransfer.getData('application/x-swd-register') === draggedRegister) {
          applyDraftRegister(svdRegisters().find(function (item) { return item.id === draggedRegister; }), at);
        }
        finishDrag();
      });
    });
    $('#swd-pattern-search').addEventListener('input', renderPatternList);
    $('#swd-edit-pattern').addEventListener('click', openPatternEditor);
    $('#swd-create-pattern').addEventListener('click', function () { if (state.busy) return; $('#swd-new-pattern-name').value = ''; setText('swd-create-status', ''); $('#swd-create-dialog').showModal(); $('#swd-new-pattern-name').focus(); });
    $('#swd-create-confirm').addEventListener('click', createPattern);
    $('#swd-create-cancel').addEventListener('click', function () { if (!state.busy) $('#swd-create-dialog').close(); });
    $('#swd-draft-cancel').addEventListener('click', cancelPatternDraft);
    $('#swd-pattern-dialog').addEventListener('cancel', function (event) { event.preventDefault(); cancelPatternDraft(); });
    $('#swd-draft-apply').addEventListener('click', savePatternDraft);
    $('#swd-draft-add').addEventListener('click', function () { if (!authoring || state.busy) return; authoring.index += 1; authoring.rows.splice(authoring.index, 0, blankStep()); renderDraft(); });
    Object.keys(draftFields).forEach(function (id) { var update = function (event) { var row = draftRow(); if (!row || state.busy) return; row[draftFields[id]] = event.target.value; if (id === 'swd-step-addr') authoring.sources.delete(row); renderProvenance(); renderDraftList(); renderBits(); }; $('#' + id).addEventListener('input', update); if (id === 'swd-step-type') $('#' + id).addEventListener('change', update); });
    $('#swd-pick-folder').addEventListener('click', function () { $('#swd-folder-picker').click(); });
    $('#swd-folder-picker').addEventListener('change', function (event) { importMaterials(Array.prototype.slice.call(event.target.files || [])); event.target.value = ''; });
    $('#swd-generation-clear').addEventListener('click', function () {
      if (state.busy) return;
      state.generations.forEach(function (item) { hiddenGenerations.add(item.id); });
      try { localStorage.setItem('swd-hidden-generations', JSON.stringify(Array.from(hiddenGenerations))); } catch (_) {}
      $('#swd-preview').hidden = true; $('#swd-preview').textContent = ''; state.previewKey = '';
      setStatus('swd-generation-status', '列表已清空，已生成文件和关联保留。'); renderGenerations();
    });
    $('#swd-generation-scope').addEventListener('change', updateButtons);
    $('#swd-generation-retry').addEventListener('click', function () { generate(true); });
    $('#swd-pattern-select-all').addEventListener('click', function () { if (state.busy) return; var query = $('#swd-pattern-search').value.trim().toLowerCase(), checked = checkedForDocument(); patternNames(selectedDocument()).filter(function (name) { return name.toLowerCase().indexOf(query) >= 0; }).forEach(function (name) { checked.add(name); }); $('#swd-generation-scope').value = 'selected'; renderPatternList(); updateButtons(); });
    $('#swd-pattern-clear').addEventListener('click', function () { if (state.busy) return; checkedForDocument().clear(); renderPatternList(); updateButtons(); });
    $('#swd-document-list').addEventListener('change', function (event) { if (state.busy || state.dirty) { event.target.value = state.documentId; if (state.dirty) notify('当前步骤有未保存修改，请先保存。'); return; } state.documentId = event.target.value; state.pattern = patternNames(selectedDocument())[0] || ''; state.selectedRowId = ''; changedCells = {}; renderAll(); });
    document.addEventListener('change', function (event) { var input = event.target.closest('[data-pattern-check]'); if (!input || state.busy) return; var checked = checkedForDocument(); if (input.checked) checked.add(input.dataset.patternCheck); else checked.delete(input.dataset.patternCheck); $('#swd-generation-scope').value = 'selected'; renderPatternList(); updateButtons(); });
    function beginCellEdit(event) { var input = event.target.closest('input[data-row-id][data-field]'); if (!input || state.busy) return; input.readOnly = false; input.focus(); }
    document.addEventListener('dblclick', beginCellEdit);
    document.addEventListener('keydown', function (event) { if (event.key === 'F2') { event.preventDefault(); beginCellEdit(event); } });
    document.addEventListener('focusout', function (event) { var input = event.target.closest('input[data-row-id][data-field]'); if (input) input.readOnly = true; });
    $('#swd-pick-register').addEventListener('click', function () { openRegisterPicker(null); });
    $('#swd-register-close').addEventListener('click', closeRegisterPicker);
    $('#swd-register-apply').addEventListener('click', applyRegisters);
    ['search', 'source', 'peripheral'].forEach(function (name) { $('#swd-register-' + name).addEventListener(name === 'search' ? 'input' : 'change', function (event) { if (!registerPicker) return; registerPicker[name === 'search' ? 'query' : name] = name === 'search' ? event.target.value.trim().toLowerCase() : event.target.value; renderRegisterPicker(); }); });
    $('#swd-pick-excel').addEventListener('click', function () { $('#swd-excel-picker').click(); });
    $('#swd-excel-picker').addEventListener('change', function (event) { var file = event.target.files[0]; if (file) importBinary('/api/swd/import', file, 'swd-document-status'); event.target.value = ''; });
    $('#swd-pick-material').addEventListener('click', function () { $('#swd-material-picker').click(); });
    $('#swd-material-picker').addEventListener('change', function (event) { importMaterials(Array.prototype.slice.call(event.target.files || [])); event.target.value = ''; });
    $('#swd-pattern').addEventListener('change', function (event) { state.pattern = event.target.value; renderEditor(); updateButtons(); });
    $('#swd-save').addEventListener('click', saveDocument); $('#swd-save-config').addEventListener('click', saveConfig); $('#swd-add-row').addEventListener('click', addRow); $('#swd-generate').addEventListener('click', generate);
    ['swd-chip', 'swd-pin-swc', 'swd-pin-swd', 'swd-pin-reset', 'swd-pin-trig'].forEach(function (id) { $('#' + id).addEventListener('input', changedConfig); $('#' + id).addEventListener('change', changedConfig); });
    document.addEventListener('click', function (event) {
      var target = event.target.closest('button'); if (!target) return;
      if (target.dataset.cacheId != null) { useCache(target.dataset.cacheId); return; }
      if (target.dataset.patternName != null) { if (state.busy) return; state.pattern = target.dataset.patternName; state.selectedRowId = ''; renderPatternList(); renderEditor(); updateButtons(); return; }
      if (target.dataset.draftDelete != null) { if (!authoring || state.busy) return; var current = draftRow(), removed = Number(target.dataset.draftDelete); authoring.rows.splice(removed, 1); if (!authoring.rows.length) authoring.rows.push(blankStep()); authoring.index = authoring.rows.indexOf(current); if (authoring.index < 0) authoring.index = Math.min(removed, authoring.rows.length - 1); renderDraft(); return; }
      if (target.dataset.registerInsert != null || target.dataset.registerReplace != null) { var sourceId = target.dataset.registerInsert || target.dataset.registerReplace; if (registerPicker && registerPicker.active === sourceId) applyDraftRegister(svdRegisters().find(function (source) { return source.id === sourceId; }), target.dataset.registerInsert != null ? authoring.index + 1 : null); return; }
      if (target.dataset.draftStep != null) { if (authoring && !state.busy) { authoring.index = Number(target.dataset.draftStep); renderDraft(); } return; }
      if (target.dataset.fieldExpand != null) { $$('#swd-register-detail .swd-field-description').forEach(function (detail) { detail.open = target.dataset.fieldExpand === 'true'; }); return; }
      if (target.dataset.fieldIndex != null) {
        var source = browsedRegister(), field = source && (source.fields || [])[Number(target.dataset.fieldIndex)], range = field && fieldRange(field);
        if (registerMatchesDraft(source) && range && range[0] >= 0 && range[1] < 32) { registerPicker.focusedField = { sourceId: source.id, row: draftRow(), range: range }; renderBits(); setText('swd-draft-status', '已定位 ' + field.name + ' [' + range[1] + ':' + range[0] + ']，数据未修改。'); }
        return;
      }
      if (target.dataset.bitIndex != null) { toggleDraftBit(Number(target.dataset.bitIndex)); return; }
      if (target.dataset.registerSelect != null) { selectRegister(target.dataset.registerSelect); return; }
      if (target.dataset.pickRegisterRow != null) { openRegisterPicker(target.dataset.pickRegisterRow); return; }
      if (target.dataset.selectRow != null) { state.selectedRowId = target.dataset.selectRow; renderEditor(); return; }
      if (target.dataset.document != null) { if (state.dirty) { notify('当前步骤有未保存修改，请先保存。'); return; } state.documentId = target.dataset.document; state.pattern = patternNames(selectedDocument())[0] || ''; state.selectedRowId = ''; changedCells = {}; renderAll(); return; }
      if (target.dataset.deleteRow != null) { deleteRow(target.dataset.deleteRow); return; }
      if (target.id === 'swd-delete-row') { var first = state.selectedRowId || ($('#swd-step-body tr[data-row-id]') && $('#swd-step-body tr[data-row-id]').getAttribute('data-row-id')); if (first != null && first !== '') deleteRow(first); return; }
      if (target.id === 'swd-download-excel') { downloadExcel(); return; }
      if (target.dataset.downloadGeneration != null) { download('/api/swd/download', target.dataset.downloadGeneration, { file: target.dataset.downloadFile || '', read: false }); return; }
      if (target.dataset.previewGeneration != null) { download('/api/swd/download', target.dataset.previewGeneration, { file: target.dataset.previewFile || '', read: true }); return; }
      if (target.dataset.confirmMaterial != null) { confirmMaterial(target.dataset.confirmMaterial); }
    });
    document.addEventListener('input', function (event) {
      var input = event.target.closest('input[data-row-id][data-field]'); if (!input) return;
      var doc = selectedDocument(), id = input.getAttribute('data-row-id'), key = input.getAttribute('data-field');
      state.selectedRowId = id;
      var row = doc && (doc.rows || []).find(function (item, index) { return String(rowId(item, index)) === String(id); }); if (row) { editRow(row, key, input.value); var cell = input.closest('td'); if (cell) cell.classList.add('swd-changed'); }
    });
  }
  async function openProgramSource(context) {
    if (state.busy || state.dirty || state.configDirty || authoring) { notify('当前有未保存的步骤或配置，请先保存，再从程序卡片进入。'); return; }
    await refresh();
    if (context.source) {
      var doc = state.documents.find(function (item) { return item.id === context.source.documentId; });
      if (!doc || patternNames(doc).indexOf(context.source.pattern) < 0) { notify('步骤来源已变化，请返回程序重新选择。'); return; }
      state.documentId = doc.id; state.pattern = context.source.pattern; state.selectedRowId = ''; renderAll();
      openPatternEditor();
    } else {
      $('#swd-new-pattern-name').value = context.name || ''; setText('swd-create-status', '为程序目标配置步骤；保存后返回程序关联，无需在此生成。');
      $('#swd-create-dialog').showModal(); $('#swd-new-pattern-name').focus();
    }
  }
  function assistantSnapshot() {
    return JSON.parse(JSON.stringify({ document: selectedDocument() || null, pattern: state.pattern,
      config: state.config, materialVersion: state.materials.version,
      materials: { materials: state.materials.materials || [], conflicts: state.materials.conflicts || [], confirmations: state.materials.confirmations || {} },
      dirty: state.dirty, configDirty: state.configDirty,
      popupDraft: authoring ? { documentId: authoring.documentId, pattern: authoring.pattern, rows: authoring.rows } : null }));
  }
  function receiveAssistant(candidate) {
    if (assistantApplied.has(candidate.id)) return { applied: false, message: '该候选已送入编辑器' };
    if (state.busy || state.dirty || state.configDirty || authoring) throw new Error('请先处理现有未保存步骤和弹窗，再送入独立候选');
    assistantUndo = { state: JSON.parse(JSON.stringify(state)), changes: changedCells, id: candidate.id };
    state.documents.push(JSON.parse(JSON.stringify(candidate))); state.documentId = candidate.id;
    state.pattern = candidate.patterns[0] || ''; state.dirty = true; state.selectedRowId = ''; changedCells = {};
    assistantApplied.add(candidate.id); renderAll();
    assistantUndo.after = JSON.stringify(assistantSnapshot());
    setStatus('swd-editor-status', '助手候选已作为独立文档送入草稿；保存前可在助手窗口整批撤销。');
    return { applied: true };
  }
  function undoAssistant() {
    if (!assistantUndo) throw new Error('没有可撤销的助手批次');
    if (state.busy || JSON.stringify(assistantSnapshot()) !== assistantUndo.after) throw new Error('送入后已有编辑或保存，不能用旧批次覆盖，请保留当前草稿');
    var previous = assistantUndo;
    if (previous.kind === 'edit') {
      previous.target.forEach(function (row, index) { row.data = previous.beforeRows[index].data; });
      state.dirty = previous.dirty; changedCells = previous.changes;
    } else { state = previous.state; changedCells = previous.changes; }
    assistantApplied.delete(previous.id); assistantUndo = null; renderAll();
    if (authoring) renderDraft();
    return { undone: true };
  }
  function applyAssistantEdit(candidate) {
    if (assistantApplied.has(candidate.id)) return { applied: false, message: '该修改已应用' };
    var doc = selectedDocument(), target = candidate.scope === 'popup' ? authoring && authoring.rows : doc && doc.rows;
    if (state.busy || !doc || doc.id !== candidate.documentId || !target ||
        (candidate.scope === 'document' && authoring) || JSON.stringify(target) !== JSON.stringify(candidate.beforeRows)) throw new Error('编辑对象或步骤已改变，拒绝应用旧差异');
    if (!Array.isArray(candidate.rows) || candidate.rows.length !== target.length) throw new Error('字段修改不得增加、删除或重排步骤');
    candidate.rows.forEach(function (row, index) {
      var copy = Object.assign({}, row, { data: target[index].data });
      if (JSON.stringify(copy) !== JSON.stringify(target[index])) throw new Error('字段修改包含范围外改动');
    });
    assistantUndo = { kind: 'edit', id: candidate.id, beforeRows: JSON.parse(JSON.stringify(target)),
      target: target, dirty: state.dirty, changes: Object.assign({}, changedCells) };
    target.forEach(function (row, index) {
      if (row.data !== candidate.rows[index].data) {
        if (candidate.scope === 'popup') row.data = candidate.rows[index].data;
        else editRow(row, 'data', candidate.rows[index].data);
      }
    });
    assistantApplied.add(candidate.id); renderAll(); if (authoring) renderDraft();
    assistantUndo.after = JSON.stringify(assistantSnapshot());
    return { applied: true, kind: 'edit' };
  }
  window.MCUSWD = { applyAssistantEdit: applyAssistantEdit, receiveAssistant: receiveAssistant, undoAssistant: undoAssistant, assistantSnapshot: assistantSnapshot, refresh: refresh, state: function () { return state; }, save: saveDocument, generate: generate, deleteRow: deleteRow, openProgramSource: openProgramSource };
  bind(); renderAll(); refresh();
}());
