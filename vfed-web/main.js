
/* ============================================================
   STATE
   ============================================================ */
const state = {
    theme: localStorage.getItem('theme') || 'dark',
    scatterColorBy: 'lcoe',
    sweepResults: [],        // array of result objects
    bestResult: null,
    objective: 'lcoe',
    selectedRowIndex: -1,
    scatterChart: null,
    worker: null,
    runStartTime: 0,
    progressTimer: null,
    presets: [],

    // Default coarse parameter ranges (avoid excess computation)
    defaultRanges: {
        'pv_area':        { min: 0,   max: 500, step: 50,  label: 'PV Area (m²)',         cat: 'PV/Battery' },
        'battery':        { min: 0,   max: 200, step: 50,  label: 'Battery (kWh)',        cat: 'PV/Battery' },
        'T_light':        { min: 20,  max: 26,  step: 2,   label: 'Light Temp (°C)',      cat: 'Climate' },
        'T_dark':         { min: 14,  max: 22,  step: 2,   label: 'Dark Temp (°C)',       cat: 'Climate' },
        'photoperiod_hours': { min: 14, max: 18, step: 2, label: 'Photoperiod (h)',      cat: 'Lighting' },
        'ppfd_target':    { min: 150, max: 300, step: 50, label: 'PPFD (µmol/m²/s)',     cat: 'Lighting' },
        'RH':             { min: 60,  max: 80,  step: 10,  label: 'RH (%)',               cat: 'Climate' },
        'co2_ppm':        { min: 600, max: 1200,step: 200, label: 'CO₂ (ppm)',            cat: 'Climate' },
        'crop_cycle_days':{ min: 25,  max: 45,  step: 5,   label: 'Crop Cycle (days)',    cat: 'Crop' },
        'efficacy':       { min: 2.5, max: 3.5, step: 0.5,  label: 'LED Efficacy (µmol/J)',cat: 'Lighting' },
    },
    activeRanges: {}  // key -> {min, max, step}
};

/* ============================================================
   WEATHER CACHING (localStorage)
   ============================================================ */
const WEATHER_CACHE_PREFIX = 'vfed_weather_';
const WEATHER_CACHE_TTL = 30 * 24 * 60 * 60 * 1000; // 30 days

function getWeatherCacheKey(lat, lon, year) {
    return `${WEATHER_CACHE_PREFIX}${lat.toFixed(4)}_${lon.toFixed(4)}_${year}`;
}

function getCachedWeather(lat, lon, year) {
    const key = getWeatherCacheKey(lat, lon, year);
    const cached = localStorage.getItem(key);
    if (!cached) return null;
    try {
        const { data, ts } = JSON.parse(cached);
        if (Date.now() - ts < WEATHER_CACHE_TTL) return data;
    } catch { }
    return null;
}

function setCachedWeather(lat, lon, year, data) {
    const key = getWeatherCacheKey(lat, lon, year);
    localStorage.setItem(key, JSON.stringify({ data, ts: Date.now() }));
}

/* ============================================================
   TOAST NOTIFICATIONS
   ============================================================ */
const Toast = {
    container: null,
    init() { this.container = document.getElementById('toast-container'); },
    show(message, type = 'info', duration = 4000) {
        if (!this.container) this.init();
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.innerHTML = `
            <div class="toast-content">${message}</div>
            <button class="toast-dismiss" onclick="this.parentElement.remove()">×</button>
        `;
        this.container.appendChild(toast);
        if (duration > 0) setTimeout(() => this.dismiss(toast), duration);
    },
    dismiss(toast) {
        toast.classList.add('dismissing');
        setTimeout(() => toast.remove(), 300);
    },
    error(msg) { this.show(msg, 'error', 6000); },
    success(msg) { this.show(msg, 'success', 3000); },
    warning(msg) { this.show(msg, 'warning', 4000); },
    info(msg) { this.show(msg, 'info', 4000); }
};

/* ============================================================
   THEME
   ============================================================ */
function applyTheme(theme) {
    document.documentElement.className = theme;
    document.getElementById('theme-toggle').textContent = theme === 'dark' ? '☀️' : '🌙';
    state.theme = theme;
    localStorage.setItem('theme', theme);
    if (state.scatterChart) updateScatterChart();
}

/* ============================================================
   WORKER COMMUNICATION
   ============================================================ */
function initWorker() {
    state.worker = new Worker('worker.js');
    
    state.worker.onmessage = ({ data }) => {
        if (data.type === 'worker_loaded') {
            // Worker script loaded, now init Pyodide
            state.worker.postMessage({ type: 'init' });
            state.worker.postMessage({ type: 'list_presets' });
        } else if (data.type === 'ready') {
            updateRunButton(false, 'Run Simulation');
        } else if (data.type === 'status') {
            updateProgressText(data.message);
        } else if (data.type === 'presets') {
            state.presets = data.presets;
            populatePresetDropdown();
        } else if (data.type === 'progress') {
            updateProgress(data.current, data.total, data.result);
        } else if (data.type === 'complete') {
            onSweepComplete(data);
        } else if (data.type === 'error') {
            onSweepError(data.message);
        }
    };
    
    state.worker.onerror = (e) => {
        console.error('Worker error:', e);
        Toast.error('Worker error: ' + e.message);
        updateRunButton(false, 'Run Simulation');
        hideProgress();
    };
}

function updateRunButton(disabled, text) {
    const btn = document.getElementById('run-btn');
    const txt = document.getElementById('run-btn-text');
    btn.disabled = disabled;
    if (text) txt.textContent = text;
}

function showProgress() {
    document.getElementById('progress-section').classList.add('visible');
    document.getElementById('scatter-loading').classList.remove('hidden');
    document.getElementById('scatter-empty').classList.add('hidden');
    document.getElementById('scatter-error').classList.add('hidden');
    state.runStartTime = Date.now();
    state.progressTimer = setInterval(updateElapsedTime, 1000);
}

function hideProgress() {
    document.getElementById('progress-section').classList.remove('visible');
    document.getElementById('scatter-loading').classList.add('hidden');
    if (state.progressTimer) clearInterval(state.progressTimer);
}

function updateProgressText(msg) {
    document.getElementById('progress-text').innerHTML = `<span class="progress-spinner"></span>${msg}`;
}

function updateElapsedTime() {
    const elapsed = Math.floor((Date.now() - state.runStartTime) / 1000);
    const m = Math.floor(elapsed / 60).toString().padStart(2, '0');
    const s = (elapsed % 60).toString().padStart(2, '0');
    document.getElementById('progress-time').textContent = `${m}:${s}`;
}

function updateProgress(current, total, result) {
    const pct = total > 0 ? Math.round((current / total) * 100) : 0;
    document.getElementById('progress-fill').style.width = `${pct}%`;
    document.getElementById('progress-text').innerHTML = `<span class="progress-spinner"></span>Design ${current} / ${total}`;
    
    // Add result to sweep results incrementally
    if (result) {
        state.sweepResults.push(result);
        // Update best so far
        if (!state.bestResult || result[state.objective] < state.bestResult[state.objective]) {
            state.bestResult = result;
            updateBestCards(result);
        }
        // Live-update scatter
        addScatterPoint(result);
    }
}

function onSweepComplete(data) {
    hideProgress();
    updateRunButton(false, 'Run Simulation');
    
    state.sweepResults = data.results || [];
    state.bestResult = data.best;
    state.objective = data.objective;
    
    if (state.sweepResults.length === 0) {
        Toast.warning('No results returned from sweep');
        document.getElementById('scatter-empty').classList.remove('hidden');
        return;
    }
    
    // Sort by objective
    state.sweepResults.sort((a, b) => (a[state.objective] || Infinity) - (b[state.objective] || Infinity));
    
    // Update all UI
    updateBestCards(state.bestResult);
    initScatterChart();
    populateResultsTable();
    document.getElementById('metrics-row').style.display = 'grid';
    document.getElementById('table-empty').style.display = 'none';
    
    Toast.success(`Sweep complete: ${state.sweepResults.length} designs evaluated`);
}

function onSweepError(msg) {
    hideProgress();
    updateRunButton(false, 'Run Simulation');
    document.getElementById('scatter-error').classList.remove('hidden');
    Toast.error('Simulation failed: ' + msg);
}

/* ============================================================
   PRESET HANDLING
   ============================================================ */
function populatePresetDropdown() {
    const select = document.getElementById('preset-select');
    select.innerHTML = '<option value="">-- Load Preset --</option>';
    state.presets.forEach(p => {
        const opt = document.createElement('option');
        opt.value = p.id;
        opt.textContent = p.label;
        select.appendChild(opt);
    });
    select.addEventListener('change', onPresetChange);
}

async function onPresetChange(e) {
    const presetId = e.target.value;
    if (!presetId) return;
    
    try {
        const res = await fetch(`https://raw.githubusercontent.com/VFLab/vertical-farm-energy-designer/main/src/design/presets.py`);
        // Actually, we should get the preset from the worker
        state.worker.postMessage({ type: 'get_preset', preset: presetId });
        // For now, just show a message
        Toast.info(`Preset loading not yet implemented for ${presetId}`);
    } catch (err) {
        Toast.error('Failed to load preset');
    }
}

/* For now, embed a few known presets directly */
const BUILTIN_PRESETS = {
    '609': {
        label: '609 — Fengxian Strawberry PFAL',
        yaml: `site:
  lat: 31.0
  lon: 121.5
  year: 2023
  tz_hours: 8
  tilt: 10
  azimuth: 180
envelope:
  U_wall_A: 0.35
  A_window: 0.0
  eta_solar: 0.7
  ach: 0.5
  permeance: 0.0
  rho_air: 1.2
  cp_air: 1005
  V_room: 5000
  C_z: 1200000.0
led:
  auto_deduce: true
  ppfd_target: 200
  efficacy: 2.8
  light_start_hour: 6
  photoperiod_hours: 16
  heat_fraction: 0.8
  covered_area: 100
hvac:
  P_rated_w: 50000
  cop_mode: "constant"
  cop_value: 3.5
  heat_mode: "heat_pump"
  P_rated_heat_w: 50000
  deadband_c: 1.0
  min_on_s: 300
  min_off_s: 300
  fan_power_w: 500
  shr_BF: 0.15
  tau_q: 60
  tau_m: 120
deh:
  P_ref_w: 8000
  poly_e: [0.0, 0.0, 0.0, 0.0]
  T_mean: 24
  T_std: 3
  W_mean: 0.012
  W_std: 0.003
  eta_ref: 1.2
  eta_max: 2.0
  ah_min: 0.004
  ah_ref: 0.01
  deadband_rh: 5.0
  min_on_s: 300
  min_off_s: 300
  fan_power_w: 200
  tau_q: 60
  tau_m: 120
setpoints:
  T_light: 24
  T_dark: 20
  RH: 70
  co2_ppm: 800
  crop_cycle_days: 35
pv:
  eta_pv: 0.20
  area_to_power: 180
  N_s: 20
  I_sc_stc: 10.5
  V_oc_stc: 42
  I_mp_stc: 10
  V_mp_stc: 35
  alpha_sc: 0.0005
  beta_voc: -0.0012
  NOCT: 45
  eta_inv: 0.96
  C_pv: 800
  degradation: 0.005
battery:
  c_energy: 400
  c_rate: 0.5
  eta_ch: 0.95
  eta_dis: 0.95
  soc_min: 0.1
  soc_max: 0.9
  cycle_life: 6000
  maintenance: 0.01
tariff:
  hourly_prices: [0.3,0.3,0.3,0.3,0.3,0.3,0.6,0.8,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,0.8,0.6,0.4,0.3,0.3,0.3]
  export_price: 0.25
equipment_power_w: 2000
interest_rate: 0.05
currency: CNY
exchange_rate: 1.0
space:
  timestep_s: 600
  parameter_ranges: {}
  objective: lcoe
`
    },
    'lettuce_standard': {
        label: 'Lettuce — Standard PFAL',
        yaml: `site:
  lat: 35.68
  lon: 139.69
  year: 2023
  tz_hours: 9
  tilt: 10
  azimuth: 180
envelope:
  U_wall_A: 0.3
  A_window: 0.0
  eta_solar: 0.7
  ach: 0.3
  permeance: 0.0
  rho_air: 1.2
  cp_air: 1005
  V_room: 3000
  C_z: 800000.0
led:
  auto_deduce: true
  ppfd_target: 180
  efficacy: 3.0
  light_start_hour: 6
  photoperiod_hours: 16
  heat_fraction: 0.8
  covered_area: 80
hvac:
  P_rated_w: 40000
  cop_mode: "constant"
  cop_value: 3.8
  heat_mode: "heat_pump"
  P_rated_heat_w: 40000
  deadband_c: 1.0
  min_on_s: 300
  min_off_s: 300
  fan_power_w: 400
  shr_BF: 0.12
  tau_q: 60
  tau_m: 120
deh:
  P_ref_w: 6000
  poly_e: [0.0, 0.0, 0.0, 0.0]
  T_mean: 22
  T_std: 2
  W_mean: 0.01
  W_std: 0.002
  eta_ref: 1.3
  eta_max: 2.2
  ah_min: 0.003
  ah_ref: 0.008
  deadband_rh: 5.0
  min_on_s: 300
  min_off_s: 300
  fan_power_w: 150
  tau_q: 60
  tau_m: 120
setpoints:
  T_light: 22
  T_dark: 18
  RH: 65
  co2_ppm: 1000
  crop_cycle_days: 30
pv:
  eta_pv: 0.21
  area_to_power: 190
  N_s: 22
  I_sc_stc: 11.0
  V_oc_stc: 44
  I_mp_stc: 10.5
  V_mp_stc: 37
  alpha_sc: 0.0005
  beta_voc: -0.0012
  NOCT: 45
  eta_inv: 0.965
  C_pv: 750
  degradation: 0.005
battery:
  c_energy: 380
  c_rate: 0.5
  eta_ch: 0.95
  eta_dis: 0.95
  soc_min: 0.1
  soc_max: 0.9
  cycle_life: 6000
  maintenance: 0.01
tariff:
  hourly_prices: [0.25,0.25,0.25,0.25,0.25,0.25,0.5,0.7,0.9,0.9,0.9,0.9,0.9,0.9,0.9,0.9,0.9,0.9,0.7,0.5,0.35,0.25,0.25,0.25]
  export_price: 0.2
equipment_power_w: 1500
interest_rate: 0.05
currency: USD
exchange_rate: 1.0
space:
  timestep_s: 600
  parameter_ranges: {}
  objective: lcoe
`
    }
};

function populatePresetDropdown() {
    const select = document.getElementById('preset-select');
    select.innerHTML = '<option value="">-- Load Preset --</option>';
    Object.entries(BUILTIN_PRESETS).forEach(([id, p]) => {
        const opt = document.createElement('option');
        opt.value = id;
        opt.textContent = p.label;
        select.appendChild(opt);
    });
    select.addEventListener('change', onPresetChange);
}

function onPresetChange(e) {
    const presetId = e.target.value;
    if (!presetId) return;
    const preset = BUILTIN_PRESETS[presetId];
    if (preset) {
        document.getElementById('yaml-editor').value = preset.yaml;
        Toast.success(`Loaded preset: ${preset.label}`);
    }
}

/* ============================================================
   PARAMETER RANGE EDITOR
   ============================================================ */
function initParamRanges() {
    state.activeRanges = { ...state.defaultRanges };
    renderParamRows();
}

function renderParamRows() {
    const container = document.getElementById('param-ranges');
    container.innerHTML = '';
    Object.entries(state.activeRanges).forEach(([key, r]) => {
        container.appendChild(createParamRow(key, r));
    });
}

function createParamRow(key, r) {
    const row = document.createElement('div');
    row.className = 'param-row';
    row.dataset.key = key;
    row.innerHTML = `
        <label style="min-width:140px;">${r.label}</label>
        <input type="number" class="param-min" value="${r.min}" step="any" title="Min">
        <input type="number" class="param-max" value="${r.max}" step="any" title="Max">
        <input type="number" class="param-step" value="${r.step}" step="any" title="Step">
        <button class="param-remove" title="Remove" data-key="${key}">×</button>
    `;
    row.querySelector('.param-remove').addEventListener('click', () => removeParam(key));
    row.querySelectorAll('input').forEach(input => {
        input.addEventListener('change', () => updateParamFromRow(key, row));
    });
    return row;
}

function updateParamFromRow(key, row) {
    const min = parseFloat(row.querySelector('.param-min').value);
    const max = parseFloat(row.querySelector('.param-max').value);
    const step = parseFloat(row.querySelector('.param-step').value);
    if (!isNaN(min) && !isNaN(max) && !isNaN(step) && max > min && step > 0) {
        state.activeRanges[key] = { ...state.activeRanges[key], min, max, step };
    }
}

function removeParam(key) {
    delete state.activeRanges[key];
    renderParamRows();
}

function openParamModal() {
    const modal = document.getElementById('param-modal');
    const list = document.getElementById('param-list');
    const search = document.getElementById('param-search');
    
    // Group by category
    const byCat = {};
    Object.entries(state.defaultRanges).forEach(([key, r]) => {
        if (state.activeRanges[key]) return; // already added
        if (!byCat[r.cat]) byCat[r.cat] = [];
        byCat[r.cat].push({ key, ...r });
    });
    
    list.innerHTML = '';
    Object.entries(byCat).forEach(([cat, params]) => {
        const catDiv = document.createElement('div');
        catDiv.style.marginBottom = '12px';
        catDiv.innerHTML = `<div class="cat" style="padding:4px 8px;">${cat}</div>`;
        params.forEach(p => {
            const opt = document.createElement('div');
            opt.className = 'modal-option';
            opt.dataset.key = p.key;
            opt.innerHTML = `<span class="name">${p.label}</span><span class="range">${p.min}–${p.max} step ${p.step}</span>`;
            opt.addEventListener('click', () => addParam(p.key));
            catDiv.appendChild(opt);
        });
        list.appendChild(catDiv);
    });
    
    search.value = '';
    search.oninput = () => filterParams(search.value);
    modal.classList.add('visible');
}

function filterParams(query) {
    const items = document.querySelectorAll('.modal-option');
    const q = query.toLowerCase();
    items.forEach(item => {
        const text = item.textContent.toLowerCase();
        item.style.display = text.includes(q) ? 'flex' : 'none';
    });
}

function addParam(key) {
    if (state.activeRanges[key]) return;
    state.activeRanges[key] = { ...state.defaultRanges[key] };
    renderParamRows();
    closeParamModal();
}

function closeParamModal() {
    document.getElementById('param-modal').classList.remove('visible');
}

function getRangesForWorker() {
    const out = {};
    Object.entries(state.activeRanges).forEach(([key, r]) => {
        out[key] = [r.min, r.max, r.step];
    });
    return out;
}

/* ============================================================
   SCATTER CHART (LCOE Design Space)
   ============================================================ */
function initScatterChart() {
    const ctx = document.getElementById('scatter-chart').getContext('2d');
    
    if (state.scatterChart) {
        state.scatterChart.destroy();
    }
    
    // Calculate color domain
    const values = state.sweepResults.map(r => r[state.scatterColorBy]).filter(v => v != null && isFinite(v));
    const minVal = Math.min(...values);
    const maxVal = Math.max(...values);
    
    state.scatterChart = new Chart(ctx, {
        type: 'scatter',
        data: {
            datasets: [
                {
                    label: 'Design Points',
                    data: state.sweepResults.map((r, i) => ({
                        x: r.pv_area,
                        y: r.battery_kwh,
                        index: i
                    })),
                    backgroundColor: state.sweepResults.map(r => valueToColor(r[state.scatterColorBy], minVal, maxVal)),
                    borderColor: state.sweepResults.map(r => valueToColor(r[state.scatterColorBy], minVal, maxVal, 0.5)),
                    borderWidth: 1,
                    pointRadius: 6,
                    pointHoverRadius: 10,
                },
                {
                    label: 'Best Design',
                    data: state.bestResult ? [{ x: state.bestResult.pv_area, y: state.bestResult.battery_kwh }] : [],
                    backgroundColor: '#ffd700',
                    borderColor: '#ffd700',
                    borderWidth: 2,
                    pointRadius: 12,
                    pointStyle: 'star',
                    pointRotation: 0,
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'nearest', intersect: true },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (ctx) => {
                            const r = state.sweepResults[ctx.raw.index];
                            if (!r) return '';
                            return [
                                `PV Area: ${r.pv_area} m²`,
                                `Battery: ${r.battery_kwh} kWh`,
                                `LCOE: ${r.lcoe?.toFixed(4) ?? 'N/A'} $/kWh`,
                                `kWh/kg fresh: ${r.kwh_per_kg_fresh?.toFixed(2) ?? 'N/A'}`,
                                `$/kg fresh: ${r.cost_per_kg_fresh?.toFixed(2) ?? 'N/A'}`,
                                `Capital: $${(r.capital_total/1000).toFixed(0)}k`,
                            ];
                        }
                    }
                }
            },
            scales: {
                x: {
                    title: { display: true, text: 'PV Area (m²)', color: '#71717a', font: { size: 11 } },
                    grid: { display: false },
                    ticks: { color: '#71717a', font: { size: 10 } }
                },
                y: {
                    title: { display: true, text: 'Battery Capacity (kWh)', color: '#71717a', font: { size: 11 } },
                    grid: { display: false },
                    ticks: { color: '#71717a', font: { size: 10 } }
                }
            },
            onClick: (e, elements) => {
                if (elements.length > 0) {
                    const idx = elements[0].index;
                    if (elements[0].datasetIndex === 0) { // main dataset
                        selectResult(idx);
                    }
                }
            }
        }
    });
    
    document.getElementById('scatter-empty').classList.add('hidden');
}

function addScatterPoint(result) {
    if (!state.scatterChart) return;
    const values = state.sweepResults.map(r => r[state.scatterColorBy]).filter(v => v != null && isFinite(v));
    const minVal = Math.min(...values);
    const maxVal = Math.max(...values);
    const color = valueToColor(result[state.scatterColorBy], minVal, maxVal);
    
    state.scatterChart.data.datasets[0].data.push({
        x: result.pv_area,
        y: result.battery_kwh,
        index: state.sweepResults.length - 1
    });
    state.scatterChart.data.datasets[0].backgroundColor.push(color);
    state.scatterChart.data.datasets[0].borderColor.push(valueToColor(result[state.scatterColorBy], minVal, maxVal, 0.5));
    state.scatterChart.update('none');
}

function updateScatterChart() {
    if (!state.scatterChart || state.sweepResults.length === 0) return;
    
    const values = state.sweepResults.map(r => r[state.scatterColorBy]).filter(v => v != null && isFinite(v));
    const minVal = Math.min(...values);
    const maxVal = Math.max(...values);
    
    state.scatterChart.data.datasets[0].backgroundColor = state.sweepResults.map(r => valueToColor(r[state.scatterColorBy], minVal, maxVal));
    state.scatterChart.data.datasets[0].borderColor = state.sweepResults.map(r => valueToColor(r[state.scatterColorBy], minVal, maxVal, 0.5));
    state.scatterChart.data.datasets[1].data = state.bestResult ? [{ x: state.bestResult.pv_area, y: state.bestResult.battery_kwh }] : [];
    state.scatterChart.update();
}

function valueToColor(val, min, max, alpha = 1) {
    if (val == null || !isFinite(val) || max <= min) return `rgba(128,128,128,${alpha})`;
    const t = Math.max(0, Math.min(1, (val - min) / (max - min)));
    // Green (120°) → Yellow (60°) → Red (0°)
    const hue = 120 * (1 - t);
    return `hsla(${hue}, 70%, 45%, ${alpha})`;
}

function selectResult(index) {
    const r = state.sweepResults[index];
    if (!r) return;
    
    state.selectedRowIndex = index;
    
    // Update table selection
    document.querySelectorAll('#results-body tr').forEach((tr, i) => {
        tr.classList.toggle('best-row', i === index);
    });
    
    // Update cost breakdown
    updateCostBreakdown(r);
    
    // Update scatter best point
    if (state.scatterChart) {
        state.scatterChart.data.datasets[1].data = [{ x: r.pv_area, y: r.battery_kwh }];
        state.scatterChart.update('none');
    }
}

document.getElementById('scatter-color-tabs').addEventListener('click', (e) => {
    const btn = e.target.closest('.chart-tab');
    if (!btn) return;
    document.querySelectorAll('#scatter-color-tabs .chart-tab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    state.scatterColorBy = btn.dataset.color;
    updateScatterChart();
});

/* ============================================================
   COST BREAKDOWN (Horizontal Stacked Bar)
   ============================================================ */
function updateCostBreakdown(r) {
    const container = document.getElementById('cost-breakdown');
    const components = [
        { key: 'capital_led', label: 'LED', color: 'rgba(72,121,128,0.9)' },
        { key: 'capital_hvac', label: 'HVAC', color: 'rgba(59,130,246,0.9)' },
        { key: 'capital_deh', label: 'Dehumidifier', color: 'rgba(168,85,247,0.9)' },
        { key: 'capital_pv', label: 'PV', color: 'rgba(249,115,22,0.9)' },
        { key: 'capital_battery', label: 'Battery', color: 'rgba(234,179,8,0.9)' },
        { key: 'capital_equipment', label: 'Equipment', color: 'rgba(107,114,128,0.9)' },
        { key: 'capital_envelope', label: 'Envelope', color: 'rgba(75,85,99,0.9)' },
    ];
    
    const total = r.capital_total || 1;
    let html = '';
    components.forEach(c => {
        const val = r[c.key] || 0;
        const pct = (val / total * 100).toFixed(1);
        html += `
            <div class="cost-item">
                <div class="cost-label">
                    <span class="cost-name" style="color:${c.color}">${c.label}</span>
                    <span class="cost-value">$${(val/1000).toFixed(0)}k (${pct}%)</span>
                </div>
                <div class="cost-bar-container">
                    <div class="cost-bar" style="width:${pct}%;background:${c.color}"></div>
                </div>
            </div>
        `;
    });
    container.innerHTML = html;
}

/* ============================================================
   RESULTS TABLE
   ============================================================ */
function populateResultsTable() {
    const tbody = document.getElementById('results-body');
    tbody.innerHTML = '';
    
    state.sweepResults.forEach((r, i) => {
        const tr = document.createElement('tr');
        if (i === 0) tr.classList.add('best-row');
        tr.innerHTML = `
            <td${i === 0 ? ' class="best-cell"' : ''}>${r.lcoe?.toFixed(4) ?? '—'}</td>
            <td>${r.pv_area ?? '—'}</td>
            <td>${r.battery_kwh ?? '—'}</td>
            <td>${r.kwh_per_kg_fresh?.toFixed(2) ?? '—'}</td>
            <td>${r.cost_per_kg_fresh?.toFixed(2) ?? '—'}</td>
            <td>${(r.capital_total/1000).toFixed(0)}k</td>
            <td>${(r.annual_grid_cost/1000).toFixed(0)}k</td>
        `;
        tr.addEventListener('click', () => selectResult(i));
        tbody.appendChild(tr);
    });
    
    // Add sort handlers
    document.querySelectorAll('#results-table th[data-sort]').forEach(th => {
        th.addEventListener('click', () => sortTable(th.dataset.sort));
    });
}

let sortDir = {};
function sortTable(key) {
    const dir = (sortDir[key] = - (sortDir[key] || 1));
    state.sweepResults.sort((a, b) => {
        const va = a[key] ?? (dir > 0 ? Infinity : -Infinity);
        const vb = b[key] ?? (dir > 0 ? Infinity : -Infinity);
        return dir * (va - vb);
    });
    // Update sort indicators
    document.querySelectorAll('#results-table th .sort-indicator').forEach(si => si.textContent = '');
    const active = document.querySelector(`#results-table th[data-sort="${key}"] .sort-indicator`);
    if (active) active.textContent = dir > 0 ? '▲' : '▼';
    populateResultsTable();
}

function selectResult(index) {
    selectResult(index);
    // Scroll to row
    const row = document.querySelector(`#results-body tr:nth-child(${index + 1})`);
    if (row) row.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

/* ============================================================
   BEST CARDS
   ============================================================ */
function updateBestCards(r) {
    document.getElementById('val-lcoe').textContent = r.lcoe?.toFixed(4) ?? '—';
    document.getElementById('val-pv').textContent = r.pv_area ?? '—';
    document.getElementById('val-bat').textContent = r.battery_kwh ?? '—';
    document.getElementById('val-kwhkg').textContent = r.kwh_per_kg_fresh?.toFixed(2) ?? '—';
}

/* ============================================================
   RUN SIMULATION
   ============================================================ */
function runSimulation() {
    const yaml = document.getElementById('yaml-editor').value.trim();
    if (!yaml) {
        Toast.error('Please provide a project YAML configuration');
        return;
    }
    
    const ranges = getRangesForWorker();
    if (Object.keys(ranges).length === 0) {
        Toast.warning('No parameter ranges defined — running single-point evaluation');
    }
    
    const objective = document.getElementById('objective-select').value;
    
    // Reset state
    state.sweepResults = [];
    state.bestResult = null;
    state.objective = objective;
    state.selectedRowIndex = -1;
    state.scatterColorBy = objective; // default color by objective
    
    // UI
    updateRunButton(true, 'Running...');
    showProgress();
    document.getElementById('metrics-row').style.display = 'none';
    document.getElementById('table-empty').style.display = 'block';
    document.getElementById('scatter-empty').classList.add('hidden');
    document.getElementById('scatter-error').classList.add('hidden');
    document.getElementById('cost-breakdown').innerHTML = '<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;color:var(--text-secondary);">Computing...</div>';
    
    // Clear existing chart
    if (state.scatterChart) {
        state.scatterChart.data.datasets[0].data = [];
        state.scatterChart.data.datasets[0].backgroundColor = [];
        state.scatterChart.data.datasets[0].borderColor = [];
        state.scatterChart.data.datasets[1].data = [];
        state.scatterChart.update('none');
    }
    
    // Send to worker
    state.worker.postMessage({
        type: 'run',
        projectYaml: yaml,
        ranges: ranges,
        objective: objective
    });
}

function resetAll() {
    document.getElementById('yaml-editor').value = '';
    state.activeRanges = { ...state.defaultRanges };
    renderParamRows();
    document.getElementById('objective-select').value = 'lcoe';
    state.sweepResults = [];
    state.bestResult = null;
    state.selectedRowIndex = -1;
    
    if (state.scatterChart) {
        state.scatterChart.data.datasets[0].data = [];
        state.scatterChart.data.datasets[0].backgroundColor = [];
        state.scatterChart.data.datasets[0].borderColor = [];
        state.scatterChart.data.datasets[1].data = [];
        state.scatterChart.update('none');
    }
    
    document.getElementById('metrics-row').style.display = 'none';
    document.getElementById('table-empty').style.display = 'block';
    document.getElementById('scatter-empty').classList.remove('hidden');
    document.getElementById('scatter-loading').classList.add('hidden');
    document.getElementById('scatter-error').classList.add('hidden');
    document.getElementById('cost-breakdown').innerHTML = '<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;color:var(--text-secondary);font-size:0.85rem;">Select a design point to see cost breakdown</div>';
    document.getElementById('results-body').innerHTML = '';
    updateRunButton(false, 'Run Simulation');
    Toast.info('Reset complete');
}

/* ============================================================
   INITIALIZATION
   ============================================================ */
document.addEventListener('DOMContentLoaded', () => {
    // Theme
    applyTheme(state.theme);
    document.getElementById('theme-toggle').addEventListener('click', () => 
        applyTheme(state.theme === 'dark' ? 'light' : 'dark')
    );
    
    // Toast
    Toast.init();
    
    // Worker
    initWorker();
    
    // Param ranges
    initParamRanges();
    document.getElementById('add-param-btn').addEventListener('click', openParamModal);
    document.getElementById('param-modal').addEventListener('click', (e) => {
        if (e.target === e.currentTarget) closeParamModal();
    });
    
    // Run / Reset
    document.getElementById('run-btn').addEventListener('click', runSimulation);
    document.getElementById('reset-btn').addEventListener('click', resetAll);
    
    // Enter key in YAML editor doesn't submit
    document.getElementById('yaml-editor').addEventListener('keydown', (e) => {
        if (e.key === 'Tab') {
            e.preventDefault();
            const start = e.target.selectionStart;
            const end = e.target.selectionEnd;
            e.target.value = e.target.value.substring(0, start) + '  ' + e.target.value.substring(end);
            e.target.selectionStart = e.target.selectionEnd = start + 2;
        }
    });
    
    // Load default preset
    const preset = BUILTIN_PRESETS['609'];
    if (preset) {
        document.getElementById('yaml-editor').value = preset.yaml;
    }
    
    // Initialize empty scatter chart
    initScatterChart();
    
    Toast.info('VFED Design Explorer ready. Load a preset or paste YAML to begin.');
});
