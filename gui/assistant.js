(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var token = JSON.parse($('connection').textContent).token;
  var current = null, pollTimer = null, submitting = false, pendingRequest = null;
  async function api(path, body) {
    var response = await fetch(path, { method: body === undefined ? 'GET' : 'POST',
      headers: { 'X-GUI-Session': token, 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body) });
    if (!response.ok) { var problem = await response.json(); throw new Error(problem.error || ('HTTP ' + response.status)); }
    return response.json();
  }
  function error(value) { $('error').textContent = value || ''; }
  function models(selected) {
    $('model').replaceChildren();
    ({'kimi': ['kimi-k2.6', 'kimi-k2.7-code', 'kimi-k3'], 'kimi-code': ['k3', 'k3-256k'], 'deepseek': ['deepseek-v4-pro', 'deepseek-flash']}[$('provider').value]).forEach(function (name) {
      var option = document.createElement('option'); option.value = name; option.textContent = name; $('model').appendChild(option);
    });
    if (selected) $('model').value = selected;
    modelOptions();
  }
  function modelOptions() {
    $('kimi-region-label').hidden = $('provider').value === 'deepseek';
    var coding = $('provider').value === 'kimi-code';
    $('kimi-region').options[0].textContent = coding ? '国内（api.kimi.com）' : '国内（api.moonshot.cn）';
    $('kimi-region').options[1].textContent = coding ? '国际（api.kimi.ai）' : '国际（api.moonshot.ai）';
    var fixedThinking = $('provider').value === 'kimi' && $('model').value !== 'kimi-k3';
    $('effort').disabled = fixedThinking;
    $('model-note').textContent = coding ? '使用 Kimi Code 控制台密钥及会员额度。K3 需 Moderato / Plus 及以上，当前档位支持最高 256K 上下文；选择后请重新填写订阅密钥并保存。' : (fixedThinking ? 'K2.6 / K2.7 Code 使用开启思考模式，不发送推理档位。地区需与密钥所属平台一致。' : '');
  }
  async function refresh() {
    var state = await api('/api/assistant/state'), settings = state.settings;
    $('model-label').textContent = settings.hasKey ? settings.model + ' · ' + settings.reasoning_effort : '请先配置模型与 API 密钥';
    $('history').replaceChildren();
    state.tasks.forEach(function (task) {
      var button = document.createElement('button'); button.textContent = task.text || '未命名任务';
      button.title = task.status + ' · ' + task.text;
      button.onclick = function () { select(task.id).catch(function (e) { error(e.message); }); };
      $('history').appendChild(button);
    });
    return settings;
  }
  async function context() {
    if (window.pywebview && window.pywebview.api) return window.pywebview.api.assistant_context();
    if (window.opener && !window.opener.closed && window.opener.MCUWorkbench) return window.opener.MCUWorkbench.assistantContext();
    throw new Error('无法读取主窗口草稿，请从工作台重新打开助手');
  }
  async function editorContext() {
    if (window.pywebview && window.pywebview.api) await window.pywebview.api.assistant_context(true);
    else if (window.opener && !window.opener.closed && window.opener.MCUWorkbench) window.opener.MCUWorkbench.open('swd');
    for (var attempt = 0; attempt < 50; attempt++) {
      var snapshot = await context();
      if (snapshot.swd && snapshot.swd.materialVersion) return snapshot;
      await new Promise(function (resolve) { setTimeout(resolve, 200); });
    }
    throw new Error('SWD编辑器尚未就绪，请稍后再次点击送入');
  }
  function contextLabel(snapshot) {
    var program = snapshot.program, swd = snapshot.swd || {};
    return (program && program.name ? '程序：' + program.name : '未载入程序') +
      (swd.document ? ' · SWD：' + swd.document.name + ' / ' + swd.pattern : '') +
      (swd.popupDraft ? ' · 含弹窗未保存步骤' : '') + ' · 回答绑定提问时的快照';
  }
  async function download(record, candidate, kind) {
    var query = new URLSearchParams({ id: record.id, candidate: candidate.id, kind: kind });
    var response = await fetch('/api/assistant/artifact?' + query, { headers: { 'X-GUI-Session': token } });
    if (!response.ok) throw new Error('候选文件无法读取');
    var url = URL.createObjectURL(await response.blob()), link = document.createElement('a');
    link.href = url; link.download = candidate.files[kind]; document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url);
  }
  function render(record) {
    current = record; $('result').hidden = false;
    $('context-label').textContent = contextLabel(record.context || {});
    $('stage').textContent = record.stage + ' · ' + record.status;
    $('question').textContent = record.text; $('answer').textContent = record.answer || record.error || '';
    $('conversation').replaceChildren();
    (record.history || []).forEach(function (turn) {
      var question = document.createElement('p'), answer = document.createElement('pre');
      question.textContent = turn.question; answer.textContent = turn.answer;
      $('conversation').append(question, answer);
    });
    $('send').textContent = record.status === 'completed' ? '继续追问' : '发送';
    $('cancel').disabled = record.status !== 'running'; $('send').disabled = record.status === 'running' || submitting;
    $('events').replaceChildren();
    (record.events || []).forEach(function (event) { var line = document.createElement('div'); line.className = 'muted'; line.textContent = event.tool + ' · ' + event.status + (event.message ? '：' + event.message : ''); $('events').appendChild(line); });
    $('candidates').replaceChildren();
    if (record.status === 'needs_input') {
      var form = document.createElement('form'); form.className = 'candidate';
      var heading = document.createElement('h2'); heading.textContent = '补充复位资料'; form.appendChild(heading);
      var scope = document.createElement('p'); scope.textContent = '仅用于 py32f420 / ' + record.conditions.product + ' 的指定寄存器。保存为本地用户确认知识，后续生成可复用；不会覆盖包内资料。不确定时可暂不填写。'; form.appendChild(scope);
      var inputs = (record.knowledgeQuestions || []).map(function (q) {
        var label = document.createElement('label');
        label.textContent = q.peripheral + '.' + q.register + '（0x' + q.address.toString(16).padStart(8, '0') + '）完整32位复位值，缺少 ' + q.fields.join('、');
        var value = document.createElement('input'); value.required = true; value.placeholder = '例如 0x00000000 或 全0'; label.appendChild(value); form.appendChild(label);
        var sourceLabel = document.createElement('label'); sourceLabel.textContent = '依据（手册位置、项目规范或用户工程确认）';
        var source = document.createElement('input'); source.required = true; source.maxLength = 1000; source.value = '用户工程确认'; sourceLabel.appendChild(source); form.appendChild(sourceLabel);
        return { id: q.id, value: value, source: source };
      });
      var save = document.createElement('button'); save.type = 'submit'; save.textContent = '保存补充并重新生成'; form.appendChild(save);
      form.onsubmit = async function (event) {
        event.preventDefault(); save.disabled = true; error('');
        try {
          var updated = await api('/api/assistant/confirm-knowledge', {id:record.id, context:await context(),
            answers:inputs.map(function (item) { return {id:item.id, value:item.value.value, source:item.source.value}; })});
          render(updated); await refresh();
        } catch (e) { error(e.message); }
        finally { save.disabled = false; }
      };
      $('candidates').appendChild(form);
    }
    (record.candidates || []).forEach(function (candidate) {
      var card = document.createElement('section'); card.className = 'candidate';
      var title = document.createElement('h2'); title.textContent = candidate.name; card.appendChild(title);
      if (candidate.kind === 'action') {
        var description = document.createElement('p'); description.textContent = candidate.notice; card.appendChild(description);
        var parameters = document.createElement('pre'); parameters.textContent = JSON.stringify(candidate.request, null, 2); card.appendChild(parameters);
        var execute = document.createElement('button'); execute.textContent = candidate.execution ? '查看已启动任务' : '确认参数并启动';
        execute.onclick = async function () {
          execute.disabled = true; error('');
          try {
            var value = await api('/api/assistant/execute', {id:record.id,candidate:candidate.id,context:await context()});
            if (window.pywebview && window.pywebview.api) await window.pywebview.api.assistant_job(value);
            else window.opener.MCUWorkbench.assistantJob(value);
            error('已提交工作台任务，请在主窗口查看实际进度与输出。取消聊天不会停止已提交的转换或生成。');
            await select(record.id);
          } catch (e) { error(e.message); }
          finally { execute.disabled = false; }
        };
        card.appendChild(execute); $('candidates').appendChild(card); return;
      }
      var edit = candidate.kind === 'edit';
      var note = document.createElement('p'); note.className = 'muted'; note.textContent = edit ? '字段差异已校验 · 其余步骤保留，旧流程未整体复验 · 尚未应用' : '独立候选 · 静态校验和向量生成通过 · 此文件未经过厂商编译或硬件验证'; card.appendChild(note);
      if (edit) {
        var diff = document.createElement('pre'); diff.textContent = candidate.diff.map(function (item) {
          return '第 ' + (item.rowIndex + 1) + ' 条 · ' + item.field + '\n' + item.before + ' → ' + item.after + '（掩码 ' + item.mask + '）';
        }).join('\n'); card.appendChild(diff);
      }
      var details = document.createElement('details'), summary = document.createElement('summary'); summary.textContent = '查看 ' + candidate.rows.length + ' 条步骤'; details.appendChild(summary);
      var rows = document.createElement('pre'); rows.className = 'steps'; rows.textContent = candidate.rows.map(function (r) { return [r.type, r.addr, r.data, r.description].join('  '); }).join('\n'); details.appendChild(rows); card.appendChild(details);
      (edit ? [] : ['excel', 'pattern']).forEach(function (kind) { var button = document.createElement('button'); button.textContent = kind === 'excel' ? '另存配置 Excel' : '下载 Pattern'; button.onclick = function () { download(record, candidate, kind).catch(function (e) { error(e.message); }); }; card.appendChild(button); });
      var apply = document.createElement('button'); apply.textContent = edit ? '确认差异并应用到草稿' : '送入 SWD 编辑器';
      apply.onclick = async function () {
        apply.disabled = true; error('');
        try {
          var snapshot = await editorContext();
          var staged = await api('/api/assistant/stage', { id: record.id, candidate: candidate.id, context: snapshot });
          if (window.pywebview && window.pywebview.api) await window.pywebview.api.receive_assistant(staged);
          else window.opener.MCUWorkbench.receiveAssistant(staged);
          error(edit ? '差异已应用到当前草稿，可整批撤销；尚未保存。' : '已作为独立草稿送入 SWD 编辑器；尚未保存或关联程序。');
        } catch (e) { error(e.message); }
        finally { apply.disabled = false; }
      }; card.appendChild(apply);
      $('candidates').appendChild(card);
    });
  }
  async function select(identity) {
    clearTimeout(pollTimer);
    var record = await api('/api/assistant/task?id=' + encodeURIComponent(identity)); render(record);
    if (record.status === 'running') pollTimer = setTimeout(function () { select(identity).catch(function (e) { error(e.message + '；可从历史重新打开任务'); }); }, 700);
  }
  $('send').onclick = async function () {
    if (submitting) return;
    submitting = true; $('send').disabled = true; error('');
    try {
      var snapshot = await context();
      var body = { text: $('prompt').value, parentId: current && current.status === 'completed' ? current.id : null, context: snapshot, conditions: { product: $('product').value,
        platform: $('platform').value, initialState: $('reset').checked ? 'reset' : 'unknown' } };
      var signature = JSON.stringify(body);
      if (!pendingRequest || pendingRequest.signature !== signature) pendingRequest = { signature: signature, id: crypto.randomUUID() };
      var record = await api('/api/assistant/start', Object.assign(body, { requestId: pendingRequest.id }));
      pendingRequest = null; $('prompt').value = ''; await refresh(); await select(record.id);
    } catch (e) { error(e.message); }
    finally { submitting = false; $('send').disabled = !!current && current.status === 'running'; }
  };
  $('cancel').onclick = async function () { if (!current) return; try { render(await api('/api/assistant/cancel', { id: current.id })); clearTimeout(pollTimer); await refresh(); } catch (e) { error(e.message); } };
  $('undo').onclick = async function () {
    try {
      if (window.pywebview && window.pywebview.api) await window.pywebview.api.undo_assistant();
      else if (window.opener) window.opener.MCUWorkbench.undoAssistant();
      else throw new Error('主窗口不可用');
      error('已整批撤销送入操作，原草稿恢复。');
    } catch (e) { error(e.message); }
  };
  $('new-task').onclick = function () { if (current && current.status === 'running') { error('请先等待或取消当前任务'); return; } current = null; pendingRequest = null; clearTimeout(pollTimer); $('prompt').value = ''; $('result').hidden = true; $('send').disabled = false; $('send').textContent = '发送'; $('reset').checked = false; error(''); };
  $('provider').onchange = function () { models(); $('key').value = ''; if ($('provider').value !== 'deepseek') $('kimi-region').value = 'china'; };
  $('model').onchange = modelOptions;
  $('clear-history').onclick = async function () {
    if (!window.confirm('清空本机助手任务、问答与候选下载文件？已送入编辑器的草稿和模型设置将保留。')) return;
    try {
      await api('/api/assistant/clear', {});
      current = null; $('new-task').click(); await refresh();
    } catch (e) { error(e.message); }
  };
  $('settings-open').onclick = async function () { try { var config = await refresh(); if (config.provider) $('provider').value = config.provider; models(config.model); $('kimi-region').value = config.kimi_region || 'international'; $('effort').value = config.reasoning_effort; $('tokens').value = config.max_tokens; $('remember').checked = config.remember; $('settings-status').textContent = config.error || (config.hasKey ? '当前服务商已有密钥' : '尚未配置密钥'); $('settings').showModal(); } catch (e) { error(e.message); } };
  async function saveSettings(clear) {
    try { await api('/api/assistant/settings', { provider: $('provider').value, model: $('model').value,
      apiKey: clear ? '' : $('key').value, clearKey: clear, remember: $('remember').checked,
      reasoning_effort: $('effort').value, max_tokens: Number($('tokens').value), kimi_region: $('kimi-region').value });
      $('key').value = ''; $('settings-status').textContent = clear ? '密钥已清除' : '已保存；发送问题才会调用模型'; await refresh();
    } catch (e) { $('settings-status').textContent = e.message; }
  }
  $('settings-save').onclick = function () { saveSettings(false); }; $('key-clear').onclick = function () { saveSettings(true); };
  $('connection-test').onclick = async function () {
    try {
      var record = await api('/api/assistant/test', {requestId:crypto.randomUUID()});
      $('settings').close(); current = null; await refresh(); await select(record.id);
    } catch (e) { $('settings-status').textContent = e.message; }
  };
  $('settings-close').onclick = function () { $('key').value = ''; $('settings').close(); };
  models(); refresh().catch(function (e) { error(e.message); });
}());
