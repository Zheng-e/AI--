const SERVERS = [
  { id: '186', name: '服务器 A (186)', url: 'http://192.168.0.186:8000' },
  { id: '34', name: '服务器 B (34)', url: 'http://192.168.0.34:8000' },
];

let currentServerUrl = '';  // empty = auto (nginx)

async function fetchFromServer(baseUrl, url, options = {}) {
  const fullUrl = baseUrl + url;
  const resp = await fetch(fullUrl, options);
  if (!resp.ok) {
    throw new Error(await resp.text());
  }
  return resp.json();
}

async function api(url, options = {}) {
  const baseUrl = currentServerUrl || '';
  const resp = await fetch(baseUrl + url, options);
  if (!resp.ok) {
    throw new Error(await resp.text());
  }
  return resp.json();
}

function escapeHtml(text) {
  return String(text || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function defaultTemplateText(kind) {
  if (kind === 'bottom') {
    return `Recolor all visible {GARMENT_CATEGORY} items in the image for the {GARMENT}. Keep the original model, face, skin, hair, pose, expression, body shape, camera angle, framing, background, environment, lighting direction, lighting intensity, exposure, white balance, global color grading, contrast, saturation, shadows, highlights, reflections, and all non-garment pixels exactly unchanged.

Change all visible {GARMENT_CATEGORY} items to the exact target color {RGB_VALUE} and exact HEX value {HEX_VALUE}. If multiple {GARMENT_CATEGORY} pieces are visible, recolor every one of them. Do not leave any matching garment piece unmodified. Do not modify tops, shirts, jackets, shoes, accessories, or any other non-target item.

Preserve the original garment structure exactly. Keep the waistband, fly, seams, stitching, hems, pleats, folds, wrinkles, pocket shapes, fabric weave, edge shapes, and silhouette unchanged. Do not add, remove, or redesign any construction details. Do not invent new stitching, do not create extra lines, and do not redraw the garment.

Match the garment color faithfully to the target RGB value. Do not make it brighter, cleaner, more vivid, more saturated, neon, glossy, or more colorful than the target color. Preserve realistic textile behavior, natural shading, subtle highlights, and material depth without altering the rest of the scene.

The result must look like a minimal, physically plausible recolor edit on an authentic product photograph, not a repaint or redesign.

Negative prompt:
Do not change the background saturation, contrast, color grading, or white balance. Do not modify tops, shirts, jackets, shoes, accessories, or any non-target clothing. Do not alter seams, stitching, waistline structure, hems, or silhouette. Do not invent new garment details. Do not oversaturate the garment. Do not make the clothing brighter, cleaner, more vivid, more saturated, glossy, or enhanced beyond the target RGB. Do not repaint the whole image. Do not change any non-garment pixels. Do not create AI artifacts, plastic textures, or unnatural redraws.`;
  }
  if (kind === 'dress') {
    return `Recolor all visible dress items in the image for the {GARMENT}. Keep the original model, face, skin, hair, pose, expression, body shape, camera angle, framing, background, environment, lighting direction, lighting intensity, exposure, white balance, global color grading, contrast, saturation, shadows, highlights, reflections, and all non-garment pixels exactly unchanged.

Change all visible dresses to the exact target color {RGB_VALUE} and exact HEX value {HEX_VALUE}. If multiple dress parts or layered dress pieces are visible, recolor every one of them. Do not leave any matching dress piece unmodified. Do not modify shoes, accessories, or any other non-target item.

Preserve the original garment structure exactly. Keep the neckline, straps, seams, stitching, hems, folds, wrinkles, fabric weave, edge shapes, fringe, sequins, and silhouette unchanged. Do not add, remove, or redesign any construction details. Do not invent new stitching, do not create extra lines, and do not redraw the garment.

Match the garment color faithfully to the target RGB value. Do not make it brighter, cleaner, more vivid, more saturated, neon, glossy, or more colorful than the target color. Preserve realistic textile behavior, natural shading, subtle highlights, and material depth without altering the rest of the scene.

The result must look like a minimal, physically plausible recolor edit on an authentic product photograph, not a repaint or redesign.

Negative prompt:
Do not change the background saturation, contrast, color grading, or white balance. Do not modify shoes or accessories. Do not alter seams, stitching, neckline structure, hems, straps, fringe, sequins, or silhouette. Do not invent new garment details. Do not oversaturate the garment. Do not make the clothing brighter, cleaner, more vivid, more saturated, glossy, or enhanced beyond the target RGB. Do not repaint the whole image. Do not change any non-garment pixels. Do not create AI artifacts, plastic textures, or unnatural redraws.`;
  }
  return `Recolor all visible {GARMENT_CATEGORY} items in the image for the {GARMENT}. Keep the original model, face, skin, hair, pose, expression, body shape, camera angle, framing, background, environment, lighting direction, lighting intensity, exposure, white balance, global color grading, contrast, saturation, shadows, highlights, reflections, and all non-garment pixels exactly unchanged.

Change all visible {GARMENT_CATEGORY} items to the exact target color {RGB_VALUE} and exact HEX value {HEX_VALUE}. If multiple {GARMENT_CATEGORY} pieces are visible, recolor every one of them. Do not leave any matching garment piece unmodified. Do not modify pants, shorts, skirt, shoes, accessories, or any other non-target item.

Preserve the original garment structure exactly. Keep the neckline, collar, seams, stitching, hems, cuffs, folds, wrinkles, fabric weave, edge shapes, and silhouette unchanged. Do not add, remove, or redesign any construction details. Do not invent new stitching, do not create extra lines, and do not redraw the garment.

Match the garment color faithfully to the target RGB value. Do not make it brighter, cleaner, more vivid, more saturated, neon, glossy, or more colorful than the target color. Preserve realistic textile behavior, natural shading, subtle highlights, and material depth without altering the rest of the scene.

The result must look like a minimal, physically plausible recolor edit on an authentic product photograph, not a repaint or redesign.

Negative prompt:
Do not change the background saturation, contrast, color grading, or white balance. Do not modify pants, shorts, skirt, shoes, accessories, or any non-target clothing. Do not alter seams, stitching, collars, hems, neckline structure, or silhouette. Do not invent new garment details. Do not oversaturate the garment. Do not make the clothing brighter, cleaner, more vivid, more saturated, glossy, or enhanced beyond the target RGB. Do not repaint the whole image. Do not change any non-garment pixels. Do not create AI artifacts, plastic textures, or unnatural redraws.`;
}

function renderDefaultTemplates() {
  const preview = document.getElementById('defaultPromptPreview');
  preview.innerHTML = `
    <div class="template-block">
      <div class="template-chip">Top</div>
      <pre>${escapeHtml(defaultTemplateText('top'))}</pre>
    </div>
    <div class="template-block">
      <div class="template-chip">Bottom</div>
      <pre>${escapeHtml(defaultTemplateText('bottom'))}</pre>
    </div>
    <div class="template-block">
      <div class="template-chip">Dress</div>
      <pre>${escapeHtml(defaultTemplateText('dress'))}</pre>
    </div>
    <div class="template-note">未命中裤装、裙装、连衣裙关键词时，默认使用 Top 模板。</div>
  `;
}

function parseManualColors(text) {
  const lines = String(text || '').split(/\r?\n/).map(s => s.trim()).filter(Boolean);
  return lines.map(line => {
    const normalized = line.replace('：', ':');
    const parts = normalized.split(':');
    if (parts.length < 2) return null;
    const name = parts[0].trim();
    const hex = parts.slice(1).join(':').trim();
    return { name, hex };
  }).filter(Boolean);
}

function jobCard(job) {
  const div = document.createElement('div');
  div.className = 'job';
  const colorCount = (job.colors || []).length;
  const canCancel = job.status === 'queued' || job.status === 'running';
  const canResume = ['paused', 'failed', 'cancelled'].includes(job.status) && (job.completed_combos || []).length > 0;
  const totalCombos = (job.image_paths || []).length * colorCount;
  const completedCount = (job.completed_combos || []).length;
  const serverLabel = job._server ? `<span class="server-tag">${escapeHtml(job._server)}</span>` : '';
  div.innerHTML = `
    <div class="job-top">
      <div>
        <strong>${escapeHtml(job.product_id || job.job_id)}</strong>
        ${serverLabel}
        <div class="meta">${escapeHtml(job.garment_name || '')} · ${escapeHtml(job.input_name || '')}</div>
      </div>
      <span class="badge badge-${escapeHtml(job.status)}">${escapeHtml(job.status)}</span>
    </div>
    <div class="progress"><div style="width:${job.progress || 0}%"></div></div>
    <div class="meta">${escapeHtml(job.message || '')}</div>
    <div class="meta">进度：${job.progress || 0}% · 颜色数：${colorCount}${completedCount > 0 ? ` · 已完成：${completedCount}/${totalCombos}` : ''}</div>
    ${canCancel ? `<button class="cancel-btn" onclick="cancelJob('${escapeHtml(job.job_id)}', '${escapeHtml(job._serverUrl || '')}', this)">取消任务</button>` : ''}
    ${canResume ? `<button class="resume-btn" onclick="resumeJob('${escapeHtml(job.job_id)}', '${escapeHtml(job._serverUrl || '')}', this)">恢复任务</button>` : ''}
    ${job.status === 'completed' ? `<a class="link-btn" href="${escapeHtml(job._serverUrl || '')}/api/jobs/${encodeURIComponent(job.job_id)}/download">下载结果</a>` : ''}
    ${job.status === 'failed' ? `<div class="meta error">${escapeHtml(job.error || '')}</div>` : ''}
  `;
  return div;
}

async function cancelJob(jobId, serverUrl, btn) {
  if (!confirm('确定要取消这个任务吗？')) return;
  btn.disabled = true;
  btn.textContent = '取消中...';
  try {
    const baseUrl = serverUrl || currentServerUrl || '';
    const resp = await fetch(`${baseUrl}/api/jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' });
    if (!resp.ok) throw new Error(await resp.text());
    await refreshJobs();
  } catch (err) {
    alert(err.message || '取消失败');
    btn.disabled = false;
    btn.textContent = '取消任务';
  }
}

async function resumeJob(jobId, serverUrl, btn) {
  btn.disabled = true;
  btn.textContent = '恢复中...';
  try {
    const baseUrl = serverUrl || currentServerUrl || '';
    const resp = await fetch(`${baseUrl}/api/jobs/${encodeURIComponent(jobId)}/resume`, { method: 'POST' });
    if (!resp.ok) throw new Error(await resp.text());
    await refreshJobs();
  } catch (err) {
    alert(err.message || '恢复失败');
    btn.disabled = false;
    btn.textContent = '恢复任务';
  }
}

async function refreshJobs() {
  let allJobs = [];

  if (!currentServerUrl) {
    // Auto mode: fetch from all servers in parallel
    const results = await Promise.allSettled(
      SERVERS.map(s => fetchFromServer(s.url, '/api/jobs').then(data => ({
        server: s.name,
        serverUrl: s.url,
        jobs: data.jobs || []
      })))
    );
    for (const r of results) {
      if (r.status === 'fulfilled') {
        for (const job of r.value.jobs) {
          job._server = r.value.server;
          job._serverUrl = r.value.serverUrl;
          allJobs.push(job);
        }
      }
    }
  } else {
    // Specific server
    const server = SERVERS.find(s => s.url === currentServerUrl);
    const serverName = server ? server.name : currentServerUrl;
    try {
      const data = await api('/api/jobs');
      for (const job of (data.jobs || [])) {
        job._server = serverName;
        job._serverUrl = currentServerUrl;
        allJobs.push(job);
      }
    } catch {
      // ignore fetch errors
    }
  }

  // Sort by created_at descending
  allJobs.sort((a, b) => (b.created_at || 0) - (a.created_at || 0));

  const list = document.getElementById('jobsList');
  list.innerHTML = '';
  allJobs.forEach(job => list.appendChild(jobCard(job)));
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
    if (!files.length) throw new Error('请先选择商品图文件夹');
    const images = files.filter(file => file.type.startsWith('image/'));
    if (!images.length) throw new Error('文件夹里没有可用图片');
    const colorsTxt = document.getElementById('colorsTxtFile').files[0];
    if (!colorsTxt) throw new Error('请上传颜色定义 TXT 文件');
    const manualColors = parseManualColors(document.getElementById('manualColors').value);
    let colorsText = await colorsTxt.text();
    if (manualColors.length) {
      const manualBlock = 'COLORS\n' + manualColors.map(c => `${c.name}: ${c.hex}`).join('\n');
      colorsText = colorsText.trimEnd() + '\n' + manualBlock;
    }
    const form = new FormData();
    const folderName = images[0].webkitRelativePath?.split('/')[0] || '';
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
    if (images.length > 0) form.append('image', images[0]);
    images.forEach(file => form.append('images', file));
    form.append('colors_text', colorsText);
    const result = await api('/api/jobs', { method: 'POST', body: form });
    status.textContent = `已提交任务 ${folderName || result.job_id}`;
    await refreshJobs();
  } catch (err) {
    status.textContent = '提交失败';
    alert(err.message || '提交失败');
  } finally {
    btn.disabled = false;
    btn.textContent = '开始改色';
  }
}

document.getElementById('submitBtn').addEventListener('click', submitJob);
document.getElementById('refreshBtn').addEventListener('click', refreshJobs);

document.getElementById('serverSelect').addEventListener('change', async (e) => {
  currentServerUrl = e.target.value;
  await refreshServerStatus();
  await refreshJobs();
});

async function refreshServerStatus() {
  const statusEl = document.getElementById('serverStatus');
  if (!currentServerUrl) {
    // Auto mode: show status of all servers
    const results = await Promise.allSettled(
      SERVERS.map(s => fetchFromServer(s.url, '/api/health').then(data => ({
        name: s.name,
        running: data.running_jobs || 0,
        queued: data.queued_jobs || 0,
        ok: data.ok
      })))
    );
    const parts = [];
    for (const r of results) {
      if (r.status === 'fulfilled' && r.value.ok) {
        parts.push(`${r.value.name}: 运行${r.value.running} 排队${r.value.queued}`);
      } else {
        const name = r.status === 'fulfilled' ? r.value.name : '未知';
        parts.push(`${name}: 离线`);
      }
    }
    statusEl.textContent = parts.join(' | ');
    return;
  }
  try {
    const info = await api('/api/health');
    statusEl.textContent = `运行中: ${info.running_jobs || 0} | 排队中: ${info.queued_jobs || 0}`;
  } catch {
    statusEl.textContent = '无法连接';
  }
}

loadDefaults();
refreshServerStatus();
refreshJobs();
setInterval(refreshJobs, 3000);
