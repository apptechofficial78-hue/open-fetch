const form = document.querySelector('#download');
const input = document.querySelector('#media-url');
const inputRow = document.querySelector('#url-row');
const message = document.querySelector('#form-message');
const clipboardButton = document.querySelector('#clipboard-button');
const submitButton = form.querySelector('.submit-button');
const modeButtons = [...document.querySelectorAll('.mode-button')];
const audioOptions = document.querySelector('#audio-options');
const audioFormat = document.querySelector('#audio-format');
const themeToggle = document.querySelector('#theme-toggle');
const historySection = document.querySelector('#recent-downloads');
const historyBody = document.querySelector('#download-history');
const RESOLVER_API = '/api/resolve';
let downloadMode = 'video';
let downloadHistory = [];

try { downloadHistory = JSON.parse(localStorage.getItem('openfetch-history') || '[]'); } catch { downloadHistory = []; }

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem('openfetch-theme', theme);
  themeToggle.textContent = theme === 'dark' ? '☀' : '☾';
  themeToggle.setAttribute('aria-label', theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme');
}
setTheme(localStorage.getItem('openfetch-theme') || 'light');
themeToggle.addEventListener('click', () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));

function updateClipboardButton() {
  if (!input.value.trim()) {
    if (navigator.clipboard && window.isSecureContext) {
      clipboardButton.textContent = '📋 Paste';
      clipboardButton.dataset.action = 'paste';
    } else {
      clipboardButton.hidden = true;
    }
  } else {
    clipboardButton.textContent = '✕ Clear';
    clipboardButton.dataset.action = 'clear';
  }
}

clipboardButton.addEventListener('click', async () => {
  if (clipboardButton.dataset.action === 'clear') {
    input.value = '';
    inputRow.classList.remove('invalid');
    input.focus();
  } else {
    try { input.value = await navigator.clipboard.readText(); input.dispatchEvent(new Event('input')); }
    catch { message.textContent = 'Clipboard access is unavailable. Paste the link manually.'; message.classList.add('show'); }
  }
  updateClipboardButton();
});
input.addEventListener('input', () => {
  updateClipboardButton();
  if (inputRow.classList.contains('invalid')) {
    inputRow.classList.remove('invalid');
  }
});
updateClipboardButton();

modeButtons.forEach(button => button.addEventListener('click', () => {
  downloadMode = button.dataset.mode;
  modeButtons.forEach(item => {
    const active = item === button;
    item.classList.toggle('active', active);
    item.setAttribute('aria-pressed', String(active));
  });
  audioOptions.hidden = downloadMode !== 'audio';
}));

function validHttpUrl(value) {
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url : null; }
  catch { return null; }
}

function showMessage(text, state = '') {
  message.className = `form-message show${state ? ` ${state}` : ''}`;
  message.replaceChildren(document.createTextNode(text));
}

function formatResult(result, sourceUrl) {
  const downloadUrl = result.download_url || result.url;
  const title = result.title || result.filename || 'media';
  const extension = result.extension || (result.filename ? result.filename.split('.').pop() : '');
  const isHls = result.stream_type === 'hls' || result.is_hls === true || result.status === 'hls';
  const picker = result.picker || result.results;
  if (picker && Array.isArray(picker) && picker.length) {
    return { kind: 'picker', items: picker.map(item => ({ url: item.url || item, title: item.title || item.filename || 'Download' })) };
  }
  if (downloadUrl) return { kind: isHls ? 'hls' : 'download', url: downloadUrl, title, extension, sourceUrl };
  return null;
}

function addHistory(item) {
  downloadHistory.unshift({ ...item, id: `${Date.now()}-${Math.random()}`, createdAt: new Date().toISOString() });
  downloadHistory = downloadHistory.slice(0, 8);
  localStorage.setItem('openfetch-history', JSON.stringify(downloadHistory));
  renderHistory();
}

function renderHistory() {
  historySection.hidden = downloadHistory.length === 0;
  historyBody.replaceChildren();
  downloadHistory.forEach(item => {
    const row = document.createElement('tr');
    const title = document.createElement('td'); title.textContent = item.title;
    const type = document.createElement('td'); type.textContent = item.extension || item.type || 'media';
    const result = document.createElement('td'); result.textContent = item.type || 'download';
    const action = document.createElement('td');
    if (item.url) { const link = document.createElement('a'); link.href = item.url; link.target = '_blank'; link.rel = 'noopener'; link.textContent = 'Open'; action.append(link); }
    row.append(title, type, result, action);
    historyBody.append(row);
  });
}
renderHistory();

function renderResult(normalized) {
  message.replaceChildren();
  if (normalized.kind === 'picker') {
    message.className = 'form-message show success';
    message.textContent = 'Multiple results found:';
    normalized.items.forEach((item, index) => {
      const link = document.createElement('a'); link.href = item.url; link.target = '_blank'; link.rel = 'noopener'; link.textContent = ` ${item.title || `Option ${index + 1}`} `; message.append(link);
      addHistory({ title: item.title || 'media', url: item.url, extension: '', type: 'picker result' });
    });
    return;
  }

  const link = document.createElement('a');
  link.href = normalized.url; link.target = '_blank'; link.rel = 'noopener';
  link.textContent = normalized.kind === 'hls' ? 'Open HLS playlist / download file' : `Download ${normalized.title}${normalized.extension ? `.${normalized.extension}` : ''}`;
  if (normalized.kind === 'hls') message.textContent = 'HLS stream ready: ';
  else message.textContent = 'Ready: ';
  message.append(link); message.className = 'form-message show success';
  addHistory({ title: normalized.title, url: normalized.url, extension: normalized.extension || '', type: normalized.kind === 'hls' ? 'HLS stream' : 'download' });
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  const value = input.value.trim();
  const url = validHttpUrl(value);
  if (!url) {
    inputRow.classList.add('invalid'); showMessage('Enter a valid public HTTP or HTTPS link.', 'error'); input.focus(); return;
  }

  inputRow.classList.remove('invalid');
  submitButton.classList.add('loading'); submitButton.disabled = true;
  showMessage('Analyzing link…');

  try {
    const directExtension = url.pathname.split('.').pop()?.toLowerCase
    if (directExtension && ['mp4','webm','mkv','mov','m4v','mp3','m4a','aac','ogg','opus','flac','wav'].includes(directExtension)) {
      const normalized = { kind: 'download', url: url.toString(), title: url.pathname.split('/').pop().replace(/\.[^.]+$/, '') || 'media', extension: directExtension, sourceUrl: url.toString() };
      renderResult(normalized); return;
    }

    const response = await fetch(RESOLVER_API, {
      method: 'POST', headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: url.toString(), downloadMode, audioFormat: audioFormat.value, videoQuality: '1080', filenameStyle: 'pretty' })
    });
    const text = await response.text();
    let result;
    try { result = JSON.parse(text); } catch { throw new Error(`Resolver returned an invalid response (HTTP ${response.status}).`); }
    if (!response.ok) {
      const error = result.error;
      throw new Error(error?.message || error?.code || result.detail || `Resolver request failed (HTTP ${response.status}).`);
    }

    let normalized;
    if (result.status === 'redirect' && result.url && !result.download_url) normalized = { kind: 'download', url: result.url, title: result.filename?.replace(/\.[^.]+$/, '') || 'media', extension: result.filename?.split('.').pop() || '', sourceUrl: url.toString() };
    else normalized = formatResult(result, url.toString());
    if (!normalized && result.status === 'picker') normalized = { kind: 'picker', items: result.picker.map(item => ({ url: item.url, title: item.filename || item.type || 'Download' })) };
    if (!normalized) throw new Error(result.error?.message || result.error?.code || 'No usable media result was returned.');
    renderResult(normalized);
  } catch (error) {
    showMessage(`Resolver error: ${error.message || 'Request failed'}`, 'error');
  } finally {
    submitButton.classList.remove('loading'); submitButton.disabled = false;
  }
});
