const SERVERS = [
  { id: '186', name: '服务器 A (186)', url: 'http://192.168.0.186:8000' },
  { id: '34', name: '服务器 B (34)', url: 'http://192.168.0.34:8000' },
];

let currentServerUrl = '';
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

function renderJob(job) {
  const canCancel = ['queued', 'running'].includes(job.status);
  const canRetry = ['paused', 'failed', 'cancelled', 'completed_with_errors'].includes(job.status);
  const canDelete = !['queued', 'running', 'cancelling'].includes(job.status);
  const downloadHref = `${job._serverUrl || currentServerUrl || ''}/api/jobs/${encodeURIComponent(job.job_id)}/download`;
  const combos = job.combos || [];
  const key = previewKey(job);
  const openAttr = openPreviewKeys.has(key) ? ' open' : '';
  return `
    <article class="job">
      <div class="job-top">
        <div class="job-title-row">
          <strong>${escapeHtml(job.product_id || job.job_id)}</strong>
          ${job._server ? `<span class="server-tag">${escapeHtml(job._server)}</span>` : ''}
          <span class="server-tag">${escapeHtml(job.api_model || 'API')}</span>
        </div>
        <span class="badge badge-${escapeHtml(job.status)}">${escapeHtml(job.status)}</span>
      </div>
      <div class="meta">${escapeHtml(job.garment_name || '')} · ${escapeHtml(job.input_name || '')}</div>
      <div class="progress"><div style="width:${job.progress || 0}%"></div></div>
      <div class="meta">${escapeHtml(job.message || '')}</div>
      <div class="meta">完成：${job.completed_count || 0}/${job.total_combos || 0} · 失败：${job.failed_count || 0}</div>
      <div class="job-actions">
        ${canCancel ? `<button class="cancel-btn" data-action="cancel" data-job="${escapeHtml(job.job_id)}" data-server-url="${escapeHtml(job._serverUrl || '')}">取消</button>` : ''}
        ${canRetry ? `<button class="resume-btn" data-action="retry" data-job="${escapeHtml(job.job_id)}" data-server-url="${escapeHtml(job._serverUrl || '')}">重试未完成</button>` : ''}
        ${(job.completed_count || 0) > 0 ? `<a class="link-btn" href="${escapeHtml(downloadHref)}">下载 ZIP</a>` : ''}
        ${canDelete ? `<button class="delete-btn" data-action="delete" data-job="${escapeHtml(job.job_id)}" data-server-url="${escapeHtml(job._serverUrl || '')}">删除</button>` : ''}
      </div>
      ${job.error ? `<div class="meta error">${escapeHtml(job.error)}</div>` : ''}
      <details class="results-preview" data-preview-key="${escapeHtml(key)}"${openAttr}>
        <summary>结果预览（${job.completed_count || 0}/${job.total_combos || combos.length}）</summary>
        <div class="combo-grid">${combos.map(combo => renderCombo(job, combo)).join('')}</div>
      </details>
    </article>
  `;
}

async function refreshJobs() {
  rememberOpenPreviews();
  let allJobs = [];
  if (!currentServerUrl) {
    const results = await Promise.allSettled(
      SERVERS.map(server => fetchFromServer(server.url, '/api/jobs?engine=api').then(data => ({
        server: server.name,
        serverUrl: server.url,
        jobs: data.jobs || [],
      })))
    );
    for (const result of results) {
      if (result.status === 'fulfilled') {
        allJobs.push(...result.value.jobs.map(job => ({ ...job, _server: result.value.server, _serverUrl: result.value.serverUrl })));
      }
    }
  } else {
    const server = SERVERS.find(item => item.url === currentServerUrl);
    try {
      const data = await api('/api/jobs?engine=api');
      allJobs = (data.jobs || []).map(job => ({ ...job, _server: server?.name || currentServerUrl, _serverUrl: currentServerUrl }));
    } catch {
      allJobs = [];
    }
  }
  allJobs.sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
  document.getElementById('jobsList').innerHTML = allJobs.length
    ? allJobs.map(renderJob).join('')
    : '<div class="empty">还没有 API 并行任务。</div>';
}

async function loadBasics() {
  const [defaults, models] = await Promise.all([api('/api/defaults'), api('/api/models')]);
  const select = document.getElementById('apiModel');
  select.innerHTML = (models.models || []).map(model => `<option value="${escapeHtml(model.id)}">${escapeHtml(model.label)}</option>`).join('');
  select.value = defaults.default_api_model || (models.models || [])[0]?.id || '';
  document.getElementById('apiHealth').textContent = `任务并发 ${defaults.max_active_jobs}，API 总并发 ${defaults.max_api_concurrency}`;
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
    if (!images.length) throw new Error('请选择包含商品图的文件夹');
    const colorsTxt = document.getElementById('colorsTxtFile').files[0];
    if (!colorsTxt) throw new Error('请上传颜色定义 TXT 文件');

    const folderName = images[0].webkitRelativePath?.split('/')[0] || '';
    const form = new FormData();
    form.append('product_id', folderName);
    form.append('garment_name', document.getElementById('garmentName').value || '');
    form.append('api_model', document.getElementById('apiModel').value);
    form.append('prompt_template', document.getElementById('promptTemplate').value || '');
    form.append('manual_colors_text', normalizeManualColors(document.getElementById('manualColors').value));
    form.append('engine', 'api');
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
    status.textContent = `已提交 API 任务 ${folderName || result.job_id}`;
    await refreshJobs();
  } catch (err) {
    status.textContent = `提交失败：${err.message || '未知错误'}`;
    alert(err.message || '提交失败');
  } finally {
    btn.disabled = false;
    btn.textContent = '开始 API 并行改色';
  }
}

async function mutate(action, jobId, serverUrl, button) {
  const config = {
    cancel: { method: 'POST', path: `/api/jobs/${encodeURIComponent(jobId)}/cancel` },
    retry: { method: 'POST', path: `/api/jobs/${encodeURIComponent(jobId)}/retry` },
    delete: { method: 'DELETE', path: `/api/jobs/${encodeURIComponent(jobId)}` },
  }[action];
  if (!config) return;
  if (action === 'delete' && !confirm('确定删除这个任务和输出文件吗？')) return;
  button.disabled = true;
  try {
    const baseUrl = serverUrl || currentServerUrl || '';
    const resp = await fetch(`${baseUrl}${config.path}`, { method: config.method });
    if (!resp.ok) throw new Error(await errorText(resp));
    await refreshJobs();
  } catch (err) {
    alert(err.message || '操作失败');
    button.disabled = false;
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
        keys: data.available_keys || {},
      })))
    );
    statusEl.textContent = results.map(result => {
      if (result.status !== 'fulfilled') return '服务器离线';
      const keys = Object.entries(result.value.keys).map(([model, count]) => `${model}:${count}`).join(' ');
      return `${result.value.name}: 运行${result.value.running} 排队${result.value.queued} ${keys}`;
    }).join(' | ');
    return;
  }
  try {
    const info = await api('/api/health');
    const keys = Object.entries(info.available_keys || {}).map(([model, count]) => `${model}:${count}`).join(' ');
    statusEl.textContent = `运行中: ${info.running_jobs || 0} | 排队中: ${info.queued_jobs || 0} | key ${keys || '无'}`;
  } catch {
    statusEl.textContent = '无法连接';
  }
}

document.getElementById('submitBtn').addEventListener('click', submitJob);
document.getElementById('refreshBtn').addEventListener('click', refreshJobs);
document.getElementById('serverSelect').addEventListener('change', async event => {
  currentServerUrl = event.target.value;
  await refreshServerStatus();
  await refreshJobs();
});
document.getElementById('jobsList').addEventListener('toggle', event => {
  if (event.target && event.target.classList && event.target.classList.contains('results-preview')) {
    setPreviewOpenState(event.target);
  }
}, true);
document.getElementById('jobsList').addEventListener('click', event => {
  const button = event.target.closest('button[data-action]');
  if (!button) return;
  mutate(button.dataset.action, button.dataset.job, button.dataset.serverUrl || '', button);
});

loadBasics();
refreshServerStatus();
refreshJobs();
setInterval(() => {
  refreshServerStatus();
  refreshJobs();
}, 3000);
