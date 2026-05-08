const SERVERS = [
  { id: '186', name: '服务器 A (186)', url: 'http://192.168.0.186:8000' },
  { id: '34', name: '服务器 B (34)', url: 'http://192.168.0.34:8000' },
];

let currentServerUrl = '';
let statusChart = null;
let engineChart = null;
let dailyChart = null;
let allJobs = [];
let prevStatsJson = '';

async function fetchFromServer(baseUrl, url) {
  const resp = await fetch(baseUrl + url);
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

async function fetchStatsRaw() {
  if (!currentServerUrl) {
    const results = await Promise.allSettled(
      SERVERS.map(s => fetchFromServer(s.url, '/api/stats').then(data => ({ ...data, _server: s.name })))
    );
    return results.filter(r => r.status === 'fulfilled').map(r => r.value);
  }
  return [await fetchFromServer(currentServerUrl, '/api/stats')];
}

async function fetchJobs() {
  if (!currentServerUrl) {
    const results = await Promise.allSettled(
      SERVERS.map(s => fetchFromServer(s.url, '/api/jobs').then(data =>
        (data.jobs || []).map(j => ({ ...j, _server: s.name, _serverUrl: s.url }))
      ))
    );
    const jobs = [];
    for (const r of results) {
      if (r.status === 'fulfilled') jobs.push(...r.value);
    }
    jobs.sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
    return jobs;
  }
  const data = await fetchFromServer(currentServerUrl, '/api/jobs');
  return (data.jobs || []).map(j => ({ ...j, _serverUrl: currentServerUrl }));
}

function mergeStats(all, jobs) {
  const merged = {
    total_jobs: 0, products: 0, total_combos: 0, completed_combos: 0,
    completion_rate: 0, avg_duration_seconds: 0,
    by_status: {}, by_engine: {}, by_model: {}, daily_submissions: {},
  };
  let durationSum = 0, durationCount = 0;
  for (const s of all) {
    merged.total_jobs += s.total_jobs || 0;
    merged.total_combos += s.total_combos || 0;
    merged.completed_combos += s.completed_combos || 0;
    for (const [k, v] of Object.entries(s.by_status || {})) merged.by_status[k] = (merged.by_status[k] || 0) + v;
    for (const [k, v] of Object.entries(s.by_engine || {})) merged.by_engine[k] = (merged.by_engine[k] || 0) + v;
    for (const [k, v] of Object.entries(s.by_model || {})) merged.by_model[k] = (merged.by_model[k] || 0) + v;
    for (const [k, v] of Object.entries(s.daily_submissions || {})) merged.daily_submissions[k] = (merged.daily_submissions[k] || 0) + v;
    if (s.avg_duration_seconds > 0 && s.total_jobs > 0) {
      durationSum += s.avg_duration_seconds * (s.by_status?.completed || 0);
      durationCount += s.by_status?.completed || 0;
    }
  }
  // Count unique product_ids from jobs list to avoid cross-server duplicates
  const uniqueProducts = new Set();
  for (const j of (jobs || [])) {
    if (j.product_id) uniqueProducts.add(j.product_id);
  }
  merged.products = uniqueProducts.size;
  merged.completion_rate = merged.total_combos > 0 ? merged.completed_combos / merged.total_combos : 0;
  merged.avg_duration_seconds = durationCount > 0 ? durationSum / durationCount : 0;
  return merged;
}

function formatDuration(seconds) {
  if (!seconds || seconds <= 0) return '-';
  if (seconds < 60) return `${Math.round(seconds)}秒`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}分钟`;
  return `${(seconds / 3600).toFixed(1)}小时`;
}

function formatTime(ts) {
  if (!ts || ts <= 0) return '-';
  const d = new Date(ts * 1000);
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

const STATUS_COLORS = {
  completed: '#22c55e', running: '#3b82f6', queued: '#94a3b8',
  failed: '#ef4444', cancelled: '#6b7280', paused: '#eab308', cancelling: '#f97316',
};
const STATUS_LABELS = {
  completed: '已完成', running: '运行中', queued: '排队中',
  failed: '失败', cancelled: '已取消', paused: '暂停', cancelling: '取消中',
};
const ENGINE_LABELS = { comfyui: 'ComfyUI', api: 'Cloud API' };

function renderStatsCards(stats) {
  document.getElementById('statProducts').textContent = stats.products || 0;
  document.getElementById('statCompleted').textContent = stats.by_status?.completed || 0;
  document.getElementById('statActive').textContent = (stats.by_status?.running || 0) + (stats.by_status?.queued || 0);
  document.getElementById('statFailed').textContent = (stats.by_status?.failed || 0) + (stats.by_status?.paused || 0);
  document.getElementById('statCancelled').textContent = (stats.by_status?.cancelled || 0) + (stats.by_status?.cancelling || 0);
  document.getElementById('statCombos').textContent = `${stats.completed_combos || 0}/${stats.total_combos || 0}`;
  document.getElementById('statRate').textContent = `${((stats.completion_rate || 0) * 100).toFixed(1)}%`;
}

function renderStatusChart(stats) {
  const ctx = document.getElementById('statusChart').getContext('2d');
  const labels = [], data = [], colors = [];
  for (const [k, v] of Object.entries(stats.by_status || {})) {
    if (v > 0) {
      labels.push(STATUS_LABELS[k] || k);
      data.push(v);
      colors.push(STATUS_COLORS[k] || '#6b7280');
    }
  }
  if (statusChart) statusChart.destroy();
  statusChart = new Chart(ctx, {
    type: 'doughnut',
    data: { labels, datasets: [{ data, backgroundColor: colors, borderWidth: 0 }] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom', labels: { color: '#94a3b8', padding: 12 } } } },
  });
}

function renderEngineChart(stats) {
  const ctx = document.getElementById('engineChart').getContext('2d');
  const labels = [], data = [], colors = ['#2563eb', '#0ea5e9'];
  for (const [k, v] of Object.entries(stats.by_engine || {})) {
    labels.push(ENGINE_LABELS[k] || k);
    data.push(v);
  }
  if (engineChart) engineChart.destroy();
  engineChart = new Chart(ctx, {
    type: 'bar',
    data: { labels, datasets: [{ data, backgroundColor: colors.slice(0, labels.length), borderRadius: 6 }] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { color: '#94a3b8', stepSize: 1 }, grid: { color: 'rgba(148,163,184,0.08)' } }, x: { ticks: { color: '#94a3b8' }, grid: { display: false } } } },
  });
}

function renderDailyChart(stats) {
  const ctx = document.getElementById('dailyChart').getContext('2d');
  const entries = Object.entries(stats.daily_submissions || {}).sort((a, b) => a[0].localeCompare(b[0]));
  const labels = entries.map(([d]) => d.slice(5));
  const data = entries.map(([, v]) => v);
  if (dailyChart) dailyChart.destroy();
  dailyChart = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets: [{ data, borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,0.1)', fill: true, tension: 0.3, pointRadius: 4, pointBackgroundColor: '#3b82f6' }] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { color: '#94a3b8', stepSize: 1 }, grid: { color: 'rgba(148,163,184,0.08)' } }, x: { ticks: { color: '#94a3b8' }, grid: { display: false } } } },
  });
}

function renderTable(jobs) {
  const search = document.getElementById('tableSearch').value.toLowerCase();
  const filter = document.getElementById('tableFilter').value;
  const filtered = jobs.filter(j => {
    if (filter && j.status !== filter) return false;
    if (search && !(j.product_id || '').toLowerCase().includes(search) && !(j.garment_name || '').toLowerCase().includes(search)) return false;
    return true;
  });
  const tbody = document.getElementById('jobsTableBody');
  tbody.innerHTML = filtered.map(j => {
    const nImg = (j.image_paths || []).length;
    const nColors = (j.colors || []).length;
    const nDone = (j.completed_combos || []).length;
    const total = nImg * Math.max(1, nColors);
    const dur = j.status === 'completed' && j.created_at > 0 ? formatDuration(j.updated_at - j.created_at) : '-';
    const engineLabel = j.engine === 'api' ? (j.api_model || 'API') : 'ComfyUI';
    return `<tr>
      <td>${escapeHtml(j.product_id || j.job_id)}</td>
      <td>${escapeHtml(j.garment_name || '')}</td>
      <td><span class="badge badge-${escapeHtml(j.status)}">${STATUS_LABELS[j.status] || j.status}</span></td>
      <td>${escapeHtml(engineLabel)}</td>
      <td>${nImg}</td>
      <td>${nColors}</td>
      <td>${nDone}/${total}</td>
      <td>${formatTime(j.created_at)}</td>
      <td>${dur}</td>
    </tr>`;
  }).join('');
}

function escapeHtml(text) {
  return String(text || '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
}

async function refresh() {
  try {
    const [allStats, jobs] = await Promise.all([fetchStatsRaw(), fetchJobs()]);
    allJobs = jobs;
    const stats = mergeStats(allStats, jobs);
    renderStatsCards(stats);
    // Only re-render charts if data actually changed
    const statsJson = JSON.stringify({ by_status: stats.by_status, by_engine: stats.by_engine, daily: stats.daily_submissions });
    if (statsJson !== prevStatsJson) {
      prevStatsJson = statsJson;
      renderStatusChart(stats);
      renderEngineChart(stats);
      renderDailyChart(stats);
    }
    renderTable(jobs);
  } catch (e) {
    console.error('Dashboard refresh error:', e);
  }
}

async function refreshServerStatus() {
  const statusEl = document.getElementById('serverStatus');
  if (!currentServerUrl) {
    const results = await Promise.allSettled(
      SERVERS.map(s => fetchFromServer(s.url, '/api/health').then(d => ({ name: s.name, ok: d.ok, running: d.running_jobs, queued: d.queued_jobs })))
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
  } else {
    try {
      const d = await fetchFromServer(currentServerUrl, '/api/health');
      statusEl.textContent = `运行中: ${d.running_jobs || 0} | 排队中: ${d.queued_jobs || 0}`;
    } catch {
      statusEl.textContent = '无法连接';
    }
  }
}

document.getElementById('serverSelect').addEventListener('change', async (e) => {
  currentServerUrl = e.target.value;
  await Promise.all([refresh(), refreshServerStatus()]);
});

document.getElementById('tableSearch').addEventListener('input', () => renderTable(allJobs));
document.getElementById('tableFilter').addEventListener('change', () => renderTable(allJobs));

refresh();
refreshServerStatus();
setInterval(() => { refresh(); refreshServerStatus(); }, 3000);
