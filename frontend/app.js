async function api(url, options = {}) {
  const resp = await fetch(url, options);
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
  div.innerHTML = `
    <div class="job-top">
      <div>
        <strong>${escapeHtml(job.job_id)}</strong>
        <div class="meta">${escapeHtml(job.garment_name || '')} · ${escapeHtml(job.input_name || '')}</div>
      </div>
      <span class="badge badge-${escapeHtml(job.status)}">${escapeHtml(job.status)}</span>
    </div>
    <div class="progress"><div style="width:${job.progress || 0}%"></div></div>
    <div class="meta">${escapeHtml(job.message || '')}</div>
    <div class="meta">进度：${job.progress || 0}% · 颜色数：${colorCount}</div>
    ${job.status === 'completed' ? `<a class="link-btn" href="/api/jobs/${encodeURIComponent(job.job_id)}/download">下载结果</a>` : ''}
    ${job.status === 'failed' ? `<div class="meta error">${escapeHtml(job.error || '')}</div>` : ''}
  `;
  return div;
}

async function refreshJobs() {
  const data = await api('/api/jobs');
  const list = document.getElementById('jobsList');
  list.innerHTML = '';
  data.jobs.slice().reverse().forEach(job => list.appendChild(jobCard(job)));
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
  const status = document.getElementById('submitStatus');
  try {
    status.textContent = '提交中...';
    const files = Array.from(document.getElementById('imageFiles').files || []);
    if (!files.length) throw new Error('请先选择商品图文件夹');
    const images = files.filter(file => file.type.startsWith('image/'));
    if (!images.length) throw new Error('文件夹里没有可用图片');
    const colorsTxt = document.getElementById('colorsTxtFile').files[0];
    if (!colorsTxt) throw new Error('请上传颜色定义 TXT 文件');
    const manualColors = parseManualColors(document.getElementById('manualColors').value);
    const form = new FormData();
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
    form.append('colors_text', await colorsTxt.text());
    if (manualColors.length) form.append('manual_colors', JSON.stringify(manualColors));
    const result = await api('/api/jobs', { method: 'POST', body: form });
    status.textContent = `已提交任务 ${result.job_id}`;
    await refreshJobs();
  } catch (err) {
    status.textContent = '提交失败';
    alert(err.message || '提交失败');
  }
}

document.getElementById('submitBtn').addEventListener('click', submitJob);
document.getElementById('refreshBtn').addEventListener('click', refreshJobs);
loadDefaults();
refreshJobs();
setInterval(refreshJobs, 3000);
