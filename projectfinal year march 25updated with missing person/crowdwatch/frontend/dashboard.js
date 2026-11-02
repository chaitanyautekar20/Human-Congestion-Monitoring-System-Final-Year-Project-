/* ── Human Congestion Monitoring Dashboard ── */

// ── DOM refs ──────────────────────────────────────────────────────────────────
const wsStatusEl       = document.getElementById('wsStatus');
const totalCountEl     = document.getElementById('totalCount');
const thresholdDisplay = document.getElementById('thresholdDisplay');
const alertModeEl      = document.getElementById('alertMode');
const thresholdInfoVal = document.getElementById('thresholdInfoVal');
const alertsFeed       = document.getElementById('alertsFeed');
const missingBadge     = document.getElementById('missingBadge');

const webcamStartBtn   = document.getElementById('webcamStartBtn');
const webcamStopBtn    = document.getElementById('webcamStopBtn');
const webcamStatusEl   = document.getElementById('webcamStatus');
const webcamCountEl    = document.getElementById('webcamCount');
const webcamPeopleEl   = document.getElementById('webcamPeopleCount');



const thresholdInput   = document.getElementById('thresholdInput');
const setThresholdBtn  = document.getElementById('setThresholdBtn');
const areaInput        = document.getElementById('areaInput');
const setAreaBtn       = document.getElementById('setAreaBtn');
const areaCalcInfo     = document.getElementById('areaCalcInfo');
const autoToggle       = document.getElementById('autoThresholdToggle');
const clearAlertsBtn   = document.getElementById('clearAlertsBtn');

const missingSetFile   = document.getElementById('missingSetFile');
const setMissingBtn    = document.getElementById('setMissingBtn');
const missingStatus    = document.getElementById('missingStatus');
const clearMissingBtn  = document.getElementById('clearMissingBtn');
const missingSearchFile= document.getElementById('missingSearchFile');
const searchMissingBtn = document.getElementById('searchMissingBtn');
const missingResults   = document.getElementById('missingResults');

// ── Live density chart ────────────────────────────────────────────────────────
const liveCtx = document.getElementById('densityChart').getContext('2d');
const liveData = {
  labels: [],
  datasets: [{
    label: 'People',
    data: [],
    fill: true,
    tension: 0.4,
    borderColor: '#6366f1',
    backgroundColor: 'rgba(99,102,241,0.10)',
    pointRadius: 2,
    pointBackgroundColor: '#818cf8',
  }]
};
const densityChart = new Chart(liveCtx, {
  type: 'line',
  data: liveData,
  options: {
    responsive: true,
    animation: false,
    plugins: {
      legend: { labels: { color: '#94a3b8', font: { size: 11 } } },
      tooltip: { mode: 'index', intersect: false },
    },
    scales: {
      x: { ticks: { color: '#64748b', maxTicksLimit: 8 }, grid: { color: '#1e2235' } },
      y: { beginAtZero: true, ticks: { color: '#64748b' }, grid: { color: '#1e2235' } },
    },
  }
});

function pushLivePoint(total) {
  liveData.labels.push(new Date().toLocaleTimeString());
  liveData.datasets[0].data.push(total);
  if (liveData.labels.length > 60) { liveData.labels.shift(); liveData.datasets[0].data.shift(); }
  densityChart.update('none');
}

// animate count changes smoothly
function animateCount(el, newVal) {
  const current = parseInt(el.textContent) || 0;
  if (current === newVal) return;
  const step = newVal > current ? 1 : -1;
  const diff = Math.abs(newVal - current);
  const delay = diff > 10 ? 20 : 60;
  let v = current;
  const tick = setInterval(() => {
    v += step;
    el.textContent = v;
    if (v === newVal) clearInterval(tick);
  }, delay);
}

window._currentThreshold = 30;

// ── WebSocket ─────────────────────────────────────────────────────────────────
let ws;
function setupWS() {
  const proto = location.protocol === 'https:' ? 'wss://' : 'ws://';
  ws = new WebSocket(proto + location.host + '/ws/alerts');
  ws.onopen = () => { wsStatusEl.innerHTML = '<span class="dot dot-on"></span> Connected'; };
  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      if (msg.type === 'STATS_UPDATE') {
        const total = msg.total ?? 0;
        animateCount(totalCountEl, total);
        pushLivePoint(total);
        const thr = msg.threshold ?? 30;
        window._currentThreshold = thr;
        thresholdDisplay.textContent = thr;
        thresholdInfoVal.textContent = thr;
        // webcam count — animate
        const wc = (msg.cameras || []).find(c => c.camera === 'webcam');
        if (wc) animateCount(webcamPeopleEl, wc.count);
        // missing badge
        if (msg.missing_active) missingBadge.classList.remove('hidden');
        else missingBadge.classList.add('hidden');
      } else if (msg.type === 'ALERT') {
        showAlert(msg.payload);
      }
    } catch (e) { console.error(e); }
  };
  ws.onclose = () => {
    wsStatusEl.innerHTML = '<span class="dot dot-off"></span> Disconnected';
    setTimeout(setupWS, 2500);
  };
}
setupWS();

// ── Alerts ────────────────────────────────────────────────────────────────────
const alertClsMap = {
  CROWD_DENSITY:       'alert-density',
  SUDDEN_SURGE:        'alert-surge',
  PUSHING_LIKELY:      'alert-push',
  MISSING_PERSON_FOUND:'alert-missing',
  INFO:                'alert-info',
};

function showAlert(alert) {
  const cls = alertClsMap[alert.type] || 'alert-info';
  const el = document.createElement('div');
  el.className = `alert-item ${cls}`;
  const ts = alert.timestamp
    ? new Date(alert.timestamp * 1000).toLocaleTimeString()
    : new Date().toLocaleTimeString();
  const extra = alert.second !== undefined ? ` · ${alert.second}s` : '';
  el.innerHTML = `
    <div class="alert-type">${alert.type || 'INFO'}</div>
    <div class="alert-msg">${alert.message || JSON.stringify(alert)}</div>
    <div class="alert-time">${ts}${extra} · ${alert.camera || ''}</div>
  `;
  alertsFeed.prepend(el);
  while (alertsFeed.children.length > 60) alertsFeed.lastChild.remove();

  // flash header for critical
  if (alert.type === 'MISSING_PERSON_FOUND') {
    document.querySelector('.header').classList.add('flash-critical');
    setTimeout(() => document.querySelector('.header').classList.remove('flash-critical'), 3000);
  }
}

function addInfo(msg) { showAlert({ type: 'INFO', message: msg, timestamp: Date.now() / 1000 }); }
clearAlertsBtn.addEventListener('click', () => { alertsFeed.innerHTML = ''; });

// ── Webcam ────────────────────────────────────────────────────────────────────
webcamStartBtn.addEventListener('click', async () => {
  webcamStartBtn.disabled = true;
  webcamStatusEl.textContent = 'Starting camera...';
  webcamStatusEl.className = 'status-bar status-off';
  try {
    const res = await fetch('/webcam/start', { method: 'POST' });
    const j = await res.json();
    if (j.ok) {
      webcamStopBtn.disabled = false;
      webcamStatusEl.textContent = j.status || 'Camera running — detecting people...';
      webcamStatusEl.className = 'status-bar status-on';
      webcamCountEl.classList.remove('hidden');
      addInfo('Webcam started');
    } else {
      webcamStartBtn.disabled = false;
      webcamStatusEl.textContent = 'Camera error — see alerts';
      webcamStatusEl.className = 'status-bar status-off';
      addInfo('Webcam error: ' + (j.error || 'unknown'));
    }
  } catch (err) {
    webcamStartBtn.disabled = false;
    webcamStatusEl.textContent = 'Camera error — see alerts';
    webcamStatusEl.className = 'status-bar status-off';
    addInfo('Webcam error: ' + err.message);
  }
});

webcamStopBtn.addEventListener('click', async () => {
  webcamStopBtn.disabled = true;
  await fetch('/webcam/stop', { method: 'POST' });
  webcamStartBtn.disabled = false;
  webcamStatusEl.textContent = 'Camera is off';
  webcamStatusEl.className = 'status-bar status-off';
  webcamCountEl.classList.add('hidden');
  webcamPeopleEl.textContent = '0';
  addInfo('Webcam stopped');
});

(async () => {
  try {
    const j = await (await fetch('/webcam/status')).json();
    if (j.running) {
      webcamStartBtn.disabled = true; webcamStopBtn.disabled = false;
      webcamStatusEl.textContent = 'Camera running — detecting people...';
      webcamStatusEl.className = 'status-bar status-on';
      webcamCountEl.classList.remove('hidden');
    }
  } catch (_) {}
})();

// ── Threshold controls ────────────────────────────────────────────────────────
setThresholdBtn.addEventListener('click', async () => {
  const val = parseInt(thresholdInput.value, 10);
  if (isNaN(val) || val < 1) return;
  const fd = new FormData(); fd.append('value', val);
  const j = await (await fetch('/threshold/set', { method: 'POST', body: fd })).json();
  if (j.ok) {
    thresholdDisplay.textContent = j.threshold;
    thresholdInfoVal.textContent = j.threshold;
    window._currentThreshold = j.threshold;
    alertModeEl.textContent = 'Manual';
    autoToggle.checked = false;
    areaCalcInfo.classList.add('hidden');
    addInfo(`Manual threshold set to ${j.threshold}`);
  }
});

setAreaBtn.addEventListener('click', async () => {
  const val = parseFloat(areaInput.value);
  if (isNaN(val) || val <= 0) return;
  const fd = new FormData(); fd.append('area_sqkm', val);
  const j = await (await fetch('/threshold/area', { method: 'POST', body: fd })).json();
  if (j.ok) {
    thresholdDisplay.textContent = j.threshold;
    thresholdInfoVal.textContent = j.threshold;
    window._currentThreshold = j.threshold;
    alertModeEl.textContent = 'Area';
    autoToggle.checked = false;
    areaCalcInfo.classList.remove('hidden');
    areaCalcInfo.innerHTML =
      `Area: <strong>${val} km²</strong> → WHO density (4/m²) → threshold: <strong>${j.threshold}</strong>`;
    addInfo(`Area threshold: ${val} km² → ${j.threshold} people`);
  }
});

autoToggle.addEventListener('change', async () => {
  const fd = new FormData(); fd.append('enabled', autoToggle.checked);
  const j = await (await fetch('/threshold/auto', { method: 'POST', body: fd })).json();
  alertModeEl.textContent = j.auto ? 'Rolling Auto' : 'Manual';
  areaCalcInfo.classList.add('hidden');
  addInfo(j.auto ? 'Rolling auto threshold enabled' : 'Auto threshold disabled');
});

(async () => {
  try {
    const j = await (await fetch('/threshold')).json();
    thresholdInput.value = j.threshold;
    thresholdDisplay.textContent = j.threshold;
    thresholdInfoVal.textContent = j.threshold;
    window._currentThreshold = j.threshold;
    autoToggle.checked = j.auto;
    alertModeEl.textContent = j.mode === 'area' ? 'Area' : j.auto ? 'Rolling Auto' : 'Manual';
    if (j.area_sqkm > 0) {
      areaInput.value = j.area_sqkm;
      areaCalcInfo.classList.remove('hidden');
      areaCalcInfo.innerHTML = `Area: <strong>${j.area_sqkm} km²</strong> → threshold: <strong>${j.threshold}</strong>`;
    }
  } catch (_) {}
})();

// ── Missing person ────────────────────────────────────────────────────────────
setMissingBtn.addEventListener('click', async () => {
  const f = missingSetFile.files[0];
  if (!f) { addInfo('Choose a photo first'); return; }
  setMissingBtn.disabled = true;
  const fd = new FormData(); fd.append('file', f);
  try {
    const j = await (await fetch('/missing/set', { method: 'POST', body: fd })).json();
    if (j.ok) {
      missingStatus.classList.remove('hidden');
      missingStatus.className = 'missing-status status-active';
      missingStatus.textContent = '🔴 Tracking active — alerts will fire on match';
      clearMissingBtn.classList.remove('hidden');
      missingBadge.classList.remove('hidden');
      addInfo('Missing person tracking activated');
    } else {
      addInfo('Error: ' + (j.error || 'unknown'));
    }
  } catch (err) { addInfo('Error: ' + err.message); }
  setMissingBtn.disabled = false;
});

clearMissingBtn.addEventListener('click', async () => {
  await fetch('/missing/clear', { method: 'POST' });
  missingStatus.classList.add('hidden');
  clearMissingBtn.classList.add('hidden');
  missingBadge.classList.add('hidden');
  addInfo('Missing person tracking cleared');
});

searchMissingBtn.addEventListener('click', async () => {
  const f = missingSearchFile.files[0];
  if (!f) { addInfo('Choose an image to search'); return; }
  searchMissingBtn.disabled = true;
  missingResults.innerHTML = '<div class="searching">Searching...</div>';
  const fd = new FormData(); fd.append('file', f);
  try {
    const j = await (await fetch('/missing/search', { method: 'POST', body: fd })).json();
    missingResults.innerHTML = '';
    if (j.results && j.results.length) {
      j.results.forEach(r => {
        const d = document.createElement('div'); d.className = 'missing-item';
        const ts = r.timestamp ? new Date(r.timestamp * 1000).toLocaleString() : 'N/A';
        const src = r.video ? `video: ${r.video}` : (r.camera || '');
        d.innerHTML = `<b>Source:</b> ${src} &nbsp; <b>Time:</b> ${ts} &nbsp; <b>Dist:</b> ${r.distance?.toFixed(3) ?? 'N/A'}`;
        missingResults.appendChild(d);
      });
    } else {
      missingResults.innerHTML = '<div class="no-results">No matches found in index</div>';
    }
  } catch (err) {
    missingResults.innerHTML = `<div style="color:var(--red);font-size:12px">${err.message}</div>`;
  }
  searchMissingBtn.disabled = false;
});
