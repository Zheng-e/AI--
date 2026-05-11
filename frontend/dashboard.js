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
    const results = await Promise.allSettled(SERVERS.map(server => fetchFromServer(server.url, '/api/stats')));
    return results.filter(result => result.status === 'fulfilled').map(result => result.value);
  }
  return [await fetchFromServer(currentServerUrl, '/api/stats')];
}

async function fetchJobs() {
  if (!currentServerUrl) {
    const results = await Promise.allSettled(
      SERVERS.map(server => fetchFromServer(server.url, '/api/jobs').then(data =>
        (data.jobs || []).map(job => ({ ...job, _server: server.name, _serverUrl: server.url }))
      ))
    );
    const jobs = [];
    for (const result of results) {
      if (result.status === 'fulfilled') jobs.push(...result.value);
    }
    jobs.sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
    return jobs;
  }
  const data = await fetchFromServer(currentServerUrl, '/api/jobs');
  return (data.jobs || []).map(job => ({ ...job, _serverUrl: currentServerUrl }));
}

function mergeStats(statsList, jobs) {
  const merged = {
    total_jobs: 0,
    products: 0,
    total_combos: 0,
    completed_combos: 0,
    failed_combos: 0,
    completion_rate: 0,
    avg_duration_seconds: 0,
    by_status: {},
    by_engine: {},
    by_model: {},
    daily_submissions: {},
  };
  let durationSum = 0;
  let durationCount = 0;
  for (const stats of statsList) {
    merged.total_jobs += stats.total_jobs || 0;
    merged.total_combos += stats.total_combos || 0;
    merged.completed_combos += stats.completed_combos || 0;
    merged.failed_combos += stats.failed_combos || 0;
    for (const [key, value] of Object.entries(stats.by_status || {})) merged.by_status[key] = (merged.by_status[key] || 0) + value;
    for (const [key, value] of Object.entries(stats.by_engine || {})) merged.by_engine[key] = (merged.by_engine[key] || 0) + value;
    for (const [key, value] of Object.entries(stats.by_model || {})) merged.by_model[key] = (merged.by_model[key] || 0) + value;
    for (const [key, value] of Object.entries(stats.daily_submissions || {})) merged.daily_submissions[key] = (merged.daily_submissions[key] || 0) + value;
    if (stats.avg_duration_seconds > 0 && stats.by_status?.completed > 0) {
      durationSum += stats.avg_duration_seconds * stats.by_status.completed;
      durationCount += stats.by_status.completed;
    }
  }
  merged.products = new Set((jobs || []).map(job => job.product_id).filter(Boolean)).size;
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
  return new Date(ts * 1000).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function escapeHtml(text) {
  return String(text || '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
}

const STATUS_COLORS = {
  completed: '#22c55e',
  completed_with_errors: '#fb923c',
  running: '#3b82f6',
  queued: '#94a3b8',
  failed: '#ef4444',
  cancelled: '#6b7280',
  paused: '#eab308',
  cancelling: '#f97316',
};

const STATUS_LABELS = {
  completed: '已完成',
  completed_with_errors: '部分完成',
  running: '运行中',
  queued: '排队中',
  failed: '失败',
  cancelled: '已取消',
  paused: '暂停',
  cancelling: '取消中',
};

const ENGINE_LABELS = { comfyui: 'ComfyUI 本地', api: 'API 并行' };

function renderStatsCards(stats) {
  document.getElementById('statProducts').textContent = stats.products || 0;
  document.getElementById('statCompleted').textContent = (stats.by_status?.completed || 0) + (stats.by_status?.completed_with_errors || 0);
  document.getElementById('statActive').textContent = (stats.by_status?.running || 0) + (stats.by_status?.queued || 0);
  document.getElementById('statFailed').textContent = (stats.by_status?.failed || 0) + (stats.by_status?.paused || 0);
  document.getElementById('statCancelled').textContent = (stats.by_status?.cancelled || 0) + (stats.by_status?.cancelling || 0);
  document.getElementById('statCombos').textContent = `${stats.completed_combos || 0}/${stats.total_combos || 0}`;
  document.getElementById('statRate').textContent = `${((stats.completion_rate || 0) * 100).toFixed(1)}%`;
}

function renderStatusChart(stats) {
  const ctx = document.getElementById('statusChart').getContext('2d');
  const entries = Object.entries(stats.by_status || {}).filter(([, value]) => value > 0);
  if (statusChart) statusChart.destroy();
  statusChart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: entries.map(([key]) => STATUS_LABELS[key] || key),
      datasets: [{ data: entries.map(([, value]) => value), backgroundColor: entries.map(([key]) => STATUS_COLORS[key] || '#6b7280'), borderWidth: 0 }],
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom', labels: { color: '#94a3b8', padding: 12 } } } },
  });
}

function renderEngineChart(stats) {
  const ctx = document.getElementById('engineChart').getContext('2d');
  const entries = Object.entries(stats.by_engine || {});
  if (engineChart) engineChart.destroy();
  engineChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: entries.map(([key]) => ENGINE_LABELS[key] || key),
      datasets: [{ data: entries.map(([, value]) => value), backgroundColor: ['#2563eb', '#0ea5e9'], borderRadius: 6 }],
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { color: '#94a3b8', stepSize: 1 }, grid: { color: 'rgba(148,163,184,0.08)' } }, x: { ticks: { color: '#94a3b8' }, grid: { display: false } } } },
  });
}

function renderDailyChart(stats) {
  const ctx = document.getElementById('dailyChart').getContext('2d');
  const entries = Object.entries(stats.daily_submissions || {}).sort((a, b) => a[0].localeCompare(b[0]));
  if (dailyChart) dailyChart.destroy();
  dailyChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: entries.map(([date]) => date.slice(5)),
      datasets: [{ data: entries.map(([, value]) => value), borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,0.1)', fill: true, tension: 0.3, pointRadius: 4, pointBackgroundColor: '#3b82f6' }],
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { color: '#94a3b8', stepSize: 1 }, grid: { color: 'rgba(148,163,184,0.08)' } }, x: { ticks: { color: '#94a3b8' }, grid: { display: false } } } },
  });
}

function renderTable(jobs) {
  const search = document.getElementById('tableSearch').value.toLowerCase();
  const filter = document.getElementById('tableFilter').value;
  const filtered = jobs.filter(job => {
    if (filter && job.status !== filter) return false;
    if (search && !(job.product_id || '').toLowerCase().includes(search) && !(job.garment_name || '').toLowerCase().includes(search)) return false;
    return true;
  });
  document.getElementById('jobsTableBody').innerHTML = filtered.map(job => {
    const imageCount = (job.image_paths || []).length;
    const colorCount = (job.colors || []).length;
    const total = job.total_combos || imageCount * Math.max(1, colorCount);
    const done = job.completed_count ?? (job.completed_combos || []).length;
    const duration = ['completed', 'completed_with_errors'].includes(job.status) && job.created_at > 0 ? formatDuration(job.updated_at - job.created_at) : '-';
    const engineLabel = job.engine === 'api' ? (job.api_model || 'API') : 'ComfyUI';
    return `<tr>
      <td>${escapeHtml(job.product_id || job.job_id)}</td>
      <td>${escapeHtml(job.garment_name || '')}</td>
      <td><span class="badge badge-${escapeHtml(job.status)}">${STATUS_LABELS[job.status] || job.status}</span></td>
      <td>${escapeHtml(engineLabel)}</td>
      <td>${imageCount}</td>
      <td>${colorCount}</td>
      <td>${done}/${total}</td>
      <td>${formatTime(job.created_at)}</td>
      <td>${duration}</td>
    </tr>`;
  }).join('');
}

async function refresh() {
  try {
    const [statsList, jobs] = await Promise.all([fetchStatsRaw(), fetchJobs()]);
    allJobs = jobs;
    const stats = mergeStats(statsList, jobs);
    renderStatsCards(stats);
    const statsJson = JSON.stringify({ by_status: stats.by_status, by_engine: stats.by_engine, daily: stats.daily_submissions });
    if (statsJson !== prevStatsJson) {
      prevStatsJson = statsJson;
      renderStatusChart(stats);
      renderEngineChart(stats);
      renderDailyChart(stats);
    }
    renderTable(jobs);
  } catch (error) {
    console.error('Dashboard refresh error:', error);
  }
}

async function refreshServerStatus() {
  const statusEl = document.getElementById('serverStatus');
  if (!currentServerUrl) {
    const results = await Promise.allSettled(
      SERVERS.map(server => fetchFromServer(server.url, '/api/health').then(data => ({ name: server.name, running: data.running_jobs, queued: data.queued_jobs })))
    );
    statusEl.textContent = results.map(result => (
      result.status === 'fulfilled' ? `${result.value.name}: 运行${result.value.running} 排队${result.value.queued}` : '服务器离线'
    )).join(' | ');
    return;
  }
  try {
    const data = await fetchFromServer(currentServerUrl, '/api/health');
    statusEl.textContent = `运行中: ${data.running_jobs || 0} | 排队中: ${data.queued_jobs || 0}`;
  } catch {
    statusEl.textContent = '无法连接';
  }
}

document.getElementById('serverSelect').addEventListener('change', async event => {
  currentServerUrl = event.target.value;
  await Promise.all([refresh(), refreshServerStatus()]);
});
document.getElementById('tableSearch').addEventListener('input', () => renderTable(allJobs));
document.getElementById('tableFilter').addEventListener('change', () => renderTable(allJobs));

refresh();
refreshServerStatus();
setInterval(() => {
  refresh();
  refreshServerStatus();
}, 3000);
