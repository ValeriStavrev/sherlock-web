const tabs = [...document.querySelectorAll('.mode-tab')];
const panels = [...document.querySelectorAll('[data-mode-panel]')];
const errorBox = document.getElementById('errorBox');
let activeMode = 'username';
let pollTimer = null;
let scanMode = 'fast';

const state = {
  username: {form: document.getElementById('usernameForm'), input: document.getElementById('username'), button: document.getElementById('usernameBtn'), results: document.getElementById('usernameResults')},
  email: {form: document.getElementById('emailForm'), input: document.getElementById('email'), button: document.getElementById('emailBtn'), results: document.getElementById('emailResults')}
};

function showError(message) { errorBox.textContent = message; errorBox.classList.remove('hidden'); }
function clearError() { errorBox.textContent = ''; errorBox.classList.add('hidden'); }
function escapeHtml(value) { return String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c])); }
function escapeAttr(value) { return escapeHtml(value); }
function setButton(mode, text, disabled) { const btn = state[mode].button; btn.disabled = disabled; btn.querySelector('span').textContent = text; }

function setMode(mode) {
  activeMode = mode;
  clearError();
  clearTimeout(pollTimer);
  tabs.forEach(tab => { const active = tab.dataset.mode === mode; tab.classList.toggle('active', active); tab.setAttribute('aria-selected', String(active)); });
  panels.forEach(panel => panel.classList.toggle('hidden', panel.dataset.modePanel !== mode));
  state.username.results.classList.add('hidden');
  state.email.results.classList.add('hidden');
  state[mode].input.focus();
}
tabs.forEach(tab => tab.addEventListener('click', () => setMode(tab.dataset.mode)));

const scanModeButtons = [...document.querySelectorAll('[data-scan-mode]')];
scanModeButtons.forEach(button => button.addEventListener('click', () => {
  scanMode = button.dataset.scanMode;
  scanModeButtons.forEach(b => b.classList.toggle('active', b.dataset.scanMode === scanMode));
}));

function resetUsername(username) {
  const r = state.username.results;
  r.classList.remove('hidden');
  document.getElementById('usernameResultTitle').textContent = `@${username}`;
  document.getElementById('usernameResultCount').textContent = 'SCANNING';
  document.getElementById('usernameGrid').innerHTML = '';
  document.getElementById('usernameEmpty').classList.add('hidden');
  document.getElementById('usernameLog').classList.add('hidden');
  document.getElementById('usernameProgress').classList.remove('hidden');
}
function renderUsername(results) {
  const grid = document.getElementById('usernameGrid');
  grid.innerHTML = results.map(item => `<a class="result-card" href="${escapeAttr(item.url)}" target="_blank" rel="noopener noreferrer"><div class="result-site"><strong>${escapeHtml(item.source)}</strong><span>${escapeHtml(item.url)}</span></div><span class="result-arrow">Open</span></a>`).join('');
  document.getElementById('usernameEmpty').classList.toggle('hidden', results.length !== 0);
}
function renderLogs(logs = []) { const box = document.getElementById('usernameLog'); if (!logs.length) { box.classList.add('hidden'); return; } box.textContent = logs.join('\n'); box.classList.remove('hidden'); }

function renderEmail(data) {
  const dns = data.dns || {};
  const accounts = data.account_results || [];
  const breaches = data.breach_results || [];
  const accountFound = data.account_found || 0;
  const breachCount = data.breach_count || 0;
  const status = breachCount ? `${breachCount} BREACH${breachCount === 1 ? '' : 'ES'} FOUND` : (data.source_errors?.length ? 'PARTIAL RESULTS' : 'NO BREACH FOUND');
  document.getElementById('emailProgress').classList.add('hidden');
  document.getElementById('emailResultCount').textContent = status;
  const summary = document.getElementById('emailSummary');
  summary.classList.remove('hidden');
  summary.innerHTML = `<div class="email-block"><div class="section-kicker">EMAIL</div><strong>${escapeHtml(data.email)}</strong></div><div class="email-block"><div class="section-kicker">DOMAIN</div><strong>${escapeHtml(dns.domain || data.domain || '-')}</strong><span class="dns-ok">${dns.mx_valid ? 'MX valid' : 'No MX result'}</span>${dns.mx?.length ? `<small>${escapeHtml(dns.mx.join(', '))}</small>` : ''}</div><div class="email-block"><div class="section-kicker">CANDIDATE USERNAME</div><strong>@${escapeHtml(data.candidate_username || '')}</strong><span>Candidate only - not identity proof. Use Username mode separately if you want to investigate it.</span></div>`;

  const findingsBox = document.getElementById('emailFindings');
  const renderRows = (items, emptyText) => items.length ? items.map(f => {
    const link = f.url && /^https?:\/\//i.test(f.url) ? `<a href="${escapeAttr(f.url)}" target="_blank" rel="noopener noreferrer">Open</a>` : '';
    const label = f.status === 'found' ? 'FOUND' : f.status === 'not_found' ? 'NOT FOUND' : 'UNAVAILABLE';
    return `<div class="email-finding"><div><strong>${escapeHtml(f.source)}</strong><span>${escapeHtml(f.details || '')}</span></div><div class="finding-side"><b class="finding-status ${f.status}">${label}</b>${link}</div></div>`;
  }).join('') : `<div class="empty">${escapeHtml(emptyText)}</div>`;

  findingsBox.innerHTML = `
    <div class="email-section-title">EMAIL ACCOUNT SIGNALS <span>${accountFound} FOUND</span></div>
    ${renderRows(accounts, 'No supported account association was returned by the email-account checks.')}
    <div class="email-section-title">BREACH EXPOSURE <span>${breachCount} FOUND</span></div>
    ${renderRows(breaches, breachCount ? '' : 'No breach was returned by the configured breach sources. This does not prove the address has never appeared in a breach.')}`;

  const warning = document.getElementById('emailSourcesError');
  if (data.source_errors?.length) { warning.textContent = `Some sources were unavailable: ${data.source_errors.join(' | ')}`; warning.classList.remove('hidden'); } else warning.classList.add('hidden');
}

async function pollJob(jobId, mode) {
  clearTimeout(pollTimer);
  try {
    const res = await fetch(`/api/search/${encodeURIComponent(jobId)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Search expired.');
    if (mode === 'username') {
      document.getElementById('usernameProgressText').textContent = data.message || 'Checking sites.';
      renderLogs(data.logs || []);
    } else {
      document.getElementById('emailProgressText').textContent = data.message || 'Checking email OSINT.';
      document.getElementById('emailResultTitle').textContent = data.email || 'Email';
    }
    if (data.status === 'done') {
      if (mode === 'username') { document.getElementById('usernameProgress').classList.add('hidden'); document.getElementById('usernameResultCount').textContent = `${data.count} FOUND`; renderUsername(data.results || []); }
      else renderEmail(data);
      setButton(mode, mode === 'username' ? 'Search' : 'Scan', false); return;
    }
    if (data.status === 'error') { state[mode].results.querySelector('.progress-card').classList.add('hidden'); showError(data.message || 'The scan failed.'); setButton(mode, mode === 'username' ? 'Search' : 'Scan', false); return; }
    pollTimer = setTimeout(() => pollJob(jobId, mode), 1200);
  } catch (error) { state[mode].results.querySelector('.progress-card').classList.add('hidden'); showError(error.message || 'Something went wrong.'); setButton(mode, mode === 'username' ? 'Search' : 'Scan', false); }
}

async function startScan(mode, value) {
  clearError(); clearTimeout(pollTimer);
  state.username.results.classList.add('hidden'); state.email.results.classList.add('hidden');
  state[mode].results.classList.remove('hidden');
  if (mode === 'username') resetUsername(value);
  else { document.getElementById('emailResultTitle').textContent = value; document.getElementById('emailResultCount').textContent = 'SCANNING'; document.getElementById('emailProgress').classList.remove('hidden'); document.getElementById('emailSummary').classList.add('hidden'); document.getElementById('emailFindings').innerHTML = ''; document.getElementById('emailSourcesError').classList.add('hidden'); }
  setButton(mode, mode === 'username' ? 'Scanning' : 'Scanning', true);
  try {
    const endpoint = mode === 'username' ? '/api/search' : '/api/email-search';
    const body = mode === 'username' ? {username: value, scan_mode: scanMode} : {email: value};
    const res = await fetch(endpoint, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Could not start scan.');
    pollJob(data.job_id, mode);
  } catch (error) { state[mode].results.querySelector('.progress-card').classList.add('hidden'); showError(error.message || 'Could not start scan.'); setButton(mode, mode === 'username' ? 'Search' : 'Scan', false); }
}

state.username.form.addEventListener('submit', e => { e.preventDefault(); startScan('username', state.username.input.value.trim()); });
state.email.form.addEventListener('submit', e => { e.preventDefault(); startScan('email', state.email.input.value.trim()); });
