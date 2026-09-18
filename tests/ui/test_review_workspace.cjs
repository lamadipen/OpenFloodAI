const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('tools/openfloodai-review-workspace.html', 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
function context() {
  const nodes = new Map();
  const listeners = [];
  const node = id => {
    if (!nodes.has(id)) nodes.set(id, {
      open: false, value: '', innerHTML: '', textContent: '',
      classList: { toggle() {}, add() {}, remove() {} },
      showModal() { this.open = true; }, close() { this.open = false; },
      addEventListener() {}, removeAttribute() {},
    });
    return nodes.get(id);
  };
  const ctx = vm.createContext({
    document: { getElementById: node, querySelectorAll: () => [], addEventListener() {} },
    window: { addEventListener: (name, fn) => listeners.push([name, fn]) },
    location: { origin: 'http://localhost:8080', search: '' },
    URL, URLSearchParams, setTimeout: () => {}, confirm: () => false,
  });
  vm.runInContext(script.replace(/loadSites\(new URLSearchParams\(location.search\).get\('site'\)\);/, ''), ctx);
  return { ctx, node, listeners };
}
test('workspace uses existing forms in a modal and registers listeners once', () => {
  const { ctx, node, listeners } = context();
  vm.runInContext("render();render();openSite()", ctx);
  assert.equal(listeners.filter(([name]) => name === 'message').length, 1);
  assert.equal(node('siteDialog').open, true);
  assert.equal(node('siteFrame').src, '/?action=create_site&embed=workspace');
  vm.runInContext("openEmbedded('/?site=river&action=add_video','Add video')", ctx);
  assert.equal(node('siteFrame').src, '/?site=river&action=add_video&embed=workspace');
  assert.equal(node('mediaDialog').open, false);
});
test('label form is modal and cannot discard a dirty review without confirmation', () => {
  const { ctx, node } = context();
  vm.runInContext(`detail={kind:'image',config:{},points:[{key:'a',title:'Sample',machine:'no_water_level_change',has_media:false}],comparisons:[]}; selectedKey='a'; current={site_name:'river'}; runs=[{kind:'image',run_id:'run',media_id:'sequence'}];runIndex=0;openForm('label');`, ctx);
  assert.equal(node('formDialog').open, true);
  assert.match(node('formBody').innerHTML, /id="reviewForm"/);
  assert.match(node('formBody').innerHTML, /Selected image pair/);
  vm.runInContext('dirty=true;closeForm()', ctx);
  assert.equal(node('formDialog').open, true);
});
test('invalid capture times show a clear chart empty state', () => {
  const { ctx } = context();
  assert.match(vm.runInContext("detail={kind:'image'};chart([{score:0.5,time:'invalid'}])", ctx), /valid times/);
});
