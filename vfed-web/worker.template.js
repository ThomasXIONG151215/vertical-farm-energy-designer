// worker.template.js - Pyodide Web Worker for VFED simulation
// {{SOURCES_JSON}} placeholder replaced by bundle.py

importScripts('https://cdn.jsdelivr.net/pyodide/v0.27.0/full/pyodide.js');

const VFS_SOURCE = {{SOURCES_JSON}};

let pyodide = null;
let initPromise = null;

async function initPyodide() {
    if (pyodide) return;
    if (!initPromise) {
        initPromise = (async () => {
            try {
                self.postMessage({ type: 'status', message: 'Loading Pyodide...' });
                pyodide = await loadPyodide();
                console.log('Pyodide loaded');

                self.postMessage({ type: 'status', message: 'Writing VFED source files...' });
                for (const [path, content] of Object.entries(VFS_SOURCE)) {
                    const absPath = '/' + path;
                    const dir = absPath.substring(0, absPath.lastIndexOf('/'));
                    if (dir) {
                        try { pyodide.FS.mkdirTree(dir); } catch (e) {}
                    }
                    pyodide.FS.writeFile(absPath, content);
                }
                console.log('VFED sources written');

                // Load micropip first (must be separate in Pyodide v0.27+)
                self.postMessage({ type: 'status', message: 'Loading micropip...' });
                try {
                    await pyodide.loadPackage('micropip');
                    console.log('micropip loaded');
                } catch (e) {
                    console.error('micropip loadPackage failed, trying built-in:', e);
                    // micropip may be built-in — verify via Python import
                }

                self.postMessage({ type: 'status', message: 'Loading numpy, pandas...' });
                try {
                    await pyodide.loadPackage(['numpy', 'pandas']);
                    console.log('Base packages loaded: numpy, pandas');
                } catch (e) {
                    console.error('loadPackage failed:', e);
                    self.postMessage({ type: 'error', message: 'loadPackage failed: ' + String(e) });
                    throw e;
                }

                self.postMessage({ type: 'status', message: 'Verifying micropip...' });
                await pyodide.runPythonAsync(`
import micropip
print("micropip OK:", micropip.__version__)
                `);
                console.log('micropip verified');

                self.postMessage({ type: 'status', message: 'Installing pyyaml via micropip...' });
                await pyodide.runPythonAsync(`
import micropip
print("Installing pyyaml...")
await micropip.install("pyyaml")
import yaml
print("pyyaml OK:", yaml.__version__)
print("yaml location:", yaml.__file__)
                `);
                console.log('pyyaml installed and verified');

                await pyodide.runPythonAsync(`
import sys
sys.path.insert(0, '/')
from src.design.sweep import sweep_design
from src.design.project import DesignProject
from src.design.engine import DesignEngine
                `);
                console.log('Pre-imports verified');

                self.postMessage({ type: 'ready' });
            } catch (e) {
                console.error('Init error:', e);
                self.postMessage({ type: 'error', message: String(e) });
                throw e;
            }
        })();
    }
    return initPromise;
}

async function fetchWeatherToCache(projectYaml) {
    // Extract site info from YAML
    const extract = (key) => {
        const m = projectYaml.match(new RegExp('^\\s*' + key + ':\\s*([\\d.]+)', 'm'));
        return m ? parseFloat(m[1]) : null;
    };
    const lat = extract('lat') ?? 31.0;
    const lon = extract('lon') ?? 121.5;
    const year = Math.round(extract('year')) || 2023;
    const tz = extract('tz_hours') ?? 8.0;

    const cacheDir = '/tmp/weather_cache';
    const cacheKey = `weather_${lat.toFixed(3)}_${lon.toFixed(3)}_${year}`;
    const cachePath = `${cacheDir}/${cacheKey}.csv`;

    // Check if already cached
    try { pyodide.FS.stat(cachePath); console.log('Weather cache hit:', cachePath); return; } catch (_) {}

    self.postMessage({ type: 'status', message: 'Fetching weather from Open-Meteo...' });

    const url = new URL('https://archive-api.open-meteo.com/v1/archive');
    url.searchParams.set('latitude', lat);
    url.searchParams.set('longitude', lon);
    url.searchParams.set('start_date', `${year}-01-01`);
    url.searchParams.set('end_date', `${year}-12-31`);
    url.searchParams.set('hourly', 'temperature_2m,relative_humidity_2m,wind_speed_10m,shortwave_radiation,direct_radiation,diffuse_radiation');
    url.searchParams.set('timezone', 'UTC');
    url.searchParams.set('wind_speed_unit', 'ms');

    const resp = await fetch(url.toString());
    if (!resp.ok) throw new Error(`Weather API returned ${resp.status}`);
    const data = await resp.json();
    const hourly = data.hourly;

    // Build CSV (UTC → local time)
    const lines = ['timestamp,temperature_2m,relative_humidity_2m,wind_speed_10m,shortwave_radiation,direct_radiation,diffuse_radiation'];
    for (let i = 0; i < hourly.time.length; i++) {
        const d = new Date(hourly.time[i] + 'Z');
        d.setUTCHours(d.getUTCHours() + Math.round(tz));
        const ts = d.toISOString().replace('T', ' ').replace('Z', '').slice(0, 19);
        lines.push([
            ts,
            hourly.temperature_2m[i],
            hourly.relative_humidity_2m[i],
            hourly.wind_speed_10m[i],
            hourly.shortwave_radiation?.[i] ?? 0,
            hourly.direct_radiation?.[i] ?? 0,
            hourly.diffuse_radiation?.[i] ?? 0,
        ].join(','));
    }

    try { pyodide.FS.mkdirTree(cacheDir); } catch (_) {}
    pyodide.FS.writeFile(cachePath, lines.join('\n'));
    console.log('Weather cached:', cachePath, `(${lines.length - 1} hours)`);
}

async function runSweep(projectYaml, ranges, objective) {
    await initPyodide();

    self.postMessage({ type: 'status', message: 'Writing project config...' });
    pyodide.FS.writeFile('/tmp/project.yaml', projectYaml);

    // Pre-fetch weather data via browser fetch (avoids 'requests' dependency in Pyodide)
    self.postMessage({ type: 'status', message: 'Preparing weather data...' });
    await fetchWeatherToCache(projectYaml);

    self.postMessage({ type: 'status', message: 'Running simulation...' });

    try {
        // Safety net: ensure micropip is loaded, then install yaml if needed
        try { await pyodide.loadPackage('micropip'); } catch (_) { /* built-in */ }
        await pyodide.runPythonAsync(`
try:
    import yaml
except ImportError:
    import micropip
    await micropip.install("pyyaml")
    import yaml
        `);

        pyodide.globals.set('ranges_json', JSON.stringify(ranges));
        pyodide.globals.set('objective', String(objective));

        const output = await pyodide.runPythonAsync(`
import sys, os
sys.path.insert(0, '/')
import json, yaml
from src.design.project import DesignProject
from src.design.sweep import sweep_design

with open('/tmp/project.yaml', 'r') as f:
    project = DesignProject.from_dict(yaml.safe_load(f))

project.space.parameter_ranges = json.loads(ranges_json)
project.space.objective = objective

result = sweep_design(project, cache_dir='/tmp/weather_cache')

records = None
if result['results'] is not None and not result['results'].empty:
    records = result['results'].to_dict(orient='records')

json.dumps({
    'results': records,
    'best': result['best'],
    'objective': result['objective']
})
        `);

        self.postMessage({ type: 'complete', ...JSON.parse(output) });
    } catch (e) {
        self.postMessage({ type: 'error', message: String(e) });
    }
}

async function listPresets() {
    await initPyodide();
    try {
        const output = pyodide.runPython(`
import json
try:
    from src.design.presets import PRESETS
    presets_list = [{'id': k, 'label': v.get('label', k)} for k, v in PRESETS.items()]
except (ImportError, AttributeError):
    presets_list = []
json.dumps(presets_list)
        `);
        self.postMessage({ type: 'presets', presets: JSON.parse(output) });
    } catch (e) {
        self.postMessage({ type: 'presets', presets: [] });
    }
}

async function runSinglePoint(projectYaml) {
    await initPyodide();

    self.postMessage({ type: 'status', message: 'Writing project config...' });
    pyodide.FS.writeFile('/tmp/project.yaml', projectYaml);

    self.postMessage({ type: 'status', message: 'Preparing weather data...' });
    await fetchWeatherToCache(projectYaml);

    self.postMessage({ type: 'status', message: 'Running simulation...' });

    try {
        await pyodide.runPythonAsync(`
try:
    import yaml
except ImportError:
    import micropip
    await micropip.install("pyyaml")
    import yaml
        `);

        const output = await pyodide.runPythonAsync(`
import sys, json
sys.path.insert(0, '/')
import yaml
from src.design.project import DesignProject
from src.design.engine import DesignEngine

with open('/tmp/project.yaml', 'r') as f:
    project = DesignProject.from_dict(yaml.safe_load(f))

engine = DesignEngine(cache_dir='/tmp/weather_cache')
result = engine.run(project)

# Return full SimulationResult JSON (v1.0 schema)
json.dumps(result.to_dict())
        `);

        const result = JSON.parse(output);
        self.postMessage({ type: 'simulate_complete', result });
    } catch (e) {
        self.postMessage({ type: 'simulate_error', message: String(e) });
    }
}

self.onmessage = async ({ data }) => {
    if (data.type === 'init') {
        await initPyodide();
    } else if (data.type === 'run') {
        await runSweep(data.projectYaml, data.ranges, data.objective);
    } else if (data.type === 'simulate') {
        await runSinglePoint(data.projectYaml);
    } else if (data.type === 'list_presets') {
        await listPresets();
    }
};

self.postMessage({ type: 'worker_loaded' });