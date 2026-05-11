const SERVERS = [
  { id: '186', name: '服务器 A (186)', url: 'http://192.168.0.186:8000' },
  { id: '34', name: '服务器 B (34)', url: 'http://192.168.0.34:8000' },
];

let currentServerUrl = '';
let selectedJobIds = new Set();
const openPreviewKeys = new Set();

async function errorText(resp) {
  try {
    const data = await resp.json();
    return data.detail || JSON.stringify(data);
  } catch {
    return await resp.text();
  }
}

async function fetchFromServer(baseUrl, url, options = {}) {
  const resp = await fetch(baseUrl + url, options);
  if (!resp.ok) throw new Error(await errorText(resp));
  return resp.json();
}

async function api(url, options = {}) {
  return fetchFromServer(currentServerUrl || '', url, options);
}

async function pickBestServer() {
  const results = await Promise.allSettled(
    SERVERS.map(server => fetchFromServer(server.url, '/api/health').then(data => ({
      url: server.url,
      name: server.name,
      busy: (data.running_jobs || 0) + (data.queued_jobs || 0),
    })))
  );
  const available = results
    .filter(result => result.status === 'fulfilled')
    .map(result => result.value)
    .sort((a, b) => a.busy - b.busy);
  if (!available.length) throw new Error('所有服务器均不可用');
  return available[0];
}

function escapeHtml(text) {
  return String(text || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function renderDefaultTemplates(templates) {
  const preview = document.getElementById('defaultPromptPreview');
  preview.innerHTML = Object.entries(templates || {}).map(([kind, text]) => `
    <div class="template-block">
      <div class="template-chip">${escapeHtml(kind)}</div>
      <pre>${escapeHtml(text)}</pre>
    </div>
  `).join('');
}

function normalizeManualColors(text) {
  return String(text || '')
    .split(/\r?\n/)
    .map(line => line.trim().replace('：', ':'))
    .filter(Boolean)
    .join('\n');
}

function fileHref(job, filename) {
  const baseUrl = job._serverUrl || currentServerUrl || '';
  return `${baseUrl}/api/jobs/${encodeURIComponent(job.job_id)}/files/${encodeURIComponent(filename)}`;
}

function previewKey(job) {
  return `${job._serverUrl || currentServerUrl || ''}:${job.job_id}`;
}

function rememberOpenPreviews() {
  document.querySelectorAll('.results-preview').forEach(details => {
    setPreviewOpenState(details);
  });
}

function setPreviewOpenState(details) {
  const key = details.dataset.previewKey;
  if (!key) return;
  if (details.open) openPreviewKeys.add(key);
  else openPreviewKeys.delete(key);
}

function renderCombo(job, combo) {
  const files = (combo.output_files || []).map((filename, index) => {
    const href = fileHref(job, filename);
    return `
      <a class="result-thumb-link" href="${escapeHtml(href)}" target="_blank">
        <img class="result-thumb" src="${escapeHtml(href)}" alt="结果 ${index + 1}" loading="lazy" />
      </a>
    `;
  }).join('');
  const fallback = combo.actual_engine === 'comfyui_fallback' ? '<span class="server-tag">本地兜底</span>' : '';
  return `
    <div class="combo">
      <div class="combo-top">
        <div class="combo-name">
          <span class="swatch" style="background:${escapeHtml(combo.hex)}"></span>
          <span>${escapeHtml(combo.image_name)} / ${escapeHtml(combo.color_name)}</span>
          ${fallback}
        </div>
        <span class="badge badge-${escapeHtml(combo.status)}">${escapeHtml(combo.status)}</span>
      </div>
      <div class="meta">${escapeHtml(combo.hex)}${combo.error ? ` · ${escapeHtml(combo.error)}` : ''}</div>
      ${files ? `<div class="result-grid">${files}</div>` : ''}
    </div>
  `;
}

function renderPreview(job) {
  const combos = job.combos || [];
  if (!combos.length) return '';
  const key = previewKey(job);
  const openAttr = openPreviewKeys.has(key) ? ' open' : '';
  return `
    <details class="results-preview" data-preview-key="${escapeHtml(key)}"${openAttr}>
      <summary>结果预览（${job.completed_count || 0}/${job.total_combos || combos.length}）</summary>
      <div class="combo-grid">${combos.map(combo => renderCombo(job, combo)).join('')}</div>
    </details>
  `;
}

function jobCard(job) {
  const div = document.createElement('div');
  div.className = 'job';
  const canCancel = ['queued', 'running'].includes(job.status);
  const canRetry = ['paused', 'failed', 'cancelled', 'completed_with_errors'].includes(job.status);
  const canDelete = !['queued', 'running', 'cancelling'].includes(job.status);
  const serverLabel = job._server ? `<span class="server-tag">${escapeHtml(job._server)}</span>` : '';
  const checked = selectedJobIds.has(job.job_id) ? 'checked' : '';
  const downloadHref = `${job._serverUrl || currentServerUrl || ''}/api/jobs/${encodeURIComponent(job.job_id)}/download`;
  div.innerHTML = `
    <div class="job-top">
      <div class="job-title-row">
        <input type="checkbox" class="job-checkbox" data-job-id="${escapeHtml(job.job_id)}" data-server-url="${escapeHtml(job._serverUrl || '')}" ${checked} onchange="toggleJobSelect(this)" />
        <strong>${escapeHtml(job.product_id || job.job_id)}</strong>
        ${serverLabel}
      </div>
      <span class="badge badge-${escapeHtml(job.status)}">${escapeHtml(job.status)}</span>
    </div>
    <div class="meta">${escapeHtml(job.garment_name || '')} · ${escapeHtml(job.input_name || '')}</div>
    <div class="progress"><div style="width:${job.progress || 0}%"></div></div>
    <div class="meta">${escapeHtml(job.message || '')}</div>
    <div class="meta">进度：${job.progress || 0}% · 完成：${job.completed_count || 0}/${job.total_combos || 0} · 失败：${job.failed_count || 0}</div>
    <div class="job-actions">
      ${canCancel ? `<button class="cancel-btn" onclick="cancelJob('${escapeHtml(job.job_id)}', '${escapeHtml(job._serverUrl || '')}', this)">取消任务</button>` : ''}
      ${canRetry ? `<button class="resume-btn" onclick="retryJob('${escapeHtml(job.job_id)}', '${escapeHtml(job._serverUrl || '')}', this)">重试未完成</button>` : ''}
      ${(job.completed_count || 0) > 0 ? `<a class="link-btn" href="${escapeHtml(downloadHref)}">下载结果</a>` : ''}
      ${canDelete ? `<button class="delete-btn" onclick="deleteJob('${escapeHtml(job.job_id)}', '${escapeHtml(job._serverUrl || '')}', this)">删除</button>` : ''}
    </div>
    ${job.error ? `<div class="meta error">${escapeHtml(job.error)}</div>` : ''}
    ${renderPreview(job)}
  `;
  return div;
}

async function mutateJob(jobId, serverUrl, path, method, btn) {
  btn.disabled = true;
  try {
    const baseUrl = serverUrl || currentServerUrl || '';
    const resp = await fetch(`${baseUrl}${path}`, { method });
    if (!resp.ok) throw new Error(await errorText(resp));
    await refreshJobs();
  } catch (err) {
    alert(err.message || '操作失败');
    btn.disabled = false;
  }
}

async function cancelJob(jobId, serverUrl, btn) {
  if (!confirm('确定要取消这个任务吗？')) return;
  await mutateJob(jobId, serverUrl, `/api/jobs/${encodeURIComponent(jobId)}/cancel`, 'POST', btn);
}

async function retryJob(jobId, serverUrl, btn) {
  await mutateJob(jobId, serverUrl, `/api/jobs/${encodeURIComponent(jobId)}/retry`, 'POST', btn);
}

async function deleteJob(jobId, serverUrl, btn) {
  if (!confirm('确定要删除这个任务吗？')) return;
  await mutateJob(jobId, serverUrl, `/api/jobs/${encodeURIComponent(jobId)}`, 'DELETE', btn);
  selectedJobIds.delete(jobId);
}

function toggleJobSelect(checkbox) {
  if (checkbox.checked) selectedJobIds.add(checkbox.dataset.jobId);
  else selectedJobIds.delete(checkbox.dataset.jobId);
  updateBatchButtons();
}

function selectAll() {
  document.querySelectorAll('.job-checkbox').forEach(checkbox => {
    checkbox.checked = true;
    selectedJobIds.add(checkbox.dataset.jobId);
  });
  updateBatchButtons();
}

function clearSelection() {
  document.querySelectorAll('.job-checkbox').forEach(checkbox => { checkbox.checked = false; });
  selectedJobIds.clear();
  updateBatchButtons();
}

function updateBatchButtons() {
  const batchBar = document.getElementById('batchActions');
  if (!batchBar) return;
  batchBar.style.display = selectedJobIds.size > 0 ? 'flex' : 'none';
  document.getElementById('selectedCount').textContent = `已选 ${selectedJobIds.size} 项`;
}

async function deleteSelected() {
  if (!selectedJobIds.size) return;
  if (!confirm(`确定要删除选中的 ${selectedJobIds.size} 个任务吗？`)) return;
  const byServer = {};
  document.querySelectorAll('.job-checkbox:checked').forEach(checkbox => {
    const serverUrl = checkbox.dataset.serverUrl || '';
    byServer[serverUrl] = byServer[serverUrl] || [];
    byServer[serverUrl].push(checkbox.dataset.jobId);
  });
  const btn = document.getElementById('batchDeleteBtn');
  btn.disabled = true;
  try {
    for (const [serverUrl, jobIds] of Object.entries(byServer)) {
      const baseUrl = serverUrl || currentServerUrl || '';
      const resp = await fetch(`${baseUrl}/api/jobs/batch-delete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_ids: jobIds }),
      });
      if (!resp.ok) throw new Error(await errorText(resp));
    }
    selectedJobIds.clear();
    await refreshJobs();
  } catch (err) {
    alert(err.message || '批量删除失败');
  } finally {
    btn.disabled = false;
    updateBatchButtons();
  }
}

async function refreshJobs() {
  rememberOpenPreviews();
  let allJobs = [];
  if (!currentServerUrl) {
    const results = await Promise.allSettled(
      SERVERS.map(server => fetchFromServer(server.url, '/api/jobs?engine=comfyui').then(data => ({
        server: server.name,
        serverUrl: server.url,
        jobs: data.jobs || [],
      })))
    );
    for (const result of results) {
      if (result.status === 'fulfilled') {
        for (const job of result.value.jobs) {
          job._server = result.value.server;
          job._serverUrl = result.value.serverUrl;
          allJobs.push(job);
        }
      }
    }
  } else {
    const server = SERVERS.find(item => item.url === currentServerUrl);
    try {
      const data = await api('/api/jobs?engine=comfyui');
      allJobs = (data.jobs || []).map(job => ({ ...job, _server: server?.name || currentServerUrl, _serverUrl: currentServerUrl }));
    } catch {
      allJobs = [];
    }
  }
  allJobs.sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
  const list = document.getElementById('jobsList');
  list.innerHTML = '';
  if (!allJobs.length) {
    list.innerHTML = '<div class="empty">还没有本地任务。</div>';
  } else {
    allJobs.forEach(job => list.appendChild(jobCard(job)));
  }
  updateBatchButtons();
}

async function loadDefaults() {
  const defaults = await api('/api/defaults');
  renderDefaultTemplates(defaults.default_prompt_templates || {});
  document.getElementById('guidance').value = defaults.guidance;
  document.getElementById('steps').value = defaults.steps;
  document.getElementById('steps8').value = defaults.steps_8;
  document.getElementById('targetWidth').value = defaults.target_width;
  document.getElementById('targetHeight').value = defaults.target_height;
}

async function submitJob() {
  const btn = document.getElementById('submitBtn');
  const status = document.getElementById('submitStatus');
  btn.disabled = true;
  btn.textContent = '提交中...';
  try {
    status.textContent = '提交中...';
    const files = Array.from(document.getElementById('imageFiles').files || []);
    const images = files.filter(file => file.type.startsWith('image/'));
    if (!images.length) throw new Error('请先选择包含商品图的文件夹');
    const colorsTxt = document.getElementById('colorsTxtFile').files[0];
    if (!colorsTxt) throw new Error('请上传颜色定义 TXT 文件');

    const folderName = images[0].webkitRelativePath?.split('/')[0] || '';
    const form = new FormData();
    form.append('product_id', folderName);
    form.append('garment_name', document.getElementById('garmentName').value || '');
    form.append('prompt_template', document.getElementById('promptTemplate').value || '');
    form.append('guidance', document.getElementById('guidance').value);
    form.append('steps', document.getElementById('steps').value);
    form.append('steps_8', document.getElementById('steps8').value);
    form.append('target_width', document.getElementById('targetWidth').value);
    form.append('target_height', document.getElementById('targetHeight').value);
    form.append('enable_lora', false);
    form.append('enable_8_step_lora', false);
    form.append('engine', 'comfyui');
    form.append('manual_colors_text', normalizeManualColors(document.getElementById('manualColors').value));
    form.append('colors_txt', colorsTxt);
    images.forEach(file => form.append('images', file));

    let submitUrl;
    if (currentServerUrl) {
      submitUrl = `${currentServerUrl}/api/jobs`;
    } else {
      const best = await pickBestServer();
      submitUrl = `${best.url}/api/jobs`;
      status.textContent = `分配到 ${best.name}（负载最低）...`;
    }
    const resp = await fetch(submitUrl, { method: 'POST', body: form });
    if (!resp.ok) throw new Error(await errorText(resp));
    const result = await resp.json();
    status.textContent = `已提交任务 ${folderName || result.job_id}`;
    await refreshJobs();
  } catch (err) {
    status.textContent = `提交失败：${err.message || '未知错误'}`;
    alert(err.message || '提交失败');
  } finally {
    btn.disabled = false;
    btn.textContent = '开始本地改色';
  }
}

async function refreshServerStatus() {
  const statusEl = document.getElementById('serverStatus');
  if (!currentServerUrl) {
    const results = await Promise.allSettled(
      SERVERS.map(server => fetchFromServer(server.url, '/api/health').then(data => ({
        name: server.name,
        running: data.running_jobs || 0,
        queued: data.queued_jobs || 0,
      })))
    );
    statusEl.textContent = results.map(result => (
      result.status === 'fulfilled'
        ? `${result.value.name}: 运行${result.value.running} 排队${result.value.queued}`
        : '服务器离线'
    )).join(' | ');
    return;
  }
  try {
    const info = await api('/api/health');
    statusEl.textContent = `运行中: ${info.running_jobs || 0} | 排队中: ${info.queued_jobs || 0}`;
  } catch {
    statusEl.textContent = '无法连接';
  }
}

document.getElementById('submitBtn').addEventListener('click', submitJob);
document.getElementById('refreshBtn').addEventListener('click', refreshJobs);
document.getElementById('jobsList').addEventListener('toggle', event => {
  if (event.target && event.target.classList && event.target.classList.contains('results-preview')) {
    setPreviewOpenState(event.target);
  }
}, true);
document.getElementById('serverSelect').addEventListener('change', async event => {
  currentServerUrl = event.target.value;
  await refreshServerStatus();
  await refreshJobs();
});

loadDefaults();
refreshServerStatus();
refreshJobs();
setInterval(() => {
  refreshJobs();
  refreshServerStatus();
}, 3000);
