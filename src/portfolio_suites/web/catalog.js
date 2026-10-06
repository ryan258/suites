/* Shared operator records within the existing Toolbench. No donor runtime starts here. */
class ProjectCatalog {
  constructor() {
    this.data = null;
    this.detail = null;
    this.home = 'all';
    this.el = id => document.getElementById(id);
    this.draftPrefix = 'suites-operator-draft-v1:';
    this.storageAvailable = true;
    this.release = null;
    this.saving = false;
  }
  message(text, error = false) {
    this.el('operator-status').textContent = text;
    this.el('operator-status').classList.toggle('operator-error', error);
  }
  async request(path, body) {
    const response = await fetch(path, body ? {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
    } : {cache: 'no-store'});
    const value = await response.json();
    if (!response.ok) throw new Error(value.error || 'The local service could not complete this action.');
    return value;
  }
  readLocal(key) {
    try { return JSON.parse(localStorage.getItem(key)); }
    catch { this.storageAvailable = false; return null; }
  }
  writeLocal(key, value) {
    try { if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, JSON.stringify(value)); }
    catch { this.storageAvailable = false; this.message('Browser draft storage is unavailable. Save the record before leaving this page.', true); }
  }
  async init() {
    this.el('operator-search').addEventListener('input', () => this.renderList());
    this.el('operator-attention').addEventListener('change', () => this.renderList());
    this.el('operator-refresh').addEventListener('click', () => this.refresh());
    this.el('operator-text').addEventListener('click', () => {
      const large = !document.body.classList.contains('operator-large');
      document.body.classList.toggle('operator-large', large);
      this.el('operator-text').setAttribute('aria-pressed', String(large));
      this.writeLocal('suites-operator-large', large);
    });
    const large = this.readLocal('suites-operator-large') === true;
    document.body.classList.toggle('operator-large', large);
    this.el('operator-text').setAttribute('aria-pressed', String(large));
    document.querySelector('[data-tab="catalog"]').addEventListener('click', () => { location.hash = 'home=' + this.home; this.route(); });
    this.el('tab-catalog').addEventListener('click', event => {
      const button = event.target.closest('[data-operator-action]');
      if (!button) return;
      if (button.dataset.operatorAction === 'open') this.openTarget(button);
      if (button.dataset.operatorAction === 'copy') this.copyTarget(button);
      if (button.dataset.operatorAction === 'discard') {
        this.writeLocal(this.draftPrefix + this.detail.id, null);
        this.showDetail(this.detail.id, false);
        this.message('Draft discarded. The saved record is shown.');
      }
    });
    window.addEventListener('hashchange', () => this.route(true));
    await this.refresh();
  }
  async refresh() {
    let loaded = false;
    this.message('Reading saved project records…');
    try {
      this.data = await this.request('/api/catalog');
      loaded = true;
      window.operatorHomes = this.data.homes;
      document.querySelectorAll('select option').forEach(option => { if (this.data.homes[option.value]) option.textContent = this.data.homes[option.value]; });
      window.app?.renderSuites();
      this.renderNow(); this.renderHomes(); this.renderUnresolved(); this.route();
      this.message('Saved records loaded. Attention stays your choice. Catalog observation: ' + this.data.observed_at + '.');
    } catch (error) {
      this.message('Could not reload: ' + error.message + (this.data ? ' Previously loaded records remain visible; saving and opening need the local service.' : ' Start ./s serve and choose Reload saved records.'), true);
    }
    // Release failures must not prevent access to a saved return path.
    try {
      this.release = await this.request('/api/catalog/release');
      this.el('operator-release-summary').textContent = `${this.release.open_blocker_count} release blockers remain, independently of attention`;
      if (this.release.unmodeled_exit_phases?.length) this.el('operator-release-summary').textContent += `; additional roadmap exit gates in phases ${this.release.unmodeled_exit_phases.join(', ')}`;
      this.renderProjectRelease();
      this.el('operator-release-body').innerHTML = '<p>Release next: <code>./s next</code>. Parking or using a project does not close an obligation.</p><ul>' + this.release.open_blockers.map(b => `<li>${escapeHtml(b.name)} — ${escapeHtml(b.id)}</li>`).join('') + '</ul>';
    } catch (error) {
      this.release = null;
      this.el('operator-release-summary').textContent = 'Release state unavailable — no readiness inferred';
      this.el('operator-release-body').textContent = error.message;
      this.renderProjectRelease();
    }
    return loaded;
  }
  route(focus = false) {
    if (!this.data) return;
    const params = new URLSearchParams(location.hash.slice(1));
    const view = params.get('view');
    if (view && view !== 'catalog') { window.app?.switchTab(view); return; }
    window.app?.switchTab('catalog');
    const home = params.get('home');
    if (home && (home === 'all' || this.data.homes[home])) this.home = home;
    const id = params.get('project');
    if (id) this.showDetail(id, true, focus);
    else {
      this.detail = null; this.el('operator-detail').hidden = true; this.el('operator-browser').hidden = false;
      this.renderHomes(); this.renderList();
      if (focus) this.el('operator-search').focus();
    }
  }
  link(project) { return '#project=' + encodeURIComponent(project.id); }
  renderNow() {
    const now = this.data.projects.filter(p => p.attention === 'now').sort((a,b) => a.now_order-b.now_order);
    this.el('operator-now-count').textContent = `(${now.length}/${this.data.now_limit})`;
    this.el('operator-now').innerHTML = now.length ? '<ol>' + now.map(p => `<li><a href="${this.link(p)}">${escapeHtml(p.name)}</a><p>${escapeHtml(p.next_action || 'Next action unknown — choose one bounded step.')}</p><p>Done for now: ${escapeHtml(p.done_for_now || 'Not chosen')}</p></li>`).join('') + '</ol>' : '<p>No Now projects selected. Find a project below and choose Now when you want to work on it. Three is the ceiling, not a quota.</p>';
  }
  renderHomes() {
    this.el('operator-homes').innerHTML = Object.entries({all:'All homes', ...this.data.homes}).map(([id,label]) => {
      const count = this.data.projects.filter(p => id === 'all' || p.primary_home === id).length;
      return `<a class="operator-home" href="#home=${id}" ${this.home === id ? 'aria-current="page"' : ''}>${escapeHtml(label)} <span>(${count})</span></a>`;
    }).join('');
  }
  renderList() {
    if (!this.data) return;
    const q = this.el('operator-search').value.trim().toLowerCase();
    const attention = this.el('operator-attention').value;
    const rows = this.data.projects.filter(p => (this.home === 'all' || p.primary_home === this.home) &&
      (attention === 'all' || (p.attention || 'unassigned') === attention) &&
      [p.name, p.purpose || '', p.home_label].join(' ').toLowerCase().includes(q)).sort((a,b) => a.name.localeCompare(b.name));
    this.el('operator-results').textContent = `${rows.length} entries in ${this.data.homes[this.home] || 'all homes'}. Projects, containers, and nested repositories are identified separately.`;
    this.el('operator-projects').innerHTML = rows.length ? rows.map(p => `<article class="operator-card">
      <h3><a href="${this.link(p)}">${escapeHtml(p.name)}</a></h3><p>${escapeHtml(p.purpose || 'Purpose unknown — review needed.')}</p>
      <p class="operator-meta">${escapeHtml(p.home_label)} · ${escapeHtml(p.inventory_kind.replaceAll('_', ' '))}</p>
      <p>${escapeHtml(p.attention_label)}${p.now_order ? ' · ' + p.now_order : ''} · ${escapeHtml(p.resume_status.state)}</p>
      ${p.attention === 'waiting' ? `<p>Waiting for: ${escapeHtml(p.waiting_trigger)}</p>` : ''}
      ${p.identity_status !== 'observed' ? `<p class="operator-warning">Identity ${escapeHtml(p.identity_status)}</p>` : ''}
      <p>Next: ${escapeHtml(p.next_action || 'Unknown')}</p></article>`).join('') : '<p>No matches. Clear the search or choose All homes.</p>';
  }
  renderUnresolved() {
    this.el('operator-unresolved').innerHTML = this.data.unresolved.map(item => `<li>${escapeHtml(item.project || item.label || item.id)} — ${escapeHtml(item.reason)}</li>`).join('');
  }
  field(name, label, value) {
    return `<label for="op-${name}">${label}</label><textarea id="op-${name}" name="${name}" rows="2" maxlength="8000">${escapeHtml(value || '')}</textarea>`;
  }
  showDetail(id, restore = true, focus = false) {
    const project = this.data.projects.find(p => p.id === id);
    this.el('operator-browser').hidden = true; this.el('operator-detail').hidden = false;
    if (!project) { this.el('operator-detail').innerHTML = '<h2 id="operator-project-title">Project not found</h2><p>The saved project link is unknown.</p><a href="#home=all">Return to all homes</a>'; return; }
    this.detail = project;
    let draft = restore ? this.readLocal(this.draftPrefix + id) : null;
    if (draft && (!draft.values || !Number.isInteger(draft.revision))) draft = null;
    const p = draft ? {...project, ...draft.values} : project;
    this.formRevision = draft ? draft.revision : project.revision;
    const target = p.resume || {kind:'file', target:''};
    const options = {'unassigned':'Unassigned', now:'Now', 'in-use':'In use', waiting:'Waiting', parked:'Parked'};
    const detail = this.el('operator-detail');
    detail.innerHTML = `<a href="#home=${this.home}">← Back to projects</a><h2 id="operator-project-title" tabindex="-1">${escapeHtml(project.name)}</h2>
      <p>${escapeHtml(project.home_label)} · ${escapeHtml(project.inventory_kind.replaceAll('_',' '))} · ${escapeHtml(project.attention_label)}</p>
      <p>${escapeHtml(project.purpose || 'Purpose unknown')}</p>
      <p>Owner: ${escapeHtml(project.owner)}</p><p class="operator-path">Location: ${escapeHtml(project.location)} ${project.location_exists ? '' : '(missing)'}</p>
      <p>Related homes: ${project.related_suites.map(x => `<a href="#home=${x}">${escapeHtml(this.data.homes[x])}</a>`).join(', ') || 'None recorded'}</p>
      <div class="operator-resume"><h3>Resume</h3><p class="operator-path">${escapeHtml(project.resume?.target || 'No target recorded')}</p><p>${escapeHtml(project.resume_status.message)}</p>
      ${project.resume_status.can_open ? '<button type="button" class="btn btn-primary" data-operator-action="open">Open saved target</button>' : ''}
      ${project.resume?.kind === 'url' ? `<a class="btn btn-primary" href="${escapeHtml(project.resume.target)}" target="_blank" rel="noopener noreferrer">Open saved link (unverified)</a>` : ''}
      ${project.resume ? '<button type="button" class="btn btn-secondary" data-operator-action="copy">Copy target</button>' : ''}
      ${project.resume?.kind === 'command' ? '<p>Command is shown for deliberate use in the project terminal. Suites does not execute it.</p>' : ''}</div>
      <p id="operator-draft-status" role="status">${draft ? (draft.revision === project.revision ? 'Unsaved browser draft restored. Save when ready.' : 'Saved record changed after this draft. Copy what you need, then discard the draft and reload before saving.') : 'Saved record. Empty fields remain explicitly unknown.'}</p>
      <form id="operator-form" class="operator-form">
      <label for="op-attention">Attention</label><select name="attention" id="op-attention">${Object.entries(options).map(([key,value])=>`<option value="${key}" ${key===(p.attention || 'unassigned') ? 'selected' : ''}>${value}</option>`).join('')}</select>
      <label for="op-now_order">Now position</label><select name="now_order" id="op-now_order"><option value="">Next available position</option>${[1,2,3].map(n=>`<option value="${n}" ${p.now_order===n ? 'selected' : ''}>${n}</option>`).join('')}</select>
      ${this.field('next_action','One next action',p.next_action)}
      ${this.field('done_for_now','Done for now when…',p.done_for_now)}
      ${this.field('waiting_trigger','Waiting for (required for Waiting)',p.waiting_trigger)}
      ${this.field('restart_note','Restart note (optional)',p.restart_note)}
      <details><summary>Purpose and resume target</summary>
      ${this.field('purpose','What this project gives you',p.purpose)}
      <label for="op-kind">Resume target type</label><select id="op-kind" name="kind">${['file','directory','url','command'].map(k=>`<option value="${k}" ${target.kind===k?'selected':''}>${k}</option>`).join('')}</select>
      <label for="op-target">Saved document, folder, link, or command</label><input id="op-target" name="target" value="${escapeHtml(target.target)}" maxlength="8000">
      <label for="op-refresh-target"><input type="checkbox" name="refresh_target" id="op-refresh-target" ${draft?.values?.resume ? 'checked' : ''}> I reviewed the current target; refresh its saved observation</label>
      <p>Local targets stay inside the project. Editing the target or choosing refresh observes its current contents. Blank clears the target.</p></details>
      <div class="operator-tools"><button class="btn btn-primary" type="submit">Save return point</button><button class="btn btn-secondary" type="button" data-operator-action="discard">Discard browser draft</button></div>
      </form>
      <details><summary>Evidence, identity, and provenance</summary>
      <p>Identity: ${escapeHtml(project.identity_status)}. Catalog observation: ${escapeHtml(project.observed_at)}. Record revision: ${project.revision}.</p>
      <p>${project.migration.enrolled ? 'Retained migration disposition: '+escapeHtml(project.migration.disposition)+'.' : 'Catalog only: this placement creates no runtime migration obligation.'}</p>
      <div id="operator-project-release"></div>
      ${project.suite_evidence_error ? `<p>${escapeHtml(project.suite_evidence_error)}</p>` : ''}
      ${project.suite_evidence ? '<p>Recorded suite evidence (retained manifest claims):</p><ul>' + project.suite_evidence.wave_claims.map(w=>`<li>${escapeHtml(w.id)}: ${escapeHtml(w.level)}${w.runtime_followup ? ' · Still owes: '+escapeHtml(w.runtime_followup) : ''}</li>`).join('') + '</ul>' : ''}
      <p>Release status and evidence are available in <a href="#view=overview">Overview &amp; Metrics</a> and <a href="#view=waves">Wave Runner &amp; Gates</a>. Attention changes neither.</p>
      <ul>${project.evidence_links.map(x=>`<li>${escapeHtml(x)}</li>`).join('')}</ul>
      <ul>${project.provenance.map(x=>`<li>${escapeHtml(x.source)} — ${escapeHtml(x.observed_at)}${x.sha256 ? ' · sha256 '+escapeHtml(x.sha256) : ''}</li>`).join('')}</ul>
      ${project.notes.map(x=>`<p>${escapeHtml(x)}</p>`).join('')}</details>`;
    const form = this.el('operator-form');
    this.attentionControls();
    this.renderProjectRelease();
    form.addEventListener('input', () => { this.attentionControls(); this.saveDraft(); });
    form.addEventListener('change', () => { this.attentionControls(); this.saveDraft(); });
    form.addEventListener('submit', event => { event.preventDefault(); this.save(form); });
    this.setSaving(this.saving);
    if (focus) this.el('operator-project-title').focus();
  }
  renderProjectRelease() {
    const target = this.el('operator-project-release');
    if (!target || !this.detail) return;
    const suiteId = this.detail.migration.primary_suite;
    const suite = this.release?.suites?.[suiteId];
    target.textContent = suite ? `Suite release lifecycle: ${suite.release_phase}. ${suite.criteria_open}/${suite.criteria_total} release criteria remain open. Score: ${suite.score_status}.` : (suiteId ? 'Release state unavailable; no completion inferred.' : 'No release lifecycle is assigned to this catalog-only or independent project.');
  }
  attentionControls() {
    const state = this.el('op-attention').value;
    this.el('op-now_order').disabled = state !== 'now';
    this.el('op-waiting_trigger').required = state === 'waiting';
  }
  values() {
    const form = this.el('operator-form'); const values = Object.fromEntries(new FormData(form));
    const attention = values.attention === 'unassigned' ? null : values.attention;
    const resume = values.target.trim() ? {kind:values.kind,target:values.target.trim()} : null;
    const original = this.detail.resume;
    const changed = values.refresh_target || (resume?.kind || '') !== (original?.kind || '') || (resume?.target || '') !== (original?.target || '');
    return {
      attention, ...(attention === 'now' && values.now_order ? {now_order:Number(values.now_order)} : {}),
      purpose:values.purpose, next_action:values.next_action, done_for_now:values.done_for_now,
      waiting_trigger:values.waiting_trigger, restart_note:values.restart_note,
      ...(changed ? {resume} : {})
    };
  }
  saveDraft() {
    this.writeLocal(this.draftPrefix + this.detail.id, {revision:this.formRevision, values:this.values()});
    if (this.storageAvailable) this.el('operator-draft-status').textContent = 'Unsaved draft kept in this browser. Save return point to share it with the CLI.';
  }
  setSaving(saving) {
    this.saving = saving;
    const form = this.el('operator-form');
    if (!form) return;
    form.setAttribute('aria-busy', String(saving));
    // Disabling the focused control drops focus to <body>; remember it and put it back.
    if (saving) this.focusBeforeSave = document.activeElement?.id || null;
    form.querySelectorAll('input, select, textarea, button').forEach(control => { control.disabled = saving; });
    if (!saving) {
      this.attentionControls();
      const active = document.activeElement;
      if (this.focusBeforeSave && (!active || active === document.body)) this.el(this.focusBeforeSave)?.focus?.();
      this.focusBeforeSave = null;
    }
  }
  async save(form) {
    if (this.saving) return;
    const name = this.detail.id;
    const revision = this.formRevision;
    const changes = this.values(); // Capture before disabling controls (FormData omits them).
    this.saveDraft();
    const submittedDraft = JSON.stringify(this.readLocal(this.draftPrefix + name));
    this.setSaving(true);
    this.message('Saving return point… Editing resumes when the save finishes.');
    try {
      const updated = await this.request('/api/catalog/update', {name,revision,changes});
      // Another browser tab may have written a newer draft during this request.
      if (JSON.stringify(this.readLocal(this.draftPrefix + name)) === submittedDraft) {
        this.writeLocal(this.draftPrefix + name, null);
      }
      this.data.projects = this.data.projects.map(p => p.id === name ? updated : p);
      const loaded = await this.refresh();
      if (!loaded) {
        this.showDetail(name);
        this.message(`Saved ${updated.name}, but the full view could not reload. Reload saved records when the local service returns.`, true);
        return;
      }
      // Other Now records may have reordered; reload all of them from the shared ledger.
      this.message(`Saved ${updated.name}. Your return point is available in the CLI and after restart.`);
      this.el('operator-project-title')?.focus();
    } catch (error) { this.message('Save failed: '+error.message+' Your browser draft is retained.', true); }
    finally { this.setSaving(false); }
  }
  async openTarget(button) {
    button.disabled = true;
    try { const result = await this.request('/api/catalog/open', {name:this.detail.id,revision:this.detail.revision}); this.message(result.message); }
    catch (error) { this.message(error.message, true); }
    finally { button.disabled = false; }
  }
  async copyTarget() {
    try { await navigator.clipboard.writeText(this.detail.resume.target); this.message('Saved target copied.'); }
    catch { this.message('Clipboard unavailable. The target is shown above for selection.', true); }
  }
}
window.addEventListener('DOMContentLoaded', () => { window.projectCatalog = new ProjectCatalog(); window.projectCatalog.init(); });
