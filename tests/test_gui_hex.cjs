/* Public interaction contract for the standalone HEX page. */
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const html = fs.readFileSync('gui/hex.html', 'utf8');
const source = fs.readFileSync('gui/hex.js', 'utf8');
assert.match(html, /id="hex-picker"[^>]*multiple/);
for (const endpoint of ['/api/hex/state', '/api/hex/input', '/api/hex/start', '/api/hex/clear', '/api/hex/preview', '/api/hex/download']) assert.ok(source.includes(endpoint), endpoint);
assert.ok(source.includes('X-GUI-Session'));
assert.ok(!source.includes('.innerHTML'), 'HEX UI must use textContent/DOM nodes');

function element(tag) { return { tagName: tag.toUpperCase(), children: [], firstChild: null, textContent: '', className: '', hidden: false, disabled: false, dataset: {}, value: '', checked: false, appendChild(child) { this.children.push(child); this.firstChild = this.children[0]; return child; }, removeChild(child) { this.children = this.children.filter((item) => item !== child); this.firstChild = this.children[0] || null; }, setAttribute(name, value) { this[name] = String(value); }, addEventListener(name, fn) { this.listeners = this.listeners || {}; this.listeners[name] = fn; }, click() { if (this.listeners && this.listeners.click) this.listeners.click({ target: this, stopPropagation() {} }); } }; }
const ids = ['connection', 'hex-app', 'hex-connection', 'hex-chip', 'hex-profile', 'hex-pick', 'hex-picker', 'hex-clear', 'hex-select-all', 'hex-start', 'hex-profile-info', 'hex-status', 'hex-task-count', 'hex-task-list', 'hex-detail-actions', 'hex-detail-body', 'hex-download'];
const nodes = new Map(ids.map((id) => [id, element(id === 'hex-picker' ? 'input' : 'div')]));
nodes.get('connection').textContent = JSON.stringify({ token: 'contract-token' });
const profiles = [
  { id: 'stm-a', chip: 'STM32', label: 'A版', mode: 'Pattern', platform: 'Chroma', pins: ['D0', 'D1'], timeset: 'TS1', pageSize: 256, verify: 'CRC', erase: '页擦除', enabled: true },
  { id: 'stm-b', chip: 'STM32', label: 'B版', mode: 'Pattern', platform: 'S100', pins: ['D0'], timeset: 'TS2', pageSize: 128, verify: '逐字节', erase: '整片', enabled: false, reason: '缺少 S100 资料' },
  { id: 'gd-a', chip: 'GD32', label: 'A版', mode: 'Pattern', platform: 'Chroma', pins: ['D2'], timeset: 'TS3', pageSize: 512, verify: 'CRC', erase: '页擦除', enabled: true }
];
let current = { profiles, tasks: [], running: false };
const calls = [];
let rejectInput = false;
function response(body, type = 'application/json') { return { ok: true, status: 200, headers: { get: () => type }, json: async () => body, text: async () => typeof body === 'string' ? body : JSON.stringify(body), blob: async () => new Blob([String(body)]) }; }
async function fetchStub(path, options = {}) { calls.push({ path, options }); if (path === '/api/hex/state') return response(current); if (path === '/api/hex/input') { if (rejectInput) return { ok: false, status: 422, headers: { get: () => 'application/json' }, json: async () => ({ error: 'HEX 校验失败' }) }; const name = decodeURIComponent(options.headers.get('X-File-Name')); current.tasks.push({ id: 't' + current.tasks.length, name, status: 'ready', bytes: 4, logs: [] }); return response({ task: current.tasks[current.tasks.length - 1] }); } if (path === '/api/hex/start') { const body = JSON.parse(options.body); assert.deepStrictEqual(body, { taskIds: ['t0', 't1'], profileId: 'stm-a' }); current = { ...current, running: true, tasks: current.tasks.map((task) => ({ ...task, status: body.taskIds.includes(task.id) ? 'queued' : task.status, profileId: body.profileId })) }; return response(current); } if (path === '/api/hex/clear') { current = { profiles, tasks: [], running: false }; return response(current); } if (path.startsWith('/api/hex/preview')) return response('safe <preview>\n', 'text/plain'); if (path.startsWith('/api/hex/download')) return response('ZIP'); throw new Error('unexpected ' + path); }
const context = { console, Blob, Headers, URL: { createObjectURL: () => 'blob:test', revokeObjectURL() {} }, setTimeout, clearTimeout, fetch: fetchStub, document: { getElementById: (id) => nodes.get(id), createElement: (tag) => element(tag) }, window: {} }; context.window = context;
vm.runInNewContext(source, context, { filename: 'hex.js' });
(async () => {
  await context.MCUHex.refresh();
  assert.strictEqual(context.MCUHex.state().chip, 'STM32');
  assert.strictEqual(context.MCUHex.state().profileId, 'stm-a');
  const profileOptions = nodes.get('hex-profile').children;
  assert.strictEqual(profileOptions.length, 2, 'version selector is filtered by chip');
  assert.strictEqual(profileOptions[1].disabled, true, 'unsupported version cannot be selected');
  const allText = (node) => [node.textContent, ...(node.children || []).flatMap(allText)].join(' ');
  assert.ok(allText(nodes.get('hex-profile-info')).includes('D0 → '));
  assert.ok(allText(nodes.get('hex-profile-info')).includes('当前已验证相对地址范围为 0～64 KiB'));
  const file = (name) => ({ name, size: 4 });
  await context.MCUHex.addFiles([file('扫描一.hex'), file('second.hex')]);
  const upload = calls.filter((call) => call.path === '/api/hex/input');
  assert.strictEqual(upload.length, 2);
  assert.strictEqual(upload[0].options.headers.get('X-File-Name'), encodeURIComponent('扫描一.hex'));
  rejectInput = true;
  await context.MCUHex.addFiles([file('bad.hex')]);
  assert.ok(nodes.get('hex-status').textContent.includes('HEX 校验失败'), '422 input errors are shown');
  rejectInput = false;
  context.MCUHex.state().checked = { t0: true, t1: true };
  context.MCUHex.state().options['stm-a'] = {pins:['CLK','DATA'], verify:false};
  await context.MCUHex.start();
  const posted = JSON.parse(calls.find(call=>call.path==='/api/hex/start').options.body);
  assert.deepStrictEqual(posted.pins,['CLK','DATA']); assert.strictEqual(posted.verify,false);
  assert.ok(calls.some((call) => call.path === '/api/hex/start'));
  context.MCUHex.state().running = false;
  await nodes.get('hex-clear').listeners.click();
  assert.strictEqual(current.tasks.length, 0);
  assert.ok(calls.some((call) => call.path === '/api/hex/clear'));
  console.log('HEX UI contract: PASS');
})().catch((error) => { console.error(error); process.exitCode = 1; });
