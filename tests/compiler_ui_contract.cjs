/* Small browser-contract checks for the standalone compiler page. */
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const html = fs.readFileSync('gui/compiler.html', 'utf8');
const source = fs.readFileSync('gui/compiler.js', 'utf8');
assert.ok(/id="compiler-folder-picker"[^>]*webkitdirectory/.test(html));
['/api/compiler/create', '/api/compiler/file', '/api/compiler/ready', '/api/compiler/start', '/api/compiler/state', '/api/compiler/log', '/api/compiler/download'].forEach((path) => assert.ok(source.includes(path), path));
assert.ok(!source.includes('.innerHTML'), 'compiler UI must keep compiler text out of HTML interpolation');

function element(tag) {
  return { tagName: tag.toUpperCase(), children: [], firstChild: null, textContent: '', className: '', hidden: false, disabled: false, dataset: {}, value: '', checked: false,
    appendChild(child) { this.children.push(child); this.firstChild = this.children[0]; return child; }, removeChild(child) { this.children = this.children.filter((item) => item !== child); this.firstChild = this.children[0] || null; },
    setAttribute(name, value) { this[name] = String(value); }, getAttribute(name) { return this[name]; }, addEventListener(name, fn) { this.listeners = this.listeners || {}; this.listeners[name] = fn; }, click() { if (this.listeners && this.listeners.click) this.listeners.click({ target: this, stopPropagation() {} }); }
  };
}
const nodes = new Map();
['connection', 'compiler-connection', 'compiler-folder-picker', 'compiler-pick-folder', 'compiler-select-all', 'compiler-start', 'compiler-start-one', 'compiler-status', 'compiler-task-count', 'compiler-task-list', 'compiler-toolbar-hint', 'compiler-detail-actions', 'compiler-detail-body', 'compiler-download-log', 'compiler-download-output'].forEach((id) => nodes.set(id, element('div')));
nodes.get('connection').textContent = JSON.stringify({ token: 'contract-token' });
nodes.get('compiler-folder-picker').files = [];
const calls = [];
nodes.set('compiler-mode-controls', element('div'));
nodes.set('compiler-clear', element('button'));
nodes.set('compiler-app', element('main'));
let failStart = false;
const states = [
  { tasks: [], running: false, tools: { chroma: { available: true, path: 'C:/CRAFT' } } },
  { tasks: [{ id: 't1', name: 'demo', platform: 'chroma', status: 'ready', phase: '等待编译', result: null }], running: false, tools: { chroma: { available: true, path: 'C:/CRAFT' } } },
  { tasks: [{ id: 't1', name: 'demo', platform: 'chroma', status: 'ready', phase: '等待编译', result: null }], running: false, tools: { chroma: { available: true, path: 'C:/CRAFT' } } },
  { tasks: [{ id: 't1', name: 'demo', entry: 'main.pln', platform: 'chroma', status: 'failed', phase: '编译失败', result: { diagnostics: [{ severity: 'error', file: 'main.c', line: 8, message: 'bad input', cause: '示例原因', advice: '查看日志' }], outputAvailable: false, elapsed: 1.2 } }], running: false, tools: { chroma: { available: true, path: 'C:/CRAFT' } } }
];
states.forEach(state => { state.modes = { chroma: { all: '全部', dec: '仅 DEC', pat: '仅 PAT', pln: '仅 PLN' }, s100: { all: '全部', prg: '仅 PRG' } }; });
function response(body, type = 'application/json') { return { ok: true, status: 200, headers: { get: () => type }, json: async () => body, text: async () => typeof body === 'string' ? body : JSON.stringify(body), blob: async () => new Blob([String(body)]) }; }
let stateIndex = 0;
const startCalls = [];
async function fetchStub(path, options = {}) {
  calls.push({ path, options });
  if (path === '/api/compiler/clear') { states[states.length - 1].tasks = []; return response({tasks: []}); }
  if (path === '/api/compiler/state') return response(states[Math.min(stateIndex++, states.length - 1)]);
  if (path === '/api/compiler/create') return response({ id: 't1' });
  if (path === '/api/compiler/file') return response({ ok: true });
  if (path === '/api/compiler/ready') return response({ id: 't1', status: 'ready' });
  if (path === '/api/compiler/start') { startCalls.push(JSON.parse(options.body)); if (failStart) return { ok: false, status: 409, headers: { get: () => 'application/json' }, json: async () => ({ error: '队列忙' }) }; return response({ running: true }); }
  if (path.startsWith('/api/compiler/log')) return response({ text: stateIndex >= 4 ? 'final log\n' : 'safe log\n' });
  return response({ ok: true });
}
const context = { console, Blob, Headers, URL, setTimeout, clearTimeout, fetch: fetchStub, document: { getElementById: (id) => nodes.get(id), createElement: (tag) => element(tag) }, window: {}, setInterval, clearInterval };
context.window = context;
vm.runInNewContext(source, context, { filename: 'compiler.js' });

(async () => {
  const one = { name: 'main.pln', webkitRelativePath: 'firmware/main.pln' };
  const two = { name: 'inc.h', webkitRelativePath: 'firmware/include/inc.h' };
  assert.strictEqual(JSON.stringify(context.MCUCompiler.groupFiles([one, two]).map((g) => [g.name, g.files.map((f) => f.name)])), JSON.stringify([['firmware', ['main.pln', 'include/inc.h']]]));
  await context.MCUCompiler.addFolder([one, two]);
  const uploadCalls = calls.filter((call) => call.path === '/api/compiler/file');
  assert.strictEqual(uploadCalls.length, 2);
  assert.strictEqual(uploadCalls[0].options.headers.get('X-File-Name'), 'main.pln');
  assert.strictEqual(uploadCalls[1].options.headers.get('X-File-Name'), 'include%2Finc.h');
  assert.strictEqual(context.MCUCompiler.state().tasks[0].status, 'ready');
  context.MCUCompiler.state().selectedId = 't1';
  await context.MCUCompiler.refresh();
  assert.strictEqual(context.MCUCompiler.state().selectedId, 't1', 'polling must preserve the selected task');
  await context.MCUCompiler.startOne();
  assert.strictEqual(JSON.stringify(startCalls[0].ids), JSON.stringify(['t1']), 'single-task compile submits only the selected id');
  assert.strictEqual(context.MCUCompiler.state().tasks[0].status, 'failed');
  assert.strictEqual(context.MCUCompiler.state().logText, 'final log\n', 'terminal refresh reloads the final compiler log');
  failStart = true;
  await context.MCUCompiler.startOne();
  assert.strictEqual(nodes.get('compiler-status').textContent, '提交编译失败：队列忙', 'start failure is shown in the status area');
  const warning = (file, line, message = 'warning C4229: ignored modifier') => ({ severity: 'warning', file, line, message: file + '(' + line + ') : ' + message, cause: '原因', advice: '建议' });
  const diagnostics = [warning('a.h', 110), warning('a.h', 111), warning('b.h', 8), warning('a.h', 112, 'warning C4996: deprecated'),
    { severity: 'error', message: 'same error' }, { severity: 'error', message: 'same error' }];
  states[states.length - 1].tasks[0].result.diagnostics = diagnostics;
  const original = JSON.stringify(diagnostics);
  await context.MCUCompiler.refresh();
  const list = nodes.get('compiler-detail-body').children.find(n => n.className === 'compiler-diagnostics');
  assert.strictEqual(list.children.length, 4, 'same warning across locations folds; different warnings and errors remain separate');
  const group = list.children[0];
  assert.ok(group.children[0].textContent.includes('3'), 'group shows occurrence count');
  const details = group.children.find(n => n.tagName === 'DETAILS');
  assert.ok(details && !details.open, 'repeated locations are collapsed by default');
  assert.strictEqual(details.children.length, 4, 'summary plus all three originals');
  assert.ok(details.children[2].textContent.includes('a.h(111)'), 'original location preserved');
  assert.strictEqual(JSON.stringify(diagnostics), original, 'presentation must not change stored diagnostics');
  const walk = node => [node, ...node.children.flatMap(walk)];
  assert.ok(!walk(nodes.get('compiler-task-list')).some(n => n.tagName === 'SELECT'), 'cards no longer have selectors');
  const mode = walk(nodes.get('compiler-mode-controls')).find(n => n.dataset.platform === 'chroma');
  assert.ok(mode, 'toolbar exposes platform selectors');
  assert.deepStrictEqual(mode.children.map(n => n.value), ['all', 'dec', 'pat', 'pln']);
  mode.value = 'pat'; mode.listeners.change({ target: mode, stopPropagation() {} });
  await context.MCUCompiler.refresh();
  assert.strictEqual(walk(nodes.get('compiler-mode-controls')).find(n => n.dataset.platform === 'chroma').value, 'pat', 'refresh preserves the chosen mode');
  await context.MCUCompiler.startOne();
  assert.strictEqual(startCalls[startCalls.length - 1].modes.t1, 'pat', 'submitted task carries its selected mode');
  states[states.length - 1].tasks.push({id:'t2',name:'second',platform:'chroma',status:'ready'}, {id:'t3',name:'third',platform:'s100',status:'ready'});
  await context.MCUCompiler.refresh();
  const s100 = walk(nodes.get('compiler-mode-controls')).find(n => n.dataset.platform === 's100');
  s100.value = 'prg'; s100.listeners.change();
  context.MCUCompiler.state().checked = {t1:true,t2:true,t3:true};
  await context.MCUCompiler.start();
  assert.deepStrictEqual(startCalls[startCalls.length - 1].modes, {t1:'pat',t2:'pat',t3:'prg'});
  context.MCUCompiler.state().running = true;
  await nodes.get('compiler-clear').listeners.click();
  assert.strictEqual(calls.filter(c => c.path === '/api/compiler/clear').length, 0);
  context.MCUCompiler.state().running = false;
  await nodes.get('compiler-clear').listeners.click();
  assert.strictEqual(calls.filter(c => c.path === '/api/compiler/clear').length, 1);
  assert.strictEqual(context.MCUCompiler.state().tasks.length, 0);
  assert.strictEqual(context.MCUCompiler.state().selectedId, '');
  assert.ok(nodes.get('compiler-status').textContent.includes('磁盘文件已保留'));
  const fileEntry = name => ({name, isFile:true, file: resolve => resolve({name, size:4})});
  const directory = (name, pages) => ({name, isDirectory:true, createReader() { let index=0; return {readEntries:resolve => resolve(pages[index++] || [])}; }});
  const folders = [directory('first', [[fileEntry('main.pln')], [directory('inc', [[fileEntry('a.h')]])]]), directory('second', [[fileEntry('main.prj')]])];
  const beforeDrop = calls.length;
  let prevented = false;
  await nodes.get('compiler-app').listeners.drop({preventDefault(){prevented=true;}, dataTransfer:{types:['Files'],items:folders.map(entry=>({kind:'file',webkitGetAsEntry:()=>entry}))}});
  assert.ok(prevented, 'drop prevents navigation');
  assert.deepStrictEqual(calls.slice(beforeDrop).filter(c=>c.path==='/api/compiler/create').map(c=>JSON.parse(c.options.body).name), ['first','second']);
  assert.deepStrictEqual(calls.slice(beforeDrop).filter(c=>c.path==='/api/compiler/file').map(c=>decodeURIComponent(c.options.headers.get('X-File-Name'))), ['main.pln','inc/a.h','main.prj']);
  const beforeFile = calls.length;
  await nodes.get('compiler-app').listeners.drop({preventDefault(){},dataTransfer:{types:['Files'],items:[{kind:'file',webkitGetAsEntry:()=>fileEntry('loose.prj')}]}});
  assert.strictEqual(calls.length, beforeFile, 'loose files are rejected before creating tasks');
  assert.ok(nodes.get('compiler-status').textContent.includes('文件夹'));
  const dropEvent = entry => ({preventDefault(){},dataTransfer:{types:['Files'],items:[{kind:'file',webkitGetAsEntry:()=>entry}]}});
  context.MCUCompiler.state().uploading = true;
  await nodes.get('compiler-app').listeners.drop(dropEvent(folders[0]));
  assert.strictEqual(calls.length, beforeFile, 'busy upload blocks a second drop');
  context.MCUCompiler.state().uploading = false;
  await nodes.get('compiler-app').listeners.drop(dropEvent({name:'blocked',isDirectory:true,createReader:()=>({readEntries:(ok,fail)=>fail(new Error('access denied'))})}));
  assert.strictEqual(context.MCUCompiler.state().uploading, false, 'read failure releases upload lock');
  assert.ok(nodes.get('compiler-status').textContent.includes('access denied'));
  console.log('compiler UI contract: PASS');
})().catch((error) => { console.error(error); process.exitCode = 1; });
