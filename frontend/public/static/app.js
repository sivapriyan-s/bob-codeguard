/**
 * app.js — Bob CodeGuard frontend
 * Uses EventSource (SSE) for real-time workflow progress.
 * Handles: findings, impact map, doc drift, code changes, report.
 */

// ── State ─────────────────────────────────────────────────────────────────────
const state = {
  currentJobId: null,
  eventSource: null,
  report: null,
};

// ── DOM refs ──────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const $inp = { repo: $('inp-repo'), mode: $('inp-mode'), ref: $('inp-ref') };
const $btn = { analyze: $('btn-analyze'), copyReport: $('btn-copy-report'), refreshJobs: $('btn-refresh-jobs') };
const $panels = { workflow: $('workflow-panel'), results: $('results-panel'), error: $('analyze-error') };

// ── Navigation ────────────────────────────────────────────────────────────────
document.querySelectorAll('.nav-link').forEach(link => {
  link.addEventListener('click', e => {
    e.preventDefault();
    const view = link.dataset.view;
    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    link.classList.add('active');
    document.getElementById(`view-${view}`)?.classList.add('active');
    if (view === 'jobs') refreshJobs();
  });
});

// ── Tabs ──────────────────────────────────────────────────────────────────────
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    const pane = tab.dataset.tab;
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById(`tab-${pane}`)?.classList.add('active');
  });
});

// ── Analyze ───────────────────────────────────────────────────────────────────
$btn.analyze.addEventListener('click', startAnalysis);

async function startAnalysis() {
  const repo = $inp.repo.value.trim();
  const mode = $inp.mode.value;
  const ref  = $inp.ref.value.trim();

  hideError();
  if (!repo || !repo.includes('/')) return showError('Enter a valid repository in owner/repo format.');
  if (!ref) return showError('Enter a PR or issue number.');

  // Close any existing stream
  closeStream();

  $btn.analyze.disabled = true;
  $btn.analyze.innerHTML = '<span class="btn-icon">⏳</span> Starting…';

  try {
    const res = await fetch('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repository: repo, mode, ref }),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Server error');
    }
    const data = await res.json();
    state.currentJobId = data.job_id;

    showWorkflowPanel(repo, mode);
    openStream(data.job_id);
  } catch (e) {
    showError(e.message);
    resetAnalyzeBtn();
  }
}

function showWorkflowPanel(repo, mode) {
  $panels.workflow.classList.remove('hidden');
  $panels.results.classList.add('hidden');
  $('workflow-repo').textContent = `${repo} · ${mode}`;
  $('workflow-steps').innerHTML = '';
  $('workflow-spinner').style.display = 'flex';
  $('workflow-status-text').textContent = 'Connecting…';
}

// ── SSE Stream ────────────────────────────────────────────────────────────────
function openStream(jobId) {
  const es = new EventSource(`/api/jobs/${jobId}/stream`);
  state.eventSource = es;

  es.onmessage = e => {
    const msg = JSON.parse(e.data);

    if (msg.type === 'progress') {
      renderWorkflowSteps(msg.steps || []);
      $('workflow-status-text').textContent = statusText(msg.status);
    }

    if (msg.type === 'done') {
      renderWorkflowSteps(msg.steps || state._lastSteps || []);
      $('workflow-spinner').style.display = 'none';
      $('workflow-status-text').textContent = 'Analysis complete ✓';
      resetAnalyzeBtn();
      if (msg.report) renderResults(msg.report);
      es.close();
    }

    if (msg.type === 'error') {
      $('workflow-spinner').style.display = 'none';
      showError(`Analysis failed: ${msg.message}`);
      resetAnalyzeBtn();
      es.close();
    }

    // Cache last steps for 'done' event
    if (msg.steps) state._lastSteps = msg.steps;
  };

  es.onerror = () => {
    // SSE connection lost — fall back to one-shot poll
    es.close();
    state.eventSource = null;
    setTimeout(() => fallbackPoll(jobId), 2000);
  };
}

function closeStream() {
  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }
}

// Fallback: single poll if SSE fails
async function fallbackPoll(jobId) {
  try {
    const res = await fetch(`/api/jobs/${jobId}`);
    if (!res.ok) return;
    const job = await res.json();
    renderWorkflowSteps(job.steps || []);
    $('workflow-status-text').textContent = statusText(job.status);
    if (job.status === 'done') {
      $('workflow-spinner').style.display = 'none';
      resetAnalyzeBtn();
      if (job.report) renderResults(job.report);
    } else if (job.status === 'error') {
      $('workflow-spinner').style.display = 'none';
      showError(`Analysis failed: ${job.error || 'Unknown error'}`);
      resetAnalyzeBtn();
    } else {
      setTimeout(() => fallbackPoll(jobId), 1500);
    }
  } catch (e) {
    setTimeout(() => fallbackPoll(jobId), 2000);
  }
}

function statusText(s) {
  return { pending: 'Queued…', running: 'Running analysis…', done: 'Analysis complete ✓', error: 'Analysis failed' }[s] || s;
}

// ── Workflow Steps ────────────────────────────────────────────────────────────
function renderWorkflowSteps(steps) {
  $('workflow-steps').innerHTML = steps.map(s => `
    <div class="workflow-step step--${s.status}">
      <span class="step-icon"></span>
      <span class="step-name">${esc(s.name)}</span>
      <span class="step-detail">${esc(s.detail || '')}</span>
    </div>
  `).join('');
}

// ── Results ───────────────────────────────────────────────────────────────────
function renderResults(report) {
  state.report = report;
  $panels.results.classList.remove('hidden');

  // Show/hide code-changes tab based on mode
  const hasBugFix = !!(report.bug_fix && report.bug_fix.changes_made?.length);
  const changesTab = document.querySelector('[data-tab="changes"]');
  if (changesTab) changesTab.style.display = hasBugFix ? '' : 'none';

  renderSummaryBar(report);
  renderFindings(report.all_findings || []);
  renderImpactMap(report.impact_map || []);
  renderDrifts(report.documentation_drifts || []);
  if (hasBugFix) renderCodeChanges(report.bug_fix);
  renderReport(report);
}

// ── Summary Bar ───────────────────────────────────────────────────────────────
function renderSummaryBar(report) {
  const findings = report.all_findings || [];
  const counts = {};
  findings.forEach(f => { counts[f.severity] = (counts[f.severity] || 0) + 1; });
  const drifts = (report.documentation_drifts || []).length;
  const impacts = countImpactNodes(report.impact_map || []);

  const pr = report.pr_review;
  const det = report.pr_detective;
  const bf = report.bug_fix;

  let pills = '';
  if (counts.critical)    pills += `<span class="summary-pill pill--critical">🔴 ${counts.critical} Critical</span>`;
  if (counts.warning)     pills += `<span class="summary-pill pill--warning">🟠 ${counts.warning} Warning</span>`;
  if (counts.suggestion)  pills += `<span class="summary-pill pill--info">🔵 ${counts.suggestion} Suggestion</span>`;
  if (drifts)             pills += `<span class="summary-pill pill--warning">📖 ${drifts} Doc Drift${drifts !== 1 ? 's' : ''}</span>`;
  if (impacts)            pills += `<span class="summary-pill pill--muted">🗺️ ${impacts} Impact Node${impacts !== 1 ? 's' : ''}</span>`;
  if (pr)                 pills += `<span class="summary-pill pill--${pr.recommendation === 'approve' ? 'success' : pr.recommendation === 'request_changes' ? 'critical' : 'info'}">PR: ${esc(pr.recommendation?.replace('_', ' ').toUpperCase() || '')}</span>`;
  if (bf?.changes_made?.length) pills += `<span class="summary-pill pill--success">🔧 ${bf.changes_made.length} Fix Proposed</span>`;
  if (!findings.length && !drifts) pills += '<span class="summary-pill pill--success">✅ No issues found</span>';

  $('summary-bar').innerHTML = pills;
}

function countImpactNodes(nodes) {
  return nodes.reduce((acc, n) => acc + 1 + countImpactNodes(n.children || []), 0);
}

// ── Findings ──────────────────────────────────────────────────────────────────
const CATEGORY_LABELS = {
  bug: '🐛 Bug', security: '🔒 Security', code_quality: '🔧 Code Quality',
  testing: '🧪 Testing', regression: '⚠️ Regression', documentation: '📖 Documentation',
  impact: '🗺️ Impact', api: '🌐 API',
};
const SEV_ORDER = { critical: 0, warning: 1, suggestion: 2, info: 3 };

function renderFindings(findings) {
  if (!findings.length) {
    $('findings-list').innerHTML = '<div class="empty-state">No findings detected.</div>';
    return;
  }
  const groups = {};
  findings.forEach(f => { (groups[f.category] = groups[f.category] || []).push(f); });
  Object.values(groups).forEach(arr => arr.sort((a, b) => (SEV_ORDER[a.severity] || 3) - (SEV_ORDER[b.severity] || 3)));

  $('findings-list').innerHTML = Object.entries(groups).map(([cat, items]) => `
    <div class="findings-group">
      <div class="findings-group-title">${CATEGORY_LABELS[cat] || cat} (${items.length})</div>
      ${items.map(findingCard).join('')}
    </div>
  `).join('');

  document.querySelectorAll('.finding-header').forEach(h => {
    h.addEventListener('click', () => h.nextElementSibling?.classList.toggle('open'));
  });
}

function findingCard(f) {
  const ev = (f.evidence || []).map(e => `
    <div class="evidence-block">
      <div class="evidence-label">Evidence</div>
      <div class="evidence-file">${esc(e.file)}${e.line ? `:${e.line}` : ''}${e.symbol ? ` · ${esc(e.symbol)}` : ''}</div>
      ${e.snippet ? `<div class="evidence-snippet">${esc(e.snippet)}</div>` : ''}
      <div style="font-size:12px;color:var(--muted);margin-top:5px">${esc(e.reason)}</div>
    </div>
  `).join('');
  return `
    <div class="finding-card">
      <div class="finding-header">
        <span class="sev-badge sev--${f.severity}">${f.severity}</span>
        <span class="finding-title">${esc(f.title)}</span>
        <span class="finding-cat">${CATEGORY_LABELS[f.category] || f.category}</span>
        <span class="finding-conf conf--${f.confidence}">${f.confidence}</span>
      </div>
      <div class="finding-body">
        <div class="finding-desc">${esc(f.description)}</div>
        ${ev}
        ${f.suggested_action ? `<div class="action-block"><span class="action-label">Suggested Action: </span>${esc(f.suggested_action)}</div>` : ''}
      </div>
    </div>
  `;
}

// ── Impact Map ────────────────────────────────────────────────────────────────
function renderImpactMap(nodes) {
  if (!nodes.length) {
    $('impact-tree').innerHTML = '<div class="empty-state">No impact map available. Use PR Detective or full_pr mode.</div>';
    return;
  }
  $('impact-tree').innerHTML = `<div class="impact-root">${renderNodes(nodes, 0)}</div>`;
}

function renderNodes(nodes, depth) {
  return nodes.map(n => {
    const depthClass = ['', 'impact-node--child', 'impact-node--grandchild'][depth] || 'impact-node--grandchild';
    const children = n.children?.length ? renderNodes(n.children, depth + 1) : '';
    return `
      <div class="impact-node ${depthClass}">
        ${depth > 0 ? '<div class="impact-indent"></div>' : ''}
        <span class="impact-path">${esc(n.path)} <small style="color:var(--muted)">[${n.kind}]</small></span>
        <span class="impact-rel">${esc(n.relation)}</span>
        <span class="impact-conf conf--${n.confidence}">${n.confidence}</span>
      </div>
      ${children}
    `;
  }).join('');
}

// ── Doc Drifts ────────────────────────────────────────────────────────────────
function renderDrifts(drifts) {
  if (!drifts.length) {
    $('drifts-list').innerHTML = '<div class="empty-state">No documentation drift detected.</div>';
    return;
  }
  $('drifts-list').innerHTML = drifts.map(d => `
    <div class="drift-card">
      <div class="drift-header">
        <span class="drift-status status--${d.status}">${d.status}</span>
        <span class="drift-file">${esc(d.doc_file)}</span>
        <span class="drift-section">§ ${esc(d.section)}</span>
      </div>
      <div class="drift-body">
        <div class="drift-compare">
          <div class="drift-side">
            <h4>Code Truth</h4>
            <div class="drift-text">${esc(d.code_truth)}</div>
          </div>
          <div class="drift-side">
            <h4>Documentation Says</h4>
            <div class="drift-text">${esc(d.doc_current)}</div>
          </div>
        </div>
        ${d.suggested_update ? `
          <div class="drift-suggested">
            <label>Suggested Update</label>
            <pre>${esc(d.suggested_update)}</pre>
          </div>` : ''}
      </div>
    </div>
  `).join('');
}

// ── Code Changes (Bug Fix) ────────────────────────────────────────────────────
function renderCodeChanges(bugFix) {
  const container = $('changes-list');
  if (!container) return;

  const changes = bugFix.changes_made || [];
  const tests = bugFix.tests_added || [];
  const sideEffects = bugFix.potential_side_effects || [];

  let html = '';

  if (bugFix.root_cause) {
    html += `
      <div class="change-section">
        <div class="change-section-title">Root Cause</div>
        <div class="change-desc">${esc(bugFix.root_cause)}</div>
      </div>`;
  }

  if (changes.length) {
    html += `<div class="change-section-title" style="margin:16px 0 8px">Proposed Code Changes (${changes.length})</div>`;
    html += changes.map(ch => `
      <div class="change-card">
        <div class="change-header">
          <span class="change-type-badge type--${ch.type || 'modify'}">${ch.type || 'modify'}</span>
          <span class="change-file">${esc(ch.file)}</span>
        </div>
        <div class="change-body">
          <div class="change-desc">${esc(ch.description)}</div>
          ${ch.search ? `
            <div class="diff-block">
              <div class="diff-label">Remove</div>
              <pre class="diff-old">${esc(ch.search)}</pre>
            </div>` : ''}
          ${ch.replacement ? `
            <div class="diff-block">
              <div class="diff-label">Add</div>
              <pre class="diff-new">${esc(ch.replacement)}</pre>
            </div>` : ''}
        </div>
      </div>
    `).join('');
  }

  if (tests.length) {
    html += `
      <div class="change-section" style="margin-top:20px">
        <div class="change-section-title">Tests to Add (${tests.length})</div>
        ${tests.map(t => `<div class="test-item">🧪 ${esc(t)}</div>`).join('')}
      </div>`;
  }

  if (sideEffects.length) {
    html += `
      <div class="change-section" style="margin-top:20px">
        <div class="change-section-title">⚠️ Potential Side Effects</div>
        ${sideEffects.map(s => `<div class="test-item side-effect">⚠️ ${esc(s)}</div>`).join('')}
      </div>`;
  }

  container.innerHTML = html || '<div class="empty-state">No code changes were proposed.</div>';
}

// ── Report ─────────────────────────────────────────────────────────────────────
function renderReport(report) {
  const text = buildReportText(report);
  $('report-content').innerHTML = `<div class="report-block">${esc(text)}</div>`;
}

function buildReportText(r) {
  const LINE = '─'.repeat(60);
  const findings = r.all_findings || [];
  const counts = {};
  findings.forEach(f => { counts[f.severity] = (counts[f.severity] || 0) + 1; });

  let txt = `CodeGuard Analysis Report
${LINE}
Report ID : ${r.report_id}
Generated : ${r.generated_at}
Repository: ${r.repository}
Reference : ${r.ref}
${LINE}

EXECUTIVE SUMMARY
${r.executive_summary || '(none)'}

ROOT CAUSE
${r.root_cause || '(none)'}

CHANGED COMPONENTS (${(r.changed_components || []).length})
${(r.changed_components || []).map(c => `  • ${c}`).join('\n') || '  (none)'}

FINDINGS SUMMARY
  Critical   : ${counts.critical || 0}
  Warning    : ${counts.warning || 0}
  Suggestion : ${counts.suggestion || 0}
  Info       : ${counts.info || 0}
  Total      : ${findings.length}

`;

  if (findings.length) {
    txt += `FINDINGS\n`;
    findings.forEach((f, i) => {
      txt += `\n[${i + 1}] [${f.severity.toUpperCase()}] ${f.title}\n`;
      txt += `    Category   : ${f.category}\n`;
      txt += `    Confidence : ${f.confidence}\n`;
      txt += `    ${f.description}\n`;
      (f.evidence || []).forEach(e => {
        txt += `    Evidence   : ${e.file}${e.line ? ':' + e.line : ''}${e.symbol ? ' · ' + e.symbol : ''}\n`;
        if (e.reason) txt += `    Reason     : ${e.reason}\n`;
      });
      if (f.suggested_action) txt += `    Action     : ${f.suggested_action}\n`;
    });
    txt += '\n';
  }

  const drifts = r.documentation_drifts || [];
  if (drifts.length) {
    txt += `${LINE}\nDOCUMENTATION DRIFT (${drifts.length})\n\n`;
    drifts.forEach(d => {
      txt += `  [${d.status}] ${d.doc_file} § ${d.section}\n`;
      txt += `    Code truth : ${d.code_truth}\n`;
      txt += `    Doc says   : ${d.doc_current}\n\n`;
    });
  }

  const regressions = r.regression_risks || [];
  if (regressions.length) {
    txt += `${LINE}\nREGRESSION RISKS\n`;
    regressions.forEach(r => { txt += `  • ${r}\n`; });
    txt += '\n';
  }

  const changes = r.recommended_changes || [];
  if (changes.length) {
    txt += `${LINE}\nRECOMMENDED CHANGES\n`;
    changes.forEach(c => { txt += `  • ${c}\n`; });
    txt += '\n';
  }

  txt += `${LINE}\nValidation: ${r.validation_results || 'N/A'}\n`;

  const bf = r.bug_fix;
  if (bf) {
    txt += `\n${LINE}\nBUG FIX DETAILS\n`;
    txt += `Issue #${bf.issue_number}: ${bf.issue_title}\n`;
    txt += `Root Cause: ${bf.root_cause}\n`;
    if (bf.changes_made?.length) {
      txt += `Proposed Changes (${bf.changes_made.length}):\n`;
      bf.changes_made.forEach(c => { txt += `  [${c.type}] ${c.file}: ${c.description}\n`; });
    }
    if (bf.tests_added?.length) txt += `Tests To Add:\n${bf.tests_added.map(t => `  • ${t}`).join('\n')}\n`;
    if (bf.potential_side_effects?.length) txt += `Potential Side Effects:\n${bf.potential_side_effects.map(s => `  • ${s}`).join('\n')}\n`;
  }

  const pr = r.pr_review;
  if (pr) {
    txt += `\n${LINE}\nPR REVIEW — PR #${pr.pr_number}: ${pr.pr_title}\n`;
    txt += `Files Changed  : ${pr.files_changed}\n`;
    txt += `Recommendation : ${(pr.recommendation || '').toUpperCase()}\n`;
    if (pr.summary) txt += `Summary: ${pr.summary}\n`;
    if (pr.missing_tests?.length) txt += `Missing Tests:\n${pr.missing_tests.map(t => `  • ${t}`).join('\n')}\n`;
    if (pr.potential_regressions?.length) txt += `Potential Regressions:\n${pr.potential_regressions.map(r => `  • ${r}`).join('\n')}\n`;
  }

  const det = r.pr_detective;
  if (det) {
    txt += `\n${LINE}\nPR DETECTIVE — PR #${det.pr_number}\n`;
    if (det.summary) txt += `${det.summary}\n`;
    if (det.direct_deps?.length) txt += `Direct Deps (${det.direct_deps.length}):\n${det.direct_deps.map(d => `  • ${d}`).join('\n')}\n`;
    if (det.indirect_deps?.length) txt += `Indirect Deps (${det.indirect_deps.length}):\n${det.indirect_deps.slice(0, 8).map(d => `  • ${d}`).join('\n')}\n`;
    if (det.affected_apis?.length) txt += `Affected APIs:\n${det.affected_apis.map(a => `  • ${a}`).join('\n')}\n`;
    if (det.missing_tests?.length) txt += `Missing Tests:\n${det.missing_tests.map(t => `  • ${t}`).join('\n')}\n`;
  }

  txt += `\n— Bob CodeGuard · IBM Bob 2.0\n`;
  return txt;
}

$btn.copyReport?.addEventListener('click', () => {
  if (!state.report) return;
  navigator.clipboard.writeText(buildReportText(state.report)).then(() => {
    $btn.copyReport.textContent = '✅ Copied!';
    setTimeout(() => { $btn.copyReport.innerHTML = '📋 Copy Report'; }, 2000);
  });
});

// ── Jobs View ─────────────────────────────────────────────────────────────────
$btn.refreshJobs?.addEventListener('click', refreshJobs);

async function refreshJobs() {
  const container = $('jobs-list');
  container.innerHTML = '<div class="empty-state">Loading…</div>';
  try {
    const res = await fetch('/api/jobs');
    const jobs = await res.json();
    if (!jobs.length) {
      container.innerHTML = '<div class="empty-state">No jobs yet. Start an analysis from the Dashboard.</div>';
      return;
    }
    container.innerHTML = jobs.map(j => `
      <div class="job-row" data-jobid="${j.job_id}">
        <div class="job-status-dot dot--${j.status}"></div>
        <div class="job-repo">${esc(j.repository)} <span style="color:var(--muted);font-weight:400">#${esc(j.ref)}</span></div>
        <div class="job-meta">${esc(j.mode)}</div>
        <div class="job-progress">${j.steps_done}/${j.steps_total} steps</div>
        <div class="job-meta" style="text-transform:capitalize">${esc(j.status)}</div>
      </div>
    `).join('');
    container.querySelectorAll('.job-row').forEach(row => {
      row.addEventListener('click', () => loadJob(row.dataset.jobid));
    });
  } catch (e) {
    container.innerHTML = `<div class="empty-state">Failed to load jobs: ${esc(e.message)}</div>`;
  }
}

async function loadJob(jobId) {
  // Switch to dashboard
  document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelector('[data-view="dashboard"]')?.classList.add('active');
  document.getElementById('view-dashboard')?.classList.add('active');

  closeStream();

  try {
    const res = await fetch(`/api/jobs/${jobId}`);
    const job = await res.json();
    showWorkflowPanel(job.repository, job.mode);
    renderWorkflowSteps(job.steps || []);

    if (job.status === 'done') {
      $('workflow-spinner').style.display = 'none';
      $('workflow-status-text').textContent = 'Analysis complete ✓';
      if (job.report) renderResults(job.report);
    } else if (job.status === 'error') {
      $('workflow-spinner').style.display = 'none';
      $('workflow-status-text').textContent = 'Analysis failed';
      showError(`Analysis failed: ${job.error || 'Unknown error'}`);
    } else if (job.status === 'running' || job.status === 'pending') {
      state.currentJobId = jobId;
      $('workflow-status-text').textContent = statusText(job.status);
      openStream(jobId);
    }
  } catch (e) {
    showError(`Failed to load job: ${e.message}`);
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function esc(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
function showError(msg) { $panels.error.textContent = msg; $panels.error.classList.remove('hidden'); }
function hideError() { $panels.error.classList.add('hidden'); }
function resetAnalyzeBtn() {
  $btn.analyze.disabled = false;
  $btn.analyze.innerHTML = '<span class="btn-icon">⚡</span> Analyze';
}
