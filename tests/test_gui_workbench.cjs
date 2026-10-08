const assert = require('assert');
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'gui', 'workbench.html'), 'utf8');
const js = fs.readFileSync(path.join(root, 'gui', 'workbench.js'), 'utf8');
const css = fs.readFileSync(path.join(root, 'gui', 'workbench.css'), 'utf8');

assert.match(html, /id="wb-program-frame"[^>]*data-src="\/program"/);
assert.match(html, /id="wb-file-picker"[^>]*multiple/);
assert.match(html, /webkitdirectory/);
assert.match(html, /id="wb-adapt"/);
assert.match(html, /id="wb-manual-pins"/);
assert.match(html, /id="wb-pin-list"/);
assert.match(html, /id="wb-label-marker"/);
assert.match(html, /id="wb-label-base"/);
assert.match(html, /id="wb-cp"/);
assert.match(html, /id="wb-link-dialog"/);
assert.strictEqual((html.match(/id="connection"/g) || []).length, 0, 'connection is injected once by the authenticated server');
for (const endpoint of ['/api/workbench', '/api/scan/input', '/api/scan/config', '/api/scan/register', '/api/scan/pins', '/api/scan/start', '/api/scan/status', '/api/scan/targets', '/api/scan/link', '/api/scan/output', '/api/scan/download']) {
  assert.ok(js.includes(endpoint), `missing endpoint ${endpoint}`);
}
assert.ok(js.includes("X-GUI-Session"));
assert.ok(js.includes('window.MCUWorkbench'));
assert.ok(js.includes('select_scan_files'));
assert.ok(js.includes('cp: adapt ? $(\'#wb-cp\').value : null'));
assert.ok(js.includes('encodeURIComponent(files[i].name)'));
assert.ok(js.includes('appendInputs: true'));
assert.ok(js.includes('input[data-platform]'), 'only platform checkboxes may form the platform request');
assert.match(css, /\.wb-scan-grid\{[^}]*align-items:start/);
assert.ok(js.includes("body.getAttribute('data-wb-render-key') === renderKey"));
assert.ok(js.includes("list.getAttribute('data-wb-render-key') === inputKey"));
assert.ok(js.includes("cpSelect.getAttribute('data-wb-options') !== cpKey"));
assert.ok(js.includes('state.previewCache'));
assert.ok(js.includes('async function statusRequest()'));
assert.ok(js.includes("if (state.scan.job) schedulePoll()"));
assert.ok(js.includes('window.desktopPreviewClosed'));
assert.ok(js.includes('forwardDesktopBridge'));
assert.ok(js.includes('resourcesChanged'));
assert.ok(js.includes('scheduleProgramStatus'));
assert.ok(!js.includes('snap.programRevision'));
assert.ok(!js.includes('snap.configurationSha'));
assert.ok(!js.includes('sample-files'));
assert.ok(!html.includes('workbench-prototype'));
assert.match(css, /\.wb-/);
console.log('workbench public contract: OK');

// A tiny browserless DOM checks the stateful interactions that are easy to regress.
async function interactionCheck() {
  const vm = require('vm');
  const nodes = new Map();
  const handlers = {};
  const timers = [];
  const make = (id, extra = {}) => {
    const attrs = Object.assign({}, extra.attrs);
    const node = Object.assign({ id, value: '', checked: false, hidden: false, disabled: false,
      textContent: '', innerHTML: '', className: '', style: {}, contentWindow: {},
      classList: { toggle() {}, add() {} },
      addEventListener(name, fn) { this['on' + name] = fn; },
      setAttribute(name, value) { attrs[name] = String(value); },
      getAttribute(name) { return attrs[name] == null ? null : attrs[name]; },
      showModal() { this.open = true; }, close() { this.open = false; }
    }, extra);
    nodes.set(id, node); return node;
  };
  for (const id of [...html.matchAll(/id="([^"]+)"/g)].map(m => m[1])) make(id);
  make('wb-output-preview');
  const views = ['home', 'program', 'scan'].map(page => make('view-' + page, { attrs: { 'data-page-view': page } }));
  const pageButtons = ['home', 'program', 'scan', 'program-card', 'scan-card'].map((id, i) => make('page-' + id, { attrs: { 'data-page': ['home', 'program', 'scan', 'program', 'scan'][i] }, classList: { toggle() {}, add() {}, contains(name) { return name === 'wb-nav-item'; } } }));
  const platforms = [make('platform-chroma', { value: 'chroma', checked: true }), make('platform-s100', { value: 's100', checked: true })];
  const body = make('body', { classList: { toggle() {}, add() {} } });
  const main = make('main', { className: 'wb-main' });
  const job = { id: 'a'.repeat(32), status: 'completed', logs: [], adapt: false, source: 'current', cp: null,
    inputIds: ['input-1'], result: { platforms: ['chroma', 's100'], files: [
      { path: 'chroma/scan.pat', platform: 'chroma', kind: 'pattern' },
      { path: 'chroma/scan_code.txt', platform: 'chroma', kind: 'code' },
      { path: 'chroma/scan_timing.txt', platform: 'chroma', kind: 'timing' }
    ] } };
  const wb = { program: { loaded: false, name: '', sha256: '', cps: [] }, scan: {
    inputs: [{ id: 'input-1', name: 'scan.wgl', size: 3, sha256: 'input' }], configuration: null, job, associations: []
  }};
  let outputReads = 0; let lastStatusBody = null; const uploadHeaders = []; const pinsBodies = []; const startBodies = []; let holdPins = false; const pendingPins = [];
  const response = value => ({ ok: true, status: 200, headers: new Headers({ 'content-type': 'application/json' }), json: async () => value });
  const context = {
    window: { addEventListener(name, fn) { handlers[name] = fn; } },
    document: { body, querySelector(selector) {
      if (selector === '.wb-main') return main;
      if (selector[0] === '#') return nodes.get(selector.slice(1)) || null;
      return null;
    }, querySelectorAll(selector) {
      if (selector === '[data-page-view]') return views;
      if (selector === '[data-page]') return pageButtons;
      if (selector === 'input[data-platform]') return platforms;
      return [];
    }, addEventListener(name, fn) { handlers[name] = fn; } },
    Headers, Event, console,
    setTimeout(fn) { timers.push(fn); return timers.length; }, clearTimeout() {},
    fetch: async (url, options = {}) => {
      if (url === '/api/workbench') return response(wb);
      if (url === '/api/scan/status') { lastStatusBody = JSON.parse(options.body || '{}'); return response({ scan: wb.scan }); }
      if (url === '/api/scan/input') { const name = decodeURIComponent(options.headers.get('X-File-Name')); uploadHeaders.push(options.headers.get('X-File-Name')); const id = 'input-' + name; return response({ id, name, size: 1, sha256: id }); }
      if (url === '/api/scan/pins') { pinsBodies.push(JSON.parse(options.body)); if (holdPins) return new Promise(resolve => pendingPins.push(resolve)); return response({ pins: ['TCK', 'TDO'], inputs: [{ id: 'input-1', name: 'scan.wgl', pins: ['tck', 'TDO'] }] }); }
      if (url === '/api/scan/start') { startBodies.push(JSON.parse(options.body)); return response({ jobId: 'b'.repeat(32) }); }
      if (String(url).startsWith('/api/scan/output')) { outputReads++; return response({ text: 'REAL OUTPUT' }); }
      throw new Error('unexpected ' + url);
    }
  };
  vm.runInNewContext(js, context);
  await Promise.resolve(); await Promise.resolve();
  context.window.MCUWorkbench.open('scan');
  await context.window.MCUWorkbench.refresh();
  await Promise.resolve(); await Promise.resolve();
  const resultBody = nodes.get('wb-result-body'); const inputList = nodes.get('wb-input-list');
  const resultMarkup = resultBody.innerHTML, inputMarkup = inputList.innerHTML;
  assert.equal(outputReads, 1);
  assert.ok(resultMarkup.includes('Full Pin'), 'result must show the completed job snapshot');
  handlers.click({target:{closest:()=>({id:'wb-start-scan',dataset:{}})},preventDefault(){}});
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.deepEqual({ labelMarker: startBodies[0].labelMarker, labelBase: startBodies[0].labelBase }, { labelMarker: null, labelBase: null }, 'empty label controls explicitly close labeling');
  await context.window.MCUWorkbench.refresh(); await Promise.resolve(); await Promise.resolve();
  nodes.get('wb-label-marker').value = 'Measure Iddq All'; nodes.get('wb-label-marker').oninput();
  assert.equal(nodes.get('wb-start-scan').disabled, true, 'a single label value blocks conversion before the request');
  assert.match(nodes.get('wb-start-hint').textContent, /同时填写/);
  nodes.get('wb-label-base').value = 'M-Iddq'; nodes.get('wb-label-base').oninput();
  assert.equal(nodes.get('wb-start-scan').disabled, true, 'an invalid label base blocks conversion before the request');
  assert.match(nodes.get('wb-start-hint').textContent, /字母或下划线开头/);
  nodes.get('wb-label-marker').value = ''; nodes.get('wb-label-base').value = ''; nodes.get('wb-label-base').oninput();
  assert.equal(nodes.get('wb-start-scan').disabled, false, 'clearing both label controls restores closed labeling');
  nodes.get('wb-adapt').checked = true; nodes.get('wb-adapt').onchange();
  assert.ok(resultBody.innerHTML.includes('Full Pin'), 'changing the next-run setting must not relabel an old result');
  await context.window.MCUWorkbench.refresh(); await Promise.resolve(); await Promise.resolve();
  assert.equal(resultBody.innerHTML, resultMarkup, 'unchanged status must not rebuild result DOM');
  assert.equal(inputList.innerHTML, inputMarkup, 'unchanged status must not rebuild input queue');
  assert.equal(outputReads, 1, 'cached preview must avoid duplicate output reads');
  nodes.get('wb-manual-pins').checked = true; nodes.get('wb-manual-pins').onchange();
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.deepEqual(pinsBodies, [{ inputIds: ['input-1'] }], 'manual mode reads only active WGL input ids');
  assert.ok(nodes.get('wb-pin-list').innerHTML.includes('TCK'));
  assert.equal(nodes.get('wb-adapt').checked, false, 'manual pins and Excel adaptation are mutually exclusive');
  nodes.get('wb-source').value = 'current';
  nodes.get('wb-pin-list').onchange({ target: { dataset: { pin: 'TDO' }, checked: false } });
  assert.equal(nodes.get('wb-start-scan').disabled, false, 'one selected pin per input keeps manual conversion valid');
  nodes.get('wb-label-marker').value = 'Measure Iddq All';
  nodes.get('wb-label-base').value = 'M_Iddq';
  handlers.click({target:{closest:()=>({id:'wb-start-scan',dataset:{}})},preventDefault(){}});
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.deepEqual(startBodies[1].manualPins, ['TCK'], 'start freezes the selected normalized manual pin names');
  assert.equal(startBodies[1].adapt, false);
  assert.equal(startBodies[1].source, 'current', 'manual mode keeps the established configuration-source contract');
  assert.deepEqual({ labelMarker: startBodies[1].labelMarker, labelBase: startBodies[1].labelBase }, { labelMarker: 'Measure Iddq All', labelBase: 'M_Iddq' }, 'click sends the enabled label settings');
  assert.equal(nodes.get('wb-result-body').innerHTML.includes('手动管脚 · 1 个'), true, 'task snapshot records manual selection count');
  assert.equal(nodes.get('wb-result-body').innerHTML.includes('Measure Iddq All'), true, 'task snapshot displays the enabled label marker');
  assert.equal(nodes.get('wb-result-body').innerHTML.includes('M_Iddq'), true, 'task snapshot displays the enabled label base');
  nodes.get('wb-label-marker').value = 'Future Marker'; nodes.get('wb-label-base').value = 'Future_Base'; nodes.get('wb-label-base').oninput();
  assert.equal(nodes.get('wb-result-body').innerHTML.includes('Future Marker'), false, 'editing the next-run label controls cannot relabel the running task snapshot');
  await context.window.MCUWorkbench.refresh(); await Promise.resolve(); await Promise.resolve();
  const click = dataset => handlers.click({target:{closest:()=>({dataset})},preventDefault(){}});
  for (const [kind, file] of [['code','chroma/scan_code.txt'],['timing','chroma/scan_timing.txt'],['pattern','chroma/scan.pat']]) {
    click({previewKind:kind}); await Promise.resolve(); await Promise.resolve();
    assert.equal(context.window.MCUWorkbench.state().previewFile, file, 'tab must select the corresponding output');
    assert.ok(resultBody.innerHTML.includes('data-preview-kind="'+kind+'" aria-pressed="true"'));
  }
  job.result.files.forEach(f=>{f.sourceName='scan.wgl';});
  job.result.files.push({path:'chroma/second.pat',platform:'chroma',kind:'pattern',sourceName:'second.wgl'}, {path:'chroma/second.scan.inc',platform:'chroma',kind:'code',sourceName:'second.wgl'});
  click({outputFile:'chroma/second.pat'}); await Promise.resolve();
  click({previewKind:'code'}); await Promise.resolve(); await Promise.resolve();
  assert.equal(context.window.MCUWorkbench.state().previewFile, 'chroma/second.scan.inc', 'switch preserves selected source');
  await timers.shift()(); await Promise.resolve(); await Promise.resolve();
  assert.ok(lastStatusBody && !Object.prototype.hasOwnProperty.call(lastStatusBody, 'draft'), 'status without iframe draft must omit empty draft');
  const file = name => ({ name, arrayBuffer: async () => new ArrayBuffer(1) });
  const picker = nodes.get('wb-file-picker');
  picker.onchange({ target: { files: [file('扫描一.wgl'), file('第二.wgl')], value: '' } }); await new Promise(resolve => setTimeout(resolve, 10));
  picker.onchange({ target: { files: [file('第三.wgl')], value: '' } }); await new Promise(resolve => setTimeout(resolve, 10));
  const namesAfterAppend = context.window.MCUWorkbench.state().scan.inputs.map(x => x.name);
  assert.deepEqual(namesAfterAppend, ['scan.wgl', '扫描一.wgl', '第二.wgl', '第三.wgl']);
  assert.equal(uploadHeaders[0], encodeURIComponent('扫描一.wgl'), 'Unicode file name must be encoded in request header');
  handlers.click({ target: { closest: () => ({ disabled: false, dataset: { removeInput: 'input-扫描一.wgl' } }) } });
  assert.ok(!context.window.MCUWorkbench.state().scan.inputs.some(x => x.name === '扫描一.wgl'));
  picker.onchange({ target: { files: [file('扫描一.wgl')], value: '' } }); await new Promise(resolve => setTimeout(resolve, 10));
  assert.ok(context.window.MCUWorkbench.state().scan.inputs.some(x => x.name === '扫描一.wgl'), 'reimporting a removed id must restore it');
  const frame = nodes.get('wb-program-frame'); context.window.MCUWorkbench.open('program'); const firstSrc = frame.src; context.window.MCUWorkbench.open('program');
  assert.equal(frame.src, firstSrc); assert.equal(firstSrc, '/program');
  holdPins = true;
  wb.scan.inputs[0].sha256 = 'changed';
  await context.window.MCUWorkbench.refresh(); await Promise.resolve();
  assert.equal(context.window.MCUWorkbench.state().manualPins.status, 'loading');
  nodes.get('wb-adapt').checked = true; nodes.get('wb-adapt').onchange();
  assert.equal(nodes.get('wb-manual-pins').checked, false, 'Excel adaptation also cancels an in-flight manual read');
  nodes.get('wb-manual-pins').checked = true; nodes.get('wb-manual-pins').onchange();
  assert.equal(pendingPins.length, 2, 'closing while a pin read is pending allows a fresh read after reopening');
  pendingPins[1](response({ pins: ['TCK'], inputs: [{ id: 'input-1', pins: ['TCK'] }] }));
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal(context.window.MCUWorkbench.state().manualPins.status, 'ready');
}

interactionCheck().then(() => console.log('workbench interaction contract: OK')).catch(error => { console.error(error); process.exitCode = 1; });
