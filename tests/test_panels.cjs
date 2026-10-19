const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const panels = require('../static/panels.js');
const messages = require('../static/i18n-en.js');
const { translator } = require('../static/i18n.js');
let checks = 0;
function check(fn) { fn(); checks++; }
const near = (actual, expected) => assert.ok(Math.abs(actual - expected) < .01, `${actual} != ${expected}`);
const total = (widths) => widths.reduce((a, b) => a + b, 0);
const memory = () => { const items = new Map(); return { getItem: key => items.get(key) || null, setItem: (key, value) => items.set(key, value), removeItem: key => items.delete(key) }; };
check(() => assert.deepEqual(panels.proportions([200, 500, 300]), [.2, .5, .3]));
for (const bad of [null, [], [1, 2], [0, 1, 1], [-1, 1, 1], [NaN, 1, 1], [Infinity, 1, 1], ['2', 1, 1]]) {
  check(() => assert.equal(panels.proportions(bad), null));
}
check(() => assert.equal(panels.proportions([1e308, 1e308, 1e308]), null));
check(() => assert.deepEqual(panels.moveDivider([222, 520, 452], 1, 100), [222, 620, 352]));
check(() => assert.deepEqual(panels.moveDivider([222, 520, 452], 0, 100), [322, 420, 452]));
check(() => assert.deepEqual(panels.moveDivider([222, 520, 452], 1, 9999), [222, 652, 320]));
check(() => assert.deepEqual(panels.moveDivider([222, 520, 452], 1, -9999), [222, 360, 612]));
check(() => assert.deepEqual(panels.moveDivider([222, 520, 452], 0, -9999), [190, 552, 452]));
check(() => assert.deepEqual(panels.moveDivider([222, 520, 452], 1, NaN), [222, 520, 452]));
check(() => assert.deepEqual(panels.fitWidths([222, 520, 452], 1194), [222, 520, 452]));
for (const width of [500, 870, 966, 1194, 1800]) {
  check(() => {
    const result = panels.fitWidths([.001, .998, .001], width);
    near(total(result), width);
    result.forEach((value, index) => assert.ok(value >= panels.minimums(width)[index] - .001));
  });
}
check(() => assert.deepEqual(panels.fitWidths(null, 0), [0, 0, 0]));
const storage = memory();
check(() => { panels.writePreference(storage, [222, 520, 452]); assert.deepEqual(panels.readPreference(storage), panels.proportions([222, 520, 452])); });
check(() => { panels.writePreference(storage, null); assert.equal(panels.readPreference(storage), null); });
for (const raw of ['{broken', '{"version":2,"widths":[1,1,1]}', '{"version":1,"widths":[0,1,1]}', 'null']) {
  check(() => { storage.setItem(panels.STORAGE_KEY, raw); assert.equal(panels.readPreference(storage), null); });
}
const denied = { getItem() { throw Error('blocked'); }, setItem() { throw Error('blocked'); }, removeItem() { throw Error('blocked'); } };
check(() => { panels.writePreference(denied, [1, 1, 1]); panels.writePreference(denied, null); assert.equal(panels.readPreference(denied), null); });
const source = fs.readFileSync(path.join(__dirname, '../static/panels.js'), 'utf8');
check(() => {
  const keys = [...source.matchAll(/"([^"\n]*\p{Script=Han}[^"\n]*)"/gu)].map(match => match[1]);
  assert.deepEqual(keys.filter(key => !Object.hasOwn(messages, key)), []);
});

// Exercise actual controller events without a browser dependency or course data.
function controller({ storage = memory(), desktop = true, language = 'zh' } = {}) {
  const listeners = new Map(), nodes = new Map();
  const classList = () => { const set = new Set(); return { add: key => set.add(key), remove: key => set.delete(key), toggle(key, on) { if (on) set.add(key); else set.delete(key); }, contains: key => set.has(key) }; };
  function node(id) {
    const events = {}, attrs = {};
    const element = { classList: classList(), events, attrs, dataset: {}, style: {}, hidden: false, textContent: '',
      addEventListener: (type, fn) => events[type] = fn, setAttribute: (key, value) => attrs[key] = value,
      setPointerCapture(id) { element.capture = id; }, hasPointerCapture: id => element.capture === id,
      releasePointerCapture() { element.capture = null; }, focus() {} };
    nodes.set(id, element); return element;
  }
  const workspace = node('workspace');
  let defaults = [222, 520, 452];
  workspace.style = { gridTemplateColumns: '', removeProperty() { this.gridTemplateColumns = ''; }, setProperty() {} };
  const widths = () => workspace.style.gridTemplateColumns ? workspace.style.gridTemplateColumns.split(' ').map(parseFloat) : defaults.slice();
  ['library-panel', 'main-content', 'notes-panel'].forEach((id, index) => {
    node(id).getBoundingClientRect = () => ({ width: widths()[index], left: 24 + total(widths().slice(0, index)) + 18 * index, right: 24 + total(widths().slice(0, index + 1)) + 18 * index });
  });
  workspace.getBoundingClientRect = () => ({ left: 0 });
  ['resize-library', 'resize-notes', 'reset-layout', 'layout-announcement'].forEach(node);
  const media = { matches: desktop, addEventListener: (type, fn) => media.changed = fn };
  const window = { document: { querySelector: () => workspace, getElementById: id => nodes.get(id), body: { classList: classList() } },
    LectureI18n: translator(messages, language), localStorage: storage, matchMedia: () => media,
    addEventListener: (type, fn) => listeners.set(type, fn), requestAnimationFrame: fn => { window.frame = fn; return 1; },
    getComputedStyle: () => ({ paddingBottom: '24px' }) };
  vm.runInNewContext(source, { window });
  const event = (extra = {}) => ({ button: 0, pointerId: 7, clientX: 800, preventDefault() {}, ...extra });
  const fire = (id, type, extra) => nodes.get(id).events[type](event(extra));
  const global = (type, extra) => listeners.get(type)(event(extra));
  const flush = () => { if (window.frame) { const frame = window.frame; window.frame = null; frame(); } };
  return { nodes, workspace, window, widths, storage, media, fire, global, flush, resize(next) { defaults = next; global('resize'); flush(); } };
}
const ui = controller();
check(() => { assert.equal(ui.workspace.dataset.panelsReady, 'true'); assert.equal(ui.nodes.get('reset-layout').hidden, false); assert.equal(ui.workspace.style.gridTemplateColumns, ''); });
check(() => { ui.fire('resize-notes', 'pointerdown'); ui.global('pointermove', { clientX: 900 }); assert.deepEqual(ui.widths(), [222, 620, 352]); assert.equal(ui.window.document.body.classList.contains('is-resizing-panels'), true); ui.global('pointerup'); assert.equal(ui.window.document.body.classList.contains('is-resizing-panels'), false); assert.ok(panels.readPreference(ui.storage)); });
check(() => { const reopened = controller({ storage: ui.storage }); assert.deepEqual(reopened.widths(), [222, 620, 352]); });
check(() => { const before = ui.storage.getItem(panels.STORAGE_KEY); ui.fire('resize-library', 'pointerdown'); ui.global('pointermove', { clientX: 850 }); ui.global('pointercancel'); assert.deepEqual(ui.widths(), [222, 620, 352]); assert.equal(ui.storage.getItem(panels.STORAGE_KEY), before); });
check(() => { ui.fire('resize-library', 'keydown', { key: 'ArrowRight' }); assert.deepEqual(ui.widths(), [234, 608, 352]); });
check(() => { ui.fire('resize-notes', 'keydown', { key: 'ArrowLeft', shiftKey: true }); assert.deepEqual(ui.widths(), [234, 568, 392]); });
check(() => { ui.fire('resize-notes', 'pointerdown'); ui.global('pointermove', { clientX: 900 }); ui.fire('resize-notes', 'keydown', { key: 'Escape' }); assert.deepEqual(ui.widths(), [234, 568, 392]); });
check(() => { ui.resize([195, 400, 380]); near(total(ui.widths()), 975); ui.widths().forEach((width, index) => assert.ok(width >= panels.minimums(975)[index] - .001)); });
check(() => { ui.media.matches = false; ui.media.changed(); ui.flush(); assert.equal(ui.workspace.style.gridTemplateColumns, ''); assert.equal(ui.workspace.dataset.panelsReady, 'false'); assert.equal(ui.nodes.get('reset-layout').hidden, true); });
check(() => { ui.media.matches = true; ui.media.changed(); ui.flush(); assert.notEqual(ui.workspace.style.gridTemplateColumns, ''); assert.equal(ui.workspace.dataset.panelsReady, 'true'); });
check(() => { ui.fire('resize-notes', 'keydown', { key: 'Home' }); assert.equal(ui.workspace.style.gridTemplateColumns, ''); assert.equal(panels.readPreference(ui.storage), null); assert.equal(ui.nodes.get('layout-announcement').textContent, '已恢复默认布局。'); });
check(() => { ui.fire('resize-notes', 'keydown', { key: 'ArrowRight' }); ui.fire('resize-notes', 'dblclick'); assert.equal(ui.workspace.style.gridTemplateColumns, ''); });
check(() => { const off = controller({ desktop: false }); assert.equal(off.workspace.dataset.panelsReady, 'false'); off.fire('resize-notes', 'keydown', { key: 'ArrowRight' }); assert.equal(off.workspace.style.gridTemplateColumns, ''); });
check(() => { const blocked = controller({ storage: denied, language: 'en' }); blocked.fire('resize-notes', 'keydown', { key: 'ArrowRight' }); blocked.fire('reset-layout', 'click'); assert.equal(blocked.nodes.get('layout-announcement').textContent, 'Default panel widths restored.'); });
console.log(`${checks} resizable-panel checks passed`);
