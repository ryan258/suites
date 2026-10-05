'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const web = path.join(__dirname, '..', 'src', 'portfolio_suites', 'web');
const nodes = new Map();
const context = vm.createContext({
  window: {addEventListener() {}},
  document: {getElementById: id => nodes.get(id)},
  console,
});
vm.runInContext(fs.readFileSync(path.join(web, 'app.js'), 'utf8') + '\nglobalThis.SuitesAppClass = SuitesApp;', context);
vm.runInContext(fs.readFileSync(path.join(web, 'catalog.js'), 'utf8') + '\nglobalThis.CatalogClass = ProjectCatalog;', context);

async function deferredSave({fail = false, otherTab = false, reload = true} = {}) {
  const catalog = new context.CatalogClass();
  const controls = Array.from({length: 4}, () => ({disabled: false}));
  const form = {setAttribute() {}, querySelectorAll: () => controls};
  const fallback = {textContent: '', focus() {}};
  catalog.el = id => id === 'operator-form' ? form : fallback;
  catalog.attentionControls = () => {};
  catalog.message = () => {};
  catalog.detail = {id: 'alpha', revision: 0};
  catalog.formRevision = 0;
  catalog.data = {projects: [catalog.detail]};
  const storage = new Map();
  catalog.readLocal = key => storage.get(key) ?? null;
  catalog.writeLocal = (key, value) => value === null ? storage.delete(key) : storage.set(key, value);
  catalog.values = () => ({next_action: 'Submitted wording'});
  let release, reject, sent;
  catalog.request = (_url, body) => {sent = body; return new Promise((resolve, refuse) => {release = resolve; reject = refuse;});};
  catalog.refresh = async () => reload;
  let restoredDraft = false;
  catalog.showDetail = (_name, restore = true) => {restoredDraft = restore;};
  const pending = catalog.save(form);
  assert.equal(catalog.saving, true);
  assert(controls.every(control => control.disabled), 'All editable controls must pause during the request.');
  assert.equal(sent.changes.next_action, 'Submitted wording', 'Capture fields before disabling FormData controls.');
  const key = catalog.draftPrefix + 'alpha';
  if (otherTab) storage.set(key, {revision: 0, values: {next_action: 'New draft from another tab'}});
  if (fail) reject(new Error('Service unavailable'));
  else release({id: 'alpha', name: 'alpha', revision: 1});
  await pending;
  assert.equal(catalog.saving, false);
  assert(controls.every(control => !control.disabled), 'Editing must resume after success or failure.');
  if (otherTab) assert.equal(storage.get(key).values.next_action, 'New draft from another tab');
  else if (fail) assert.equal(storage.get(key).values.next_action, 'Submitted wording');
  else assert.equal(storage.has(key), false);
  if (!fail && !reload) assert.equal(restoredDraft, true, 'Reload failure must not discard a preserved draft.');
}

function releaseCard() {
  for (const id of ['next-move-card', 'next-move-target', 'next-move-level', 'next-move-owes', 'next-move-command']) {
    nodes.set(id, {textContent: '', className: ''});
  }
  const app = Object.create(context.SuitesAppClass.prototype);
  const gate = {id: 'phase0.release-ledger', phase: '0', name: 'Close the ledger gate'};
  app.state = {
    waves: [{suite_id: 'brand-publishing', wave_id: 'B3', status: 'complete', claim_level: 'prototype', runtime_followup: 'Old ranking must not win'}],
    release: {actionable_blockers: [gate], open_blockers: [gate], open_blocker_count: 1},
  };
  app.renderNextMove();
  assert.equal(nodes.get('next-move-target').textContent, gate.id);
  assert.equal(nodes.get('next-move-command').textContent, './s next');
  app.state.release.actionable_blockers = [];
  app.renderNextMove();
  assert.match(nodes.get('next-move-target').textContent, /held by dependency/);
  app.state.release = {error: 'Invalid release evidence'};
  app.renderNextMove();
  assert.equal(nodes.get('next-move-target').textContent, 'Release state unavailable');
  assert.equal(nodes.get('next-move-owes').textContent, 'Invalid release evidence');
  app.state.release = {actionable_blockers: [], open_blockers: [], open_blocker_count: 0};
  app.renderNextMove();
  assert.match(nodes.get('next-move-owes').textContent, /does not establish release readiness/);
}

async function releaseFetchFailure() {
  const app = Object.create(context.SuitesAppClass.prototype);
  app.state = {drift: [], release: {actionable_blockers: [{id: 'stale-gate'}]}};
  app.announce = () => {};
  let releaseRead = false;
  app.fetchJSON = async url => {
    if (url === '/api/catalog/release') {releaseRead = true; throw new Error('Release read failed');}
    return url === '/api/summary' ? {} : [];
  };
  for (const method of ['renderHeaderMetrics', 'renderOverview', 'renderSuites', 'renderProjectsTable',
    'renderDriftTable', 'renderNestedTable', 'renderWaves', 'renderAIStatus']) app[method] = () => {};
  await app.refreshData();
  assert(releaseRead);
  assert.equal(app.state.release.error, 'Release read failed');
}

(async () => {
  await deferredSave();
  await deferredSave({fail: true});
  await deferredSave({otherTab: true});
  await deferredSave({otherTab: true, reload: false});
  releaseCard();
  await releaseFetchFailure();
})().catch(error => { console.error(error); process.exitCode = 1; });
