/**
 * RYAN PROJECT SUITES — CLIENT CONTROLLER
 */

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function redactSensitiveArguments(value, sensitiveKeyPattern, redactedValue) {
  if (!(sensitiveKeyPattern instanceof RegExp) || typeof redactedValue !== 'string' || !redactedValue) {
    throw new Error('Toolbench argument-redaction policy is unavailable');
  }
  if (Array.isArray(value)) {
    return value.map(child => redactSensitiveArguments(child, sensitiveKeyPattern, redactedValue));
  }
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([key, child]) => [
      key,
      sensitiveKeyPattern.test(key)
        ? redactedValue
        : redactSensitiveArguments(child, sensitiveKeyPattern, redactedValue)
    ]));
  }
  return value;
}

function referencedStepIndexes(value, found = new Set()) {
  if (value && typeof value === 'object') {
    if (!Array.isArray(value) && Object.prototype.hasOwnProperty.call(value, '$from')) {
      found.add(value.$from);
      return found;
    }
    Object.values(value).forEach(item => referencedStepIndexes(item, found));
  }
  return found;
}

function containsRedactedArgument(value, redactedValue) {
  if (typeof redactedValue !== 'string' || !redactedValue) {
    throw new Error('Toolbench argument-redaction policy is unavailable');
  }
  if (value === redactedValue) return true;
  if (Array.isArray(value)) {
    return value.some(child => containsRedactedArgument(child, redactedValue));
  }
  return Boolean(
    value
    && typeof value === 'object'
    && Object.values(value).some(child => containsRedactedArgument(child, redactedValue))
  );
}

function collectChainDependencies(argumentsValue, tray) {
  const required = new Set();
  const visiting = new Set();
  const visit = index => {
    if (!Number.isInteger(index) || index < 0 || index >= tray.length) {
      throw new Error(`$from must name an existing tray step; got ${String(index)}`);
    }
    if (visiting.has(index)) throw new Error(`tray dependency cycle reaches step ${index}`);
    if (required.has(index)) return;
    visiting.add(index);
    referencedStepIndexes(tray[index].args).forEach(visit);
    visiting.delete(index);
    required.add(index);
  };
  referencedStepIndexes(argumentsValue).forEach(visit);
  return [...required].sort((left, right) => left - right);
}

function rebaseChainReferences(value, indexMap) {
  if (Array.isArray(value)) return value.map(item => rebaseChainReferences(item, indexMap));
  if (value && typeof value === 'object') {
    if (Object.prototype.hasOwnProperty.call(value, '$from')) {
      if (!indexMap.has(value.$from)) throw new Error(`chain is missing tray dependency ${String(value.$from)}`);
      return {
        ...Object.fromEntries(
          Object.entries(value)
            .filter(([key]) => key !== '$from')
            .map(([key, child]) => [key, rebaseChainReferences(child, indexMap)])
        ),
        $from: indexMap.get(value.$from)
      };
    }
    return Object.fromEntries(
      Object.entries(value).map(([key, child]) => [key, rebaseChainReferences(child, indexMap)])
    );
  }
  return value;
}

class SuitesApp {
  constructor() {
    this.state = {
      summary: null,
      suites: [],
      projects: [],
      nested: [],
      drift: [],
      contracts: {},
      selectedContract: 'A11yFinding',
      waves: [],
      aiStatus: null
    };
    this.modalLastFocus = null;
    this.waveRunActive = false;

    this.init();
  }

  async init() {
    this.bindEvents();
    await this.refreshData();
    this.selectContract('A11yFinding');
    this.updateAIModel();
  }

  bindEvents() {
    // Manifest-derived identifiers live in data attributes, never executable inline handlers.
    document.addEventListener('click', (event) => {
      if (!(event.target instanceof Element)) return;
      const trigger = event.target.closest('[data-app-action]');
      if (!trigger) return;
      const action = trigger.dataset.appAction;
      if (action === 'inspect-suite') this.inspectSuite(trigger.dataset.suiteId);
      if (action === 'run-wave') this.runSingleWave(trigger.dataset.suiteId, trigger.dataset.waveId);
      if (action === 'view-evidence') this.viewEvidence(trigger.dataset.evidence);
      if (action === 'view-doc') this.viewDocument(trigger.dataset.docId);
      if (action === 'switch-tab') this.switchTab(trigger.dataset.tab);
    });

    // Navigation tabs
    document.querySelectorAll('.nav-item').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const tab = e.currentTarget.dataset.tab;
        this.switchTab(tab);
      });
    });

    // Refresh button
    document.getElementById('btn-refresh').addEventListener('click', () => this.refreshData());

    // Run all waves buttons
    document.getElementById('btn-run-all-waves').addEventListener('click', () => this.runAllWaves());
    const tabRunAll = document.getElementById('btn-run-all-waves-tab');
    if (tabRunAll) tabRunAll.addEventListener('click', () => this.runAllWaves());

    // Search and filter in projects tab
    const searchInput = document.getElementById('project-search-input');
    const suiteFilter = document.getElementById('project-suite-filter');
    const dispFilter = document.getElementById('project-disposition-filter');

    if (searchInput) searchInput.addEventListener('input', () => this.renderProjectsTable());
    if (suiteFilter) suiteFilter.addEventListener('change', () => this.renderProjectsTable());
    if (dispFilter) dispFilter.addEventListener('change', () => this.renderProjectsTable());

    // Contract tab buttons
    document.querySelectorAll('#contract-btn-group .btn-tab').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const contract = e.currentTarget.dataset.contract;
        this.selectContract(contract);
      });
    });

    // Contract actions
    document.getElementById('btn-load-sample').addEventListener('click', () => this.loadContractSample());
    document.getElementById('btn-validate-contract').addEventListener('click', () => this.validateCurrentContract());

    // Rescan drift
    document.getElementById('btn-rescan-drift').addEventListener('click', () => this.fetchDrift());

    // Modal close
    document.getElementById('btn-close-modal').addEventListener('click', () => this.closeEvidenceModal());
    document.getElementById('evidence-modal').addEventListener('click', event => {
      if (event.target.id === 'evidence-modal') this.closeEvidenceModal();
    });
    document.addEventListener('keydown', event => this.handleModalKeydown(event));

    // OpenRouter assistant. The browser never receives the credential; it only gets public
    // status and sends operator-authored prompt/context text to the loopback API.
    document.getElementById('ai-role').addEventListener('change', () => this.updateAIModel());
    document.getElementById('btn-ai-run').addEventListener('click', () => this.runAI());
    document.getElementById('btn-ai-clear').addEventListener('click', () => this.clearAI());
  }

  announce(message, { error = false } = {}) {
    const status = document.getElementById('app-status');
    if (!status) return;
    status.textContent = message;
    status.classList.toggle('result-error', error);
  }

  async fetchJSON(url, options = undefined) {
    const response = await fetch(url, options);
    let body;
    try {
      body = await response.json();
    } catch {
      throw new Error(`${url} returned a non-JSON response (${response.status})`);
    }
    if (!response.ok) {
      const detail = body?.error?.message || body?.error || body?.message || `HTTP ${response.status}`;
      const error = new Error(String(detail));
      error.status = response.status;
      error.body = body;
      throw error;
    }
    return body;
  }

  switchTab(tabId) {
    const target = document.getElementById(`tab-${tabId}`);
    if (!target) return;
    document.querySelectorAll('.nav-item').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.tab === tabId);
      btn.setAttribute('aria-current', btn.dataset.tab === tabId ? 'page' : 'false');
    });
    document.querySelectorAll('.tab-pane').forEach(pane => {
      pane.classList.toggle('active', pane.id === `tab-${tabId}`);
      pane.setAttribute('aria-hidden', pane.id === `tab-${tabId}` ? 'false' : 'true');
    });
    const heading = target.querySelector('h1');
    if (heading) {
      heading.setAttribute('tabindex', '-1');
      heading.focus({ preventScroll: true });
    }
  }

  async refreshData() {
    this.announce('Refreshing local suite manifests, evidence, projects, and drift…');
    try {
      const [sumRes, suitesRes, projRes, nestedRes, driftRes, contractsRes, valRes, wavesRes, aiRes] = await Promise.all([
        this.fetchJSON('/api/summary'),
        this.fetchJSON('/api/suites'),
        this.fetchJSON('/api/projects'),
        this.fetchJSON('/api/nested'),
        this.fetchJSON('/api/drift'),
        this.fetchJSON('/api/contracts'),
        this.fetchJSON('/api/validate'),
        this.fetchJSON('/api/waves'),
        this.fetchJSON('/api/ai/status').catch(error => ({
          provider: 'openrouter', configured: false, free_only: true, roles: {}, warnings: [error.message]
        }))
      ]);

      this.state.summary = sumRes;
      this.state.suites = suitesRes;
      this.state.projects = projRes;
      this.state.nested = nestedRes;
      this.state.drift = driftRes;
      this.state.contracts = contractsRes;
      this.state.waves = wavesRes;
      this.state.aiStatus = aiRes;

      this.renderHeaderMetrics(valRes);
      this.renderOverview();
      this.renderSuites();
      this.renderProjectsTable();
      this.renderDriftTable();
      this.renderNestedTable();
      this.renderWaves();
      this.renderAIStatus();
      this.announce(
        `Ready: ${sumRes.validated_completed_claims}/${sumRes.total_waves} retained claims validate; ` +
        `${sumRes.recovered_runtime_behaviors} runtime recovery; ${sumRes.waves_owing_runtime_followup} follow-ups remain.`
      );
    } catch (err) {
      console.error('Failed to load portfolio data:', err);
      this.announce(`Refresh failed: ${err.message}`, { error: true });
    }
  }

  renderHeaderMetrics(valRes) {
    document.getElementById('stat-projects').textContent = this.state.projects.length;
    document.getElementById('stat-suites').textContent = this.state.suites.length;
    document.getElementById('nav-project-count').textContent = this.state.projects.length;
    document.getElementById('project-heading-count').textContent = this.state.projects.length;
    document.getElementById('nav-nested-count').textContent = this.state.nested.length;
    document.getElementById('nested-heading-count').textContent = this.state.nested.length;
    
    const sum = this.state.summary;
    if (sum) {
      document.getElementById('stat-waves').textContent = `${sum.completed_waves}/${sum.total_waves}`;
      document.getElementById('card-progress-pct').textContent = `${sum.validated_completed_claims}/${sum.total_waves}`;
      document.getElementById('card-progress-bar').style.width = `${sum.evidence_health_pct || 0}%`;
      document.getElementById('card-total-projects').textContent = sum.total_projects;
      document.getElementById('card-suite-projects').textContent = sum.total_projects - sum.independent_projects;
      document.getElementById('card-ind-projects').textContent = sum.independent_projects;
      document.getElementById('snapshot-timestamp').textContent = `Snapshot: ${sum.snapshot_at || 'Live'}`;
      // Scheduling progress alone reads as done. A completed analysis wave still owes the
      // live run it deferred, so the tile never shows a bare 100%.
      const debtEl = document.getElementById('card-runtime-debt');
      if (debtEl) {
        const owing = sum.waves_owing_runtime_followup || 0;
        debtEl.textContent = owing
          ? `${sum.recovered_runtime_behaviors} runtime recovery · ${owing} live follow-up(s) remain`
          : `${sum.recovered_runtime_behaviors} runtime recoveries · no live follow-up outstanding`;
        debtEl.className = owing ? 'subtext subtext-warn' : 'subtext';
      }
    }

    const healthBadge = document.getElementById('stat-health');
    if (valRes && valRes.ok) {
      healthBadge.textContent = 'HEALTHY';
      healthBadge.className = 'pill-badge badge-green';
    } else {
      healthBadge.textContent = 'DRIFT / WARN';
      healthBadge.className = 'pill-badge badge-yellow';
    }
  }

  renderOverview() {
    const container = document.getElementById('suites-overview-grid');
    if (!container) return;

    container.innerHTML = this.state.suites.map(s => {
      const completedWaves = (s.waves || []).filter(w => w.status === 'complete').length;
      const totalWaves = (s.waves || []).length;
      const pct = totalWaves ? Math.round((completedWaves / totalWaves) * 100) : 100;
      const currentWave = (s.waves || []).find(w => w.status !== 'complete');
      // Every wave complete is not a finished suite: analysis-only waves still owe runtime work.
      const openFollowups = (s.waves || []).filter(w => w.status === 'complete' && w.runtime_followup).length;
      const doneLabel = openFollowups
        ? `analysis complete, ${openFollowups} runtime follow-up(s) pending`
        : 'adoption pending';

      return `
        <div class="suite-card">
          <div class="suite-card-top">
            <div class="suite-card-header">
              <span class="suite-name">${escapeHtml(s.name)}</span>
              <span class="pill-badge badge-blue">${escapeHtml(s.state)}</span>
            </div>
            <div class="suite-promise">${escapeHtml(s.promise)}</div>
            <div class="suite-tags">
              ${(s.contracts || []).map(c => `<span class="suite-tag">⚖ ${escapeHtml(c)}</span>`).join('')}
              ${(s.anchors || []).map(a => `<span class="suite-tag">⚓ ${escapeHtml(a)}</span>`).join('')}
            </div>
          </div>
          <div class="suite-card-bottom">
            <span class="subtext">Next: <strong>${escapeHtml(currentWave ? currentWave.id : doneLabel)}</strong> (${escapeHtml(completedWaves)}/${escapeHtml(totalWaves)} waves)</span>
            <button class="btn btn-sm btn-secondary" data-app-action="inspect-suite" data-suite-id="${escapeHtml(s.id)}">Inspect</button>
          </div>
        </div>
      `;
    }).join('');
  }

  renderSuites() {
    const container = document.getElementById('suite-detail-cards');
    if (!container) return;

    container.innerHTML = this.state.suites.map(s => {
      return `
        <div class="card" style="margin-bottom: 24px;" id="suite-card-${escapeHtml(s.id)}">
          <div class="card-header-row">
            <div>
              <h2 style="font-size: 18px; font-weight: 700;">${escapeHtml(s.name)} <span style="font-size: 12px; color: var(--text-dim); font-family: var(--font-mono);">(${escapeHtml(s.id)})</span></h2>
              <p style="color: var(--text-muted); font-size: 13px; margin-top: 4px;">${escapeHtml(s.promise)}</p>
            </div>
            <span class="pill-badge badge-purple">${escapeHtml(s.state)}</span>
          </div>

          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin: 16px 0;">
            <div>
              <h4 style="font-size: 12px; color: var(--text-dim); text-transform: uppercase; margin-bottom: 6px;">Anchors & Members</h4>
              <div style="font-size: 13px;">
                <strong>Anchors:</strong> ${(s.anchors || []).map(a => `<span class="suite-tag">⚓ ${escapeHtml(a)}</span>`).join(' ')}<br>
                <div style="margin-top: 8px;">
                  ${(s.members || []).map(m => `<div>&bull; <span class="mono-cell">${escapeHtml(m.project)}</span> <span style="color: var(--text-dim);">(${escapeHtml(m.relationship)})</span></div>`).join('')}
                </div>
              </div>
            </div>

            <div>
              <h4 style="font-size: 12px; color: var(--text-dim); text-transform: uppercase; margin-bottom: 6px;">Completion Criteria</h4>
              <ul style="font-size: 12px; color: var(--text-muted); padding-left: 16px;">
                ${(s.completion_criteria || []).map(c => `<li>${escapeHtml(c)}</li>`).join('')}
              </ul>
            </div>
          </div>

          <h4 style="font-size: 12px; color: var(--text-dim); text-transform: uppercase; margin-bottom: 8px;">Migration Waves</h4>
          <div class="waves-grid">
            ${(s.waves || []).map(w => `
              <div class="wave-card">
                <div class="wave-card-header">
                  <span class="wave-id-badge">${escapeHtml(s.id)} / ${escapeHtml(w.id)}</span>
                  <span class="pill-badge ${w.status === 'complete' ? 'badge-green' : 'badge-yellow'}">${escapeHtml(w.status)}</span>
                </div>
                <div class="wave-objective">${escapeHtml(w.objective)}</div>
                <div class="wave-acceptance">${escapeHtml(w.acceptance)}</div>
                <div class="wave-actions">
                  <button class="btn btn-sm btn-primary" data-app-action="run-wave" data-suite-id="${escapeHtml(s.id)}" data-wave-id="${escapeHtml(w.id)}">Run Wave Gate</button>
                  ${w.evidence ? `<button class="btn btn-sm btn-secondary" data-app-action="view-evidence" data-evidence="${escapeHtml(w.evidence)}">View Evidence</button>` : ''}
                </div>
              </div>
            `).join('')}
          </div>
        </div>
      `;
    }).join('');
  }

  renderProjectsTable() {
    const tbody = document.getElementById('projects-tbody');
    if (!tbody) return;

    const search = (document.getElementById('project-search-input')?.value || '').toLowerCase();
    const suiteFilter = document.getElementById('project-suite-filter')?.value || 'all';
    const dispFilter = document.getElementById('project-disposition-filter')?.value || 'all';

    const filtered = this.state.projects.filter(p => {
      const matchSearch = p.name.toLowerCase().includes(search) || 
                          (p.primary_suite || '').toLowerCase().includes(search) || 
                          (p.disposition || '').toLowerCase().includes(search);
      
      const matchSuite = suiteFilter === 'all' ? true :
                         suiteFilter === 'none' ? !p.primary_suite :
                         p.primary_suite === suiteFilter;

      const matchDisp = dispFilter === 'all' ? true :
                        (p.disposition || '').toLowerCase().includes(dispFilter);

      return matchSearch && matchSuite && matchDisp;
    });

    tbody.innerHTML = filtered.map(p => {
      const snap = p.source_snapshot || {};
      return `
        <tr>
          <td><strong class="mono-cell">${escapeHtml(p.name)}</strong></td>
          <td>${p.primary_suite ? `<span class="suite-tag">${escapeHtml(p.primary_suite)}</span>` : '<span style="color: var(--text-dim);">-</span>'}</td>
          <td><span class="pill-badge badge-blue">${escapeHtml(p.disposition)}</span></td>
          <td><span class="mono-cell">${escapeHtml(p.migration || '-')}</span></td>
          <td class="mono-cell">${snap.git ? `${escapeHtml(snap.branch)}@${escapeHtml(snap.head)}` : '<span style="color: var(--text-dim);">no git</span>'}</td>
          <td><span class="mono-cell">${snap.status_lines !== undefined ? `${escapeHtml(snap.status_lines)} dirty item(s)` : '-'}</span></td>
        </tr>
      `;
    }).join('');
  }

  renderDriftTable() {
    const tbody = document.getElementById('drift-tbody');
    const summaryBar = document.getElementById('drift-summary-bar');
    if (!tbody) return;

    const driftCount = this.state.drift.filter(d => d.has_drift).length;
    if (summaryBar) {
      summaryBar.innerHTML = `<div style="margin-bottom: 12px; font-size: 13px; color: var(--text-muted);">
        <strong>${escapeHtml(driftCount)}</strong> out of <strong>${escapeHtml(this.state.drift.length)}</strong> monitored repositories have working tree changes or branch/HEAD drift from recorded baseline.
      </div>`;
    }

    tbody.innerHTML = this.state.drift.map(d => {
      return `
        <tr>
          <td><strong class="mono-cell">${escapeHtml(d.name)}</strong></td>
          <td>${d.primary_suite ? `<span class="suite-tag">${escapeHtml(d.primary_suite)}</span>` : '-'}</td>
          <td class="mono-cell">${escapeHtml(d.snapshot_branch)}@${escapeHtml(d.snapshot_head)} (${escapeHtml(d.snapshot_lines)} files)</td>
          <td class="mono-cell">${escapeHtml(d.current_branch)}@${escapeHtml(d.current_head)} (${escapeHtml(d.current_lines)} files)</td>
          <td><span class="mono-cell">${escapeHtml(d.current_lines)} changed line(s)</span></td>
          <td>
            <span class="pill-badge ${d.has_drift ? 'badge-yellow' : 'badge-green'}">
              ${d.has_drift ? 'DRIFT DETECTED' : 'IN SYNC'}
            </span>
          </td>
        </tr>
      `;
    }).join('');
  }

  renderNestedTable() {
    const tbody = document.getElementById('nested-tbody');
    if (!tbody) return;

    tbody.innerHTML = this.state.nested.map(n => {
      return `
        <tr>
          <td class="mono-cell"><strong>${escapeHtml(n.path)}</strong></td>
          <td><span class="mono-cell">${escapeHtml(n.path.split('/')[0])}</span></td>
          <td><span class="pill-badge badge-purple">${escapeHtml(n.kind)}</span></td>
          <td class="mono-cell" style="font-size: 11px; color: var(--text-muted);">${escapeHtml(n.disposition || 'local')}</td>
        </tr>
      `;
    }).join('');
  }

  renderWaves() {
    const container = document.getElementById('waves-container');
    if (!container) return;

    const suiteNames = new Map(this.state.suites.map(suite => [suite.id, suite.name]));
    container.innerHTML = this.state.waves.map(wave => {
      const verified = wave.passed && wave.evidence_valid;
      const statusClass = verified ? 'badge-green' : wave.manifest_complete ? 'badge-red' : 'badge-yellow';
      const statusLabel = verified ? 'RETAINED EVIDENCE VALID' : wave.manifest_complete ? 'EVIDENCE INVALID' : 'SPECIFIED';
      const claim = [wave.claim_kind, wave.claim_level].filter(Boolean).join(' / ');
      return `
      <div class="wave-card" id="wave-card-${escapeHtml(wave.suite_id)}-${escapeHtml(wave.wave_id)}">
        <div class="wave-card-header">
          <span class="wave-id-badge">${escapeHtml(suiteNames.get(wave.suite_id) || wave.suite_id)} &bull; ${escapeHtml(wave.wave_id)}</span>
          <span class="pill-badge ${statusClass}">${statusLabel}</span>
        </div>
        <div class="wave-objective">${escapeHtml(wave.objective)}</div>
        <div class="wave-acceptance">${escapeHtml(wave.acceptance)}</div>
        <div class="suite-tags">
          <span class="suite-tag">${escapeHtml(wave.execution_kind)}</span>
          ${claim ? `<span class="suite-tag">${escapeHtml(claim)}</span>` : ''}
          <span class="suite-tag">${escapeHtml(wave.verification_depth)}</span>
        </div>
        <div class="wave-actions">
          <button type="button" class="btn btn-sm btn-primary" data-app-action="run-wave" data-suite-id="${escapeHtml(wave.suite_id)}" data-wave-id="${escapeHtml(wave.wave_id)}">Run Check</button>
          ${wave.evidence_path ? `<button type="button" class="btn btn-sm btn-secondary" data-app-action="view-evidence" data-evidence="${escapeHtml(wave.evidence_path)}">Retained Evidence</button>` : ''}
        </div>
      </div>
    `;
    }).join('');
  }

  renderAIStatus() {
    const status = this.state.aiStatus || {};
    const badge = document.getElementById('ai-provider-status');
    const runButton = document.getElementById('btn-ai-run');
    if (status.configured && status.free_only) {
      badge.textContent = 'CONFIGURED · FREE ONLY';
      badge.className = 'pill-badge badge-green';
    } else if (status.configured) {
      badge.textContent = 'CONFIGURED · PAID ROUTES ALLOWED';
      badge.className = 'pill-badge badge-red';
    } else {
      badge.textContent = 'NOT CONFIGURED';
      badge.className = 'pill-badge badge-yellow';
    }
    runButton.disabled = !status.configured;
    const boundary = document.getElementById('ai-evidence-boundary');
    if (status.evidence_boundary) boundary.textContent = status.evidence_boundary;
    this.updateAIModel();
  }

  updateAIModel() {
    const role = document.getElementById('ai-role')?.value || 'orchestrator';
    const status = this.state.aiStatus || {};
    const policy = status.roles?.[role];
    const model = policy?.model || status.default_free_router || 'openrouter/free';
    document.getElementById('ai-model').textContent = model;
    document.getElementById('ai-policy').textContent = status.free_only === false
      ? 'Paid routes are explicitly enabled · credential stays server-side'
      : 'Free-only policy · credential stays server-side';
  }

  clearAI() {
    document.getElementById('ai-prompt').value = '';
    document.getElementById('ai-context').value = '';
    document.getElementById('ai-answer').innerHTML = '<p class="result-placeholder">Provider-assisted output will appear here.</p>';
    document.getElementById('ai-answer-meta').textContent = '';
    document.getElementById('ai-request-status').innerHTML = '<span class="result-placeholder">Choose a suite and role, then ask a question.</span>';
    document.getElementById('ai-prompt').focus();
  }

  async runAI() {
    const prompt = document.getElementById('ai-prompt').value.trim();
    const context = document.getElementById('ai-context').value.trim();
    const suiteId = document.getElementById('ai-suite').value;
    const role = document.getElementById('ai-role').value;
    const statusBox = document.getElementById('ai-request-status');
    const answer = document.getElementById('ai-answer');
    const meta = document.getElementById('ai-answer-meta');
    const button = document.getElementById('btn-ai-run');
    if (!prompt) {
      statusBox.innerHTML = '<span class="result-error">Enter a prompt before requesting assistance.</span>';
      document.getElementById('ai-prompt').focus();
      return;
    }
    button.disabled = true;
    button.textContent = 'Asking…';
    statusBox.innerHTML = '<span class="pill-badge badge-blue">OPENROUTER</span> Requesting provider-assisted output…';
    answer.textContent = '';
    meta.textContent = '';
    try {
      const payload = { prompt, suite_id: suiteId, role };
      if (context) payload.context = context;
      const result = await this.fetchJSON('/api/ai/assist', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      answer.textContent = result.content;
      meta.textContent = [
        `${result.provider} / ${result.resolved_model}`,
        `suite=${result.suite_id}`,
        `role=${result.role}`,
        result.free_only ? 'free-only route' : 'paid routes allowed',
        'model-assisted',
        'human review required'
      ].join(' · ');
      statusBox.innerHTML = '<span class="result-success">Response received. Review it before use; it is not deterministic evidence.</span>';
      answer.focus();
      this.announce(`OpenRouter returned model-assisted ${role} guidance for ${suiteId}; human review is required.`);
    } catch (error) {
      const code = error.body?.error?.code ? `${error.body.error.code}: ` : '';
      statusBox.innerHTML = `<span class="result-error">${escapeHtml(code + error.message)}</span>`;
      answer.innerHTML = '<p class="result-placeholder">No provider output was accepted.</p>';
      this.announce(`AI request failed: ${code}${error.message}`, { error: true });
    } finally {
      button.disabled = !(this.state.aiStatus?.configured);
      button.textContent = 'Ask free AI';
    }
  }

  async selectContract(contractName) {
    this.state.selectedContract = contractName;
    document.querySelectorAll('#contract-btn-group .btn-tab').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.contract === contractName);
    });

    const spec = this.state.contracts[contractName];
    const specBox = document.getElementById('contract-spec-display');
    if (specBox && spec) {
      specBox.innerHTML = `
        <div style="font-weight: 600; color: var(--text-main); margin-bottom: 4px;">${escapeHtml(spec.name)}</div>
        <div style="color: var(--text-muted); margin-bottom: 8px;">${escapeHtml(spec.description)}</div>
        <div style="margin-bottom: 4px;"><strong>Required fields:</strong> <code>${escapeHtml(spec.required.join(', '))}</code></div>
        ${Object.keys(spec.enums || {}).length ? `<div><strong>Enums:</strong> ${Object.entries(spec.enums).map(([k, v]) => `<code>${escapeHtml(k)}: [${escapeHtml(v.join(', '))}]</code>`).join(' ')}</div>` : ''}
      `;
    }

    await this.loadContractSample();
  }

  async loadContractSample() {
    const cName = this.state.selectedContract;
    try {
      const res = await fetch(`/api/contracts/${cName}/sample`).then(r => r.json());
      const editor = document.getElementById('contract-json-editor');
      if (editor) {
        editor.value = JSON.stringify(res, null, 2);
      }
      const resBox = document.getElementById('contract-validation-result');
      if (resBox) {
        resBox.innerHTML = `<span class="result-success">✓ Loaded standard valid sample for ${escapeHtml(cName)}.</span>`;
      }
    } catch (err) {
      console.error(err);
    }
  }

  async validateCurrentContract() {
    const cName = this.state.selectedContract;
    const editor = document.getElementById('contract-json-editor');
    const resBox = document.getElementById('contract-validation-result');
    if (!editor || !resBox) return;

    let payload;
    try {
      payload = JSON.parse(editor.value);
    } catch (err) {
      resBox.innerHTML = `<span class="result-error">JSON Syntax Error: ${escapeHtml(err.message)}</span>`;
      return;
    }

    try {
      const res = await fetch(`/api/contracts/${cName}/validate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (res.ok && data.ok) {
        resBox.innerHTML = `<span class="result-success">✓ VALID ${escapeHtml(cName)} payload (Schema version 1.0.0 passed).</span>`;
      } else {
        resBox.innerHTML = `<span class="result-error">✗ Contract Error: ${escapeHtml(data.error)}</span>`;
      }
    } catch (err) {
      resBox.innerHTML = `<span class="result-error">Server Error: ${escapeHtml(err.message)}</span>`;
    }
  }

  async runSingleWave(suiteId, waveId) {
    const statusBox = document.getElementById('wave-run-status');
    statusBox.innerHTML = `<span class="pill-badge badge-blue">RUNNING</span> ${escapeHtml(suiteId)}/${escapeHtml(waveId)} (ephemeral; retained evidence unchanged)`;
    try {
      const res = await this.fetchJSON(`/api/waves/${encodeURIComponent(suiteId)}/${encodeURIComponent(waveId)}/run`, { method: 'POST' });
      const resultLabel = res.execution_kind === 'verified_runtime_recovery' && res.passed
        ? 'VERIFIED RUNTIME RECOVERY'
        : res.execution_kind === 'verified_source_execution' && res.passed
          ? 'VERIFIED SOURCE EXECUTION'
        : res.execution_kind === 'verified_adoption' && res.passed
          ? 'VERIFIED ADOPTION'
        : res.execution_kind === 'verified_convergence' && res.passed
          ? 'VERIFIED CONVERGENCE'
        : res.execution_kind === 'verified_resolution' && res.passed
          ? 'VERIFIED RESOLUTION'
        : res.execution_kind === 'verified_analysis' && res.passed
          ? 'VERIFIED ANALYSIS'
        : res.execution_kind === 'prototype_check' && res.prototype_passed
          ? 'PROTOTYPE CHECK PASSED'
          : res.execution_kind === 'unverifiable_environment'
            ? 'UNVERIFIABLE IN THIS ENVIRONMENT'
          : res.execution_kind === 'unintegrated_specification'
            ? 'SPECIFIED / NOT INTEGRATED'
            : 'FAILED';
      const resultClass = res.passed || res.prototype_passed
        ? 'result-success'
        : res.execution_kind === 'unverifiable_environment'
          ? 'result-warn'
          : 'result-error';
      statusBox.innerHTML = `<span class="${resultClass}">${escapeHtml(resultLabel)} · ${escapeHtml(suiteId)}/${escapeHtml(waveId)} · ${escapeHtml(res.message)}</span>`;
      this.announce(`${suiteId}/${waveId}: ${resultLabel}. Retained evidence was not changed.`);
      await this.refreshData();
    } catch (err) {
      statusBox.innerHTML = `<span class="result-error">${escapeHtml(suiteId)}/${escapeHtml(waveId)} failed to run: ${escapeHtml(err.message)}</span>`;
      this.announce(`Wave check failed to run: ${err.message}`, { error: true });
    }
  }

  async runAllWaves() {
    if (this.waveRunActive) return;
    this.waveRunActive = true;
    const buttons = [
      document.getElementById('btn-run-all-waves'),
      document.getElementById('btn-run-all-waves-tab')
    ].filter(Boolean);
    const statusBox = document.getElementById('wave-run-status');
    const totalChecks = this.state.waves.length;
    buttons.forEach(button => { button.disabled = true; button.textContent = `Running 0/${totalChecks}…`; });
    try {
      const waves = this.state.waves.map(wave => ({ sId: wave.suite_id, wId: wave.wave_id }));
      const counts = new Map();
      let failedCount = 0;
      let environmentBlockedCount = 0;
      for (let index = 0; index < waves.length; index += 1) {
        const wave = waves[index];
        const progress = `Running ${index + 1}/${waves.length}: ${wave.sId}/${wave.wId}…`;
        statusBox.innerHTML = `<span class="pill-badge badge-blue">RUNNING</span> ${escapeHtml(progress)} Retained evidence remains unchanged.`;
        buttons.forEach(button => { button.textContent = `Running ${index + 1}/${waves.length}…`; });
        const res = await this.fetchJSON(
          `/api/waves/${encodeURIComponent(wave.sId)}/${encodeURIComponent(wave.wId)}/run`,
          { method: 'POST' }
        );
        if (res.passed || res.prototype_passed) {
          counts.set(res.execution_kind, (counts.get(res.execution_kind) || 0) + 1);
        } else if (res.execution_kind === 'unverifiable_environment') {
          environmentBlockedCount += 1;
        } else {
          failedCount += 1;
        }
      }
      const summary = [
        `${counts.get('verified_runtime_recovery') || 0} runtime recoveries`,
        `${counts.get('verified_source_execution') || 0} source executions`,
        `${counts.get('verified_analysis') || 0} analyses`,
        `${counts.get('verified_adoption') || 0} adoptions`,
        `${counts.get('verified_convergence') || 0} convergences`,
        `${counts.get('verified_resolution') || 0} resolutions`,
        `${counts.get('fast_probe') || 0} fast probes`,
        `${counts.get('prototype_check') || 0} prototype checks`,
        `${environmentBlockedCount} environment-unverifiable`,
        `${failedCount} failed`
      ].join(' · ');
      const summaryClass = failedCount
        ? 'result-error'
        : environmentBlockedCount
          ? 'result-warn'
          : 'result-success';
      statusBox.innerHTML = `<span class="${summaryClass}">Checks complete: ${escapeHtml(summary)}. No evidence was recorded.</span>`;
      this.announce(`All ${waves.length} checks finished. ${summary}. No retained evidence was changed.`);
      await this.refreshData();
    } catch (err) {
      statusBox.innerHTML = `<span class="result-error">Wave execution stopped: ${escapeHtml(err.message)}. No retained evidence was changed.</span>`;
      this.announce(`Wave execution stopped: ${err.message}`, { error: true });
    } finally {
      this.waveRunActive = false;
      buttons.forEach(button => {
        button.disabled = false;
        button.innerHTML = button.id === 'btn-run-all-waves'
          ? '<span class="btn-icon">▶</span> Verify All Waves'
          : 'Run All Checks';
      });
    }
  }

  async viewEvidence(evidencePath) {
    try {
      const res = await this.fetchJSON(`/api/evidence?file=${encodeURIComponent(evidencePath)}`);
      document.getElementById('evidence-modal-title').textContent = `Evidence: ${evidencePath}`;
      document.getElementById('evidence-modal-content').textContent = res.content;
      const modal = document.getElementById('evidence-modal');
      this.modalLastFocus = document.activeElement;
      modal.hidden = false;
      document.body.classList.add('modal-open');
      modal.querySelector('.modal-dialog').focus();
    } catch (err) {
      this.announce(`Evidence could not be loaded: ${err.message}`, { error: true });
    }
  }

  async viewDocument(documentId) {
    try {
      const res = await this.fetchJSON(`/api/docs/${encodeURIComponent(documentId)}`);
      document.getElementById('evidence-modal-title').textContent = res.name;
      document.getElementById('evidence-modal-content').textContent = res.content;
      const modal = document.getElementById('evidence-modal');
      this.modalLastFocus = document.activeElement;
      modal.hidden = false;
      document.body.classList.add('modal-open');
      modal.querySelector('.modal-dialog').focus();
    } catch (err) {
      this.announce(`Document could not be loaded: ${err.message}`, { error: true });
    }
  }

  closeEvidenceModal() {
    const modal = document.getElementById('evidence-modal');
    if (modal.hidden) return;
    modal.hidden = true;
    document.body.classList.remove('modal-open');
    if (this.modalLastFocus instanceof HTMLElement) this.modalLastFocus.focus();
    this.modalLastFocus = null;
  }

  handleModalKeydown(event) {
    const modal = document.getElementById('evidence-modal');
    if (modal.hidden) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      this.closeEvidenceModal();
      return;
    }
    if (event.key !== 'Tab') return;
    const focusable = [...modal.querySelectorAll('button, [href], [tabindex]:not([tabindex="-1"])')]
      .filter(element => !element.disabled && !element.hidden);
    if (!focusable.length) {
      event.preventDefault();
      modal.querySelector('.modal-dialog').focus();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  inspectSuite(suiteId) {
    this.switchTab('suites');
    const elem = document.getElementById(`suite-card-${suiteId}`);
    if (elem) elem.scrollIntoView({ behavior: 'smooth' });
  }

  async fetchDrift() {
    const driftRes = await fetch('/api/drift').then(r => r.json());
    this.state.drift = driftRes;
    this.renderDriftTable();
  }
}

// Instantiate on load
window.addEventListener('DOMContentLoaded', () => {
  window.app = new SuitesApp();
});

// --- Toolbench: run suite engine actions and collect typed output ---
class Toolbench {
  constructor() {
    this.catalog = {};
    this.tray = [];
    this.sensitiveArgumentKeyPattern = null;
    this.redactedArgumentValue = null;
    this.el = (id) => document.getElementById(id);
  }

  async init() {
    const [catalog, policyDocument] = await Promise.all([
      fetch('/api/engines').then(response => {
        if (!response.ok) throw new Error(`Engine catalog request failed (${response.status})`);
        return response.json();
      }),
      fetch('/api/security-policy').then(response => {
        if (!response.ok) throw new Error(`Security policy request failed (${response.status})`);
        return response.json();
      })
    ]);
    const policy = policyDocument?.argument_redaction;
    if (
      !policy
      || typeof policy.pattern !== 'string'
      || typeof policy.flags !== 'string'
      || typeof policy.redacted_value !== 'string'
      || !policy.redacted_value
    ) {
      throw new Error('Server returned an invalid Toolbench argument-redaction policy');
    }
    this.catalog = catalog;
    this.sensitiveArgumentKeyPattern = new RegExp(policy.pattern, policy.flags);
    this.redactedArgumentValue = policy.redacted_value;
    const suiteSel = this.el('tb-suite');
    suiteSel.innerHTML = Object.keys(this.catalog)
      .map(id => `<option value="${escapeHtml(id)}">${escapeHtml(id)}</option>`).join('');
    suiteSel.addEventListener('change', () => this.renderActions());
    this.el('tb-action').addEventListener('change', () => this.renderSignature());
    this.el('tb-run').addEventListener('click', () => this.run());
    this.el('tb-fill-defaults').addEventListener('click', () => this.fillDefaults());
    this.el('tb-clear-tray').addEventListener('click', () => { this.tray = []; this.renderTray(); });
    this.el('tb-compare').addEventListener('click', () => this.compare());
    this.el('tb-copy-chain').addEventListener('click', () => this.copyChain());
    // Tray identifiers live in data attributes, matching the app's no-inline-handler rule.
    this.el('tb-tray').addEventListener('click', (event) => {
      if (!(event.target instanceof Element)) return;
      const trigger = event.target.closest('[data-tb-action]');
      if (!trigger) return;
      const index = Number(trigger.dataset.tbIndex);
      if (trigger.dataset.tbAction === 'show-result') this.show(index);
      if (trigger.dataset.tbAction === 'use-result') this.useAsArgument(index);
    });
    this.renderActions();
    this.renderTray();
  }

  current() {
    const suite = this.el('tb-suite').value;
    const action = this.el('tb-action').value;
    const entry = (this.catalog[suite]?.actions || []).find(a => a.name === action);
    return { suite, action, entry };
  }

  renderActions() {
    const suite = this.el('tb-suite').value;
    const info = this.catalog[suite];
    this.el('tb-action').innerHTML = info.actions
      .map(a => `<option value="${escapeHtml(a.name)}">${escapeHtml(a.name)}</option>`).join('');
    this.renderSignature();
  }

  renderSignature() {
    const { entry } = this.current();
    if (!entry) { this.el('tb-signature').innerHTML = ''; return; }
    this.el('tb-emits').textContent = entry.emits || entry.output_kind || '-';
    const rows = entry.parameters.map(p => `
      <div class="spec-field-row">
        <code>${escapeHtml(p.name)}</code>
        <span class="${p.required ? 'badge-red' : 'badge-green'} pill-badge">${p.required ? 'required' : 'optional'}</span>
        <span class="subtext">${escapeHtml(p.type)}${p.required ? '' : ` = ${escapeHtml(JSON.stringify(p.default))}`}</span>
      </div>`).join('');
    this.el('tb-signature').innerHTML =
      `<p class="subtext">${escapeHtml(entry.summary || '')}</p>${rows || '<p class="subtext">No arguments.</p>'}`;
    this.fillDefaults();
  }

  fillDefaults() {
    const { entry } = this.current();
    if (!entry) return;
    const args = {};
    entry.parameters.forEach(p => { if (!p.required) args[p.name] = p.default; });
    entry.parameters.filter(p => p.required).forEach(p => { args[p.name] = null; });
    this.el('tb-args').value = JSON.stringify(args, null, 2);
  }

  async run() {
    const { suite, action } = this.current();
    const status = this.el('tb-status');
    let args;
    try {
      args = JSON.parse(this.el('tb-args').value || '{}');
    } catch (err) {
      status.innerHTML = `<span class="badge-red pill-badge">INVALID JSON</span> ${escapeHtml(err.message)}`;
      return;
    }
    const chained = referencedStepIndexes(args).size > 0;
    status.innerHTML = `<span class="pill-badge">${chained ? 'RUNNING CHAIN...' : 'RUNNING...'}</span>`;

    let chainSteps = null;
    if (chained) {
      try {
        chainSteps = this.buildChain(args);
      } catch (error) {
        status.innerHTML = `<span class="badge-red pill-badge">INVALID CHAIN</span> ${escapeHtml(error.message)}`;
        return;
      }
    }

    let res;
    let body;
    try {
      res = chained
        ? await fetch('/api/chains/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ steps: chainSteps })
          })
        : await fetch(`/api/engines/${encodeURIComponent(suite)}/${encodeURIComponent(action)}/run`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(args)
          });
      body = await res.json();
    } catch (error) {
      status.innerHTML = `<span class="badge-red pill-badge">NETWORK</span> ${escapeHtml(error.message)}`;
      this.el('tb-output').textContent = '';
      return;
    }
    if (!res.ok) {
      const stepIndex = body.step_index ?? body.step;
      const where = stepIndex === undefined || stepIndex === null ? '' : ` at step ${stepIndex}`;
      status.innerHTML = `<span class="badge-red pill-badge">${escapeHtml(res.status)}${escapeHtml(where)}</span> ${escapeHtml(body.error)}`;
      this.el('tb-output').textContent = '';
      return;
    }

    const emits = chained ? body.steps[body.steps.length - 1].emits : body.emits;
    const result = chained ? body.final : body.result;
    const trace = chained
      ? ` <span class="subtext">(replayed ${escapeHtml(body.steps_run)} step chain)</span>`
      : '';
    status.innerHTML = `<span class="badge-green pill-badge">OK</span> ${escapeHtml(suite)}.${escapeHtml(action)} &rarr; <strong>${escapeHtml(emits)}</strong>${trace}`;
    this.el('tb-output').textContent = JSON.stringify(result, null, 2);
    this.tray.push({
      suite,
      action,
      args: redactSensitiveArguments(
        args,
        this.sensitiveArgumentKeyPattern,
        this.redactedArgumentValue
      ),
      emits,
      result
    });
    this.renderTray();
  }

  renderTray() {
    const tray = this.el('tb-tray');
    if (!this.tray.length) { tray.innerHTML = '<p class="subtext">No results yet. Run a tool.</p>'; return; }
    tray.innerHTML = this.tray.map((item, i) => `
      <div class="spec-field-row">
        <span class="pill-badge">${escapeHtml(item.emits)}</span>
        <code>${escapeHtml(item.suite)}.${escapeHtml(item.action)}</code>
        <button class="btn btn-sm btn-secondary" data-tb-action="show-result" data-tb-index="${escapeHtml(i)}">view</button>
        <button class="btn btn-sm btn-secondary" data-tb-action="use-result" data-tb-index="${escapeHtml(i)}">use</button>
      </div>`).join('');
  }

  show(index) {
    this.el('tb-output').textContent = JSON.stringify(this.tray[index].result, null, 2);
  }

  // Insert a {"$from": n} reference for the first argument that has no value yet.
  useAsArgument(index) {
    const { entry } = this.current();
    const editor = this.el('tb-args');
    let args;
    try {
      args = JSON.parse(editor.value || '{}');
    } catch {
      args = {};
    }
    const params = (entry?.parameters || []).map(p => p.name);
    const target = params.find(name => args[name] === null || args[name] === undefined) || params[0];
    if (!target) {
      this.el('tb-status').innerHTML = '<span class="badge-red pill-badge">NO ARGUMENTS</span> This action takes none.';
      return;
    }
    args[target] = { $from: index };
    editor.value = JSON.stringify(args, null, 2);
    this.el('tb-status').innerHTML =
      `<span class="pill-badge">CHAINED</span> <code>${escapeHtml(target)}</code> &larr; step ${escapeHtml(index)} (${escapeHtml(this.tray[index].emits)}). Add <code>"path"</code> to select part of it.`;
  }

  buildChain(args) {
    // Replay only the transitive dependencies of the pending action. Replaying every tray item
    // could repeat unrelated work, and a consumed approval token must never be retained/replayed.
    const dependencies = collectChainDependencies(args, this.tray);
    const indexMap = new Map(dependencies.map((original, rebased) => [original, rebased]));
    const steps = dependencies.map(index => {
      const item = this.tray[index];
      if (containsRedactedArgument(item.args, this.redactedArgumentValue)) {
        throw new Error(`tray step ${index} used a one-time secret and cannot be replayed`);
      }
      return {
        suite: item.suite,
        action: item.action,
        arguments: rebaseChainReferences(item.args, indexMap)
      };
    });
    const { suite, action } = this.current();
    steps.push({ suite, action, arguments: rebaseChainReferences(args, indexMap) });
    return steps;
  }

  async copyChain() {
    const steps = this.tray.map(item => ({ suite: item.suite, action: item.action, arguments: item.args }));
    if (!steps.length) {
      this.el('tb-status').innerHTML = '<span class="badge-red pill-badge">EMPTY</span> Run a tool first.';
      return;
    }
    const chainJSON = JSON.stringify(steps, null, 2);
    this.el('tb-output').textContent = chainJSON;
    try {
      await navigator.clipboard.writeText(chainJSON);
      this.el('tb-status').innerHTML =
        `<span class="badge-green pill-badge">COPIED</span> ${escapeHtml(steps.length)} step(s) copied &mdash; save and replay with <code>suites chain &lt;file&gt;</code>.`;
    } catch {
      this.el('tb-status').innerHTML =
        `<span class="badge-yellow pill-badge">CHAIN JSON</span> Clipboard access was unavailable. The ${escapeHtml(steps.length)} step chain is selected below for manual copy.`;
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(this.el('tb-output'));
      selection.removeAllRanges();
      selection.addRange(range);
    }
  }

  // The cross-suite payoff: three suites emit ExperimentRun, so they compare in one table.
  async compare() {
    const runs = this.tray.filter(item => item.emits === 'ExperimentRun').map(item => item.result);
    const status = this.el('tb-status');
    if (runs.length < 2) {
      status.innerHTML = '<span class="badge-red pill-badge">NEED 2+</span> Run at least two ExperimentRun tools (agent-reliability, game-design, model-behavior-lab).';
      return;
    }
    let res;
    let body;
    try {
      res = await fetch('/api/engines/model-behavior-lab/compare_runs/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ runs })
      });
      body = await res.json();
    } catch (error) {
      status.innerHTML = `<span class="badge-red pill-badge">NETWORK</span> ${escapeHtml(error.message)}`;
      return;
    }
    if (!res.ok) {
      status.innerHTML = `<span class="badge-red pill-badge">${escapeHtml(res.status)}</span> ${escapeHtml(body.error)}`;
      return;
    }
    status.innerHTML = `<span class="badge-green pill-badge">COMPARED</span> ${runs.length} ExperimentRuns across suites`;
    this.el('tb-output').textContent = JSON.stringify(body.result, null, 2);
  }
}

window.addEventListener('DOMContentLoaded', () => {
  window.toolbench = new Toolbench();
  window.toolbench.init().catch(err => console.error('[Toolbench]', err));
});
