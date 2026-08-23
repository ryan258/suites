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
      waves: []
    };

    this.init();
  }

  async init() {
    this.bindEvents();
    await this.refreshData();
    this.selectContract('A11yFinding');
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
    document.getElementById('btn-close-modal').addEventListener('click', () => {
      document.getElementById('evidence-modal').style.display = 'none';
    });
  }

  switchTab(tabId) {
    document.querySelectorAll('.nav-item').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.tab === tabId);
    });
    document.querySelectorAll('.tab-pane').forEach(pane => {
      pane.classList.toggle('active', pane.id === `tab-${tabId}`);
    });
  }

  async refreshData() {
    try {
      const [sumRes, suitesRes, projRes, nestedRes, driftRes, contractsRes, valRes] = await Promise.all([
        fetch('/api/summary').then(r => r.json()),
        fetch('/api/suites').then(r => r.json()),
        fetch('/api/projects').then(r => r.json()),
        fetch('/api/nested').then(r => r.json()),
        fetch('/api/drift').then(r => r.json()),
        fetch('/api/contracts').then(r => r.json()),
        fetch('/api/validate').then(r => r.json())
      ]);

      this.state.summary = sumRes;
      this.state.suites = suitesRes;
      this.state.projects = projRes;
      this.state.nested = nestedRes;
      this.state.drift = driftRes;
      this.state.contracts = contractsRes;

      this.renderHeaderMetrics(valRes);
      this.renderOverview();
      this.renderSuites();
      this.renderProjectsTable();
      this.renderDriftTable();
      this.renderNestedTable();
      this.renderWaves();
    } catch (err) {
      console.error('Failed to load portfolio data:', err);
    }
  }

  renderHeaderMetrics(valRes) {
    document.getElementById('stat-projects').textContent = this.state.projects.length;
    document.getElementById('stat-suites').textContent = this.state.suites.length;
    
    const sum = this.state.summary;
    if (sum) {
      document.getElementById('stat-waves').textContent = `${sum.completed_waves}/${sum.total_waves}`;
      document.getElementById('card-progress-pct').textContent = `${sum.portfolio_progress_pct}%`;
      document.getElementById('card-progress-bar').style.width = `${sum.portfolio_progress_pct}%`;
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
          ? `${owing} completed wave(s) still owe a live run`
          : 'no outstanding runtime follow-up';
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

    const allWaves = [];
    this.state.suites.forEach(s => {
      (s.waves || []).forEach(w => {
        allWaves.push({ suite: s, wave: w });
      });
    });

    container.innerHTML = allWaves.map(({ suite, wave }) => `
      <div class="wave-card" id="wave-card-${escapeHtml(suite.id)}-${escapeHtml(wave.id)}">
        <div class="wave-card-header">
          <span class="wave-id-badge">${escapeHtml(suite.name)} &bull; ${escapeHtml(wave.id)}</span>
          <span class="pill-badge ${wave.status === 'complete' ? 'badge-green' : 'badge-yellow'}">${escapeHtml(wave.status)}</span>
        </div>
        <div class="wave-objective">${escapeHtml(wave.objective)}</div>
        <div class="wave-acceptance">${escapeHtml(wave.acceptance)}</div>
        <div class="wave-actions">
          <button class="btn btn-sm btn-primary" data-app-action="run-wave" data-suite-id="${escapeHtml(suite.id)}" data-wave-id="${escapeHtml(wave.id)}">Run Gate Check</button>
          ${wave.evidence ? `<button class="btn btn-sm btn-secondary" data-app-action="view-evidence" data-evidence="${escapeHtml(wave.evidence)}">Evidence</button>` : ''}
        </div>
      </div>
    `).join('');
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
    try {
      const res = await fetch(`/api/waves/${suiteId}/${waveId}/run`, { method: 'POST' }).then(r => r.json());
      const resultLabel = res.execution_kind === 'verified_runtime_recovery' && res.passed
        ? 'VERIFIED RUNTIME RECOVERY'
        : res.execution_kind === 'verified_analysis' && res.passed
          ? 'VERIFIED ANALYSIS'
        : res.execution_kind === 'prototype_check' && res.prototype_passed
          ? 'PROTOTYPE CHECK PASSED'
          : res.execution_kind === 'unverifiable_environment'
            ? 'UNVERIFIABLE IN THIS ENVIRONMENT'
          : res.execution_kind === 'unintegrated_specification'
            ? 'SPECIFIED / NOT INTEGRATED'
            : 'FAILED';
      alert(`Wave ${suiteId}/${waveId} Result:\n\n${resultLabel}\nMessage: ${res.message}\n${res.evidence_path ? 'Evidence: ' + res.evidence_path : ''}`);
      await this.refreshData();
    } catch (err) {
      alert(`Failed to run wave: ${err.message}`);
    }
  }

  async runAllWaves() {
    const btn = document.getElementById('btn-run-all-waves');
    if (btn) btn.textContent = 'Running...';
    try {
      const waves = [];
      this.state.suites.forEach(s => {
        (s.waves || []).forEach(w => waves.push({ sId: s.id, wId: w.id }));
      });

      let recoveredCount = 0;
      let analysisCount = 0;
      let prototypeCount = 0;
      let unresolvedCount = 0;
      for (const w of waves) {
        const res = await fetch(`/api/waves/${w.sId}/${w.wId}/run`, { method: 'POST' }).then(r => r.json());
        if (res.execution_kind === 'verified_runtime_recovery' && res.passed) {
          recoveredCount++;
        } else if (res.execution_kind === 'verified_analysis' && res.passed) {
          analysisCount++;
        } else if (res.execution_kind === 'prototype_check' && res.prototype_passed) {
          prototypeCount++;
        } else {
          unresolvedCount++;
        }
      }

      alert(
        `Wave checks complete.\n\n` +
        `${recoveredCount} verified runtime recoveries\n` +
        `${analysisCount} verified analyses\n` +
        `${prototypeCount} prototype checks passed\n` +
        `${unresolvedCount} failed or unintegrated`
      );
      await this.refreshData();
    } catch (err) {
      alert(`Wave execution error: ${err.message}`);
    } finally {
      if (btn) btn.innerHTML = '<span class="btn-icon">▶</span> Verify All Waves';
    }
  }

  async viewEvidence(evidencePath) {
    try {
      const res = await fetch(`/api/evidence?file=${encodeURIComponent(evidencePath)}`).then(r => r.json());
      if (res.error) {
        alert(`Could not load evidence: ${res.error}`);
        return;
      }
      document.getElementById('evidence-modal-title').textContent = `Evidence: ${evidencePath}`;
      document.getElementById('evidence-modal-content').textContent = res.content;
      document.getElementById('evidence-modal').style.display = 'flex';
    } catch (err) {
      alert(`Evidence fetch error: ${err.message}`);
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
    this.el = (id) => document.getElementById(id);
  }

  async init() {
    this.catalog = await fetch('/api/engines').then(r => r.json());
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
    this.el('tb-emits').textContent = info.emits || '-';
    this.renderSignature();
  }

  renderSignature() {
    const { entry } = this.current();
    if (!entry) { this.el('tb-signature').innerHTML = ''; return; }
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
    const chained = this.referencedSteps(args).size > 0;
    status.innerHTML = `<span class="pill-badge">${chained ? 'RUNNING CHAIN...' : 'RUNNING...'}</span>`;

    const res = chained
      ? await fetch('/api/chains/run', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ steps: this.buildChain(args) })
        })
      : await fetch(`/api/engines/${suite}/${action}/run`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(args)
        });
    const body = await res.json();
    if (!res.ok) {
      const where = body.step === undefined || body.step === null ? '' : ` at step ${body.step}`;
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
    this.tray.push({ suite, action, args, emits, result });
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

  // Steps referenced by the pending arguments, plus everything they transitively need.
  referencedSteps(value, found = new Set()) {
    if (value && typeof value === 'object') {
      if (!Array.isArray(value) && '$from' in value) {
        found.add(value.$from);
        return found;
      }
      Object.values(value).forEach(item => this.referencedSteps(item, found));
    }
    return found;
  }

  buildChain(args) {
    // Tray order is chain order, so a reference to step n resolves to tray index n.
    const steps = this.tray.map(item => ({ suite: item.suite, action: item.action, arguments: item.args }));
    const { suite, action } = this.current();
    steps.push({ suite, action, arguments: args });
    return steps;
  }

  copyChain() {
    const steps = this.tray.map(item => ({ suite: item.suite, action: item.action, arguments: item.args }));
    if (!steps.length) {
      this.el('tb-status').innerHTML = '<span class="badge-red pill-badge">EMPTY</span> Run a tool first.';
      return;
    }
    this.el('tb-output').textContent = JSON.stringify(steps, null, 2);
    this.el('tb-status').innerHTML =
      `<span class="badge-green pill-badge">CHAIN JSON</span> ${escapeHtml(steps.length)} step(s) shown below &mdash; save it and replay with <code>suites chain &lt;file&gt;</code>.`;
  }

  // The cross-suite payoff: three suites emit ExperimentRun, so they compare in one table.
  async compare() {
    const runs = this.tray.filter(item => item.emits === 'ExperimentRun').map(item => item.result);
    const status = this.el('tb-status');
    if (runs.length < 2) {
      status.innerHTML = '<span class="badge-red pill-badge">NEED 2+</span> Run at least two ExperimentRun tools (agent-reliability, game-design, model-behavior-lab).';
      return;
    }
    const res = await fetch('/api/engines/model-behavior-lab/compare_runs/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ runs })
    });
    const body = await res.json();
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

