/**
 * VFED Web comprehensive tests (Playwright).
 *
 * Prereq: `npx serve . -p 8080` from vfed-web/ directory
 * Run  : `node test_comprehensive.js`
 *
 * T5: URL state encode → reload → decode → form restored
 * T6: COP mode select → field visibility toggles
 * T7: Single Point charts render after simulate_complete
 */

const { chromium } = require('playwright');
const BASE = 'http://localhost:8080/';

let passes = 0, fails = 0;
function ok(label) { console.log(`  ✅ ${label}`); passes++; }
function fail(label, detail) { console.log(`  ❌ ${label}: ${detail}`); fails++; }

async function test_t5_url_state() {
    console.log('── T5: URL State Encode/Decode ──');

    const browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    page.on('pageerror', err => console.error('[T5 PAGE]', err.message));

    await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(4000);  // JS init

    // 5a: Select 609 preset, modify lat
    await page.locator('#preset-select').selectOption('609');
    await page.waitForTimeout(1000);
    await page.locator('[data-key="site.lat"]').fill('35.0');
    await page.locator('[data-key="site.lat"]').dispatchEvent('change');
    await page.waitForTimeout(1000);

    const url1 = page.url();
    if (url1.includes('?state=')) ok('URL contains ?state= after form change');
    else fail('URL state missing', url1.slice(0,80));

    // 5b: Reload with state param
    await page.goto(url1, { waitUntil: 'domcontentloaded', timeout: 15000 });
    await page.waitForTimeout(3000);

    const latVal = await page.inputValue('[data-key="site.lat"]');
    if (latVal === '35') ok('site.lat restored to 35 after URL reload');
    else fail('site.lat not restored', `got: ${latVal}`);

    // 5c: Share button exists
    if (await page.locator('#share-btn').isVisible()) ok('Share button visible');
    else fail('Share button hidden', '');

    await browser.close();
    console.log('');
}

async function test_t6_t7_combined() {
    console.log('── T6+T7: Field Visibility + Chart Rendering ──');

    const browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();

    // Collect worker console for debugging
    let workerLogs = [];
    page.on('pageerror', err => console.error('[T6T7 PAGE]', err.message));
    page.on('worker', worker => {
        worker.on('error', err => console.error('[WORKER]', err.message));
        worker.on('console', msg => {
            const t = `[WORKER ${msg.type()}] ${msg.text()}`;
            workerLogs.push(t);
            if (msg.type() === 'error' || msg.text().includes('Error'))
                console.log(t);
        });
    });

    await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 30000 });
    console.log('    Waiting for Pyodide...');
    await page.waitForTimeout(90000);

    // Wait for worker `ready` signal via run button
    await page.waitForFunction(() => {
        const btn = document.getElementById('run-btn');
        return btn && !btn.disabled && btn.textContent.includes('Run');
    }, { timeout: 10000 }).then(() => {
        console.log('    Worker signaled ready');
    }).catch(() => {
        console.log('    ⚠ Worker ready timeout, continuing...');
    });

    // Select 609 preset
    await page.locator('#preset-select').selectOption('609');
    await page.waitForTimeout(1500);

    // ── T6: Field Visibility ──
    // Click HVAC gear button to open modal
    const hvacCard = page.locator('#sec-hvac .sec-gear');
    await hvacCard.click();
    await page.waitForTimeout(600);

    // Carnot → eta_II visible
    // Use modal select (inside #modal-body) to avoid sidebar duplicate
    await page.locator('#modal-body [data-key="hvac.cop_mode"]').selectOption('carnot');
    await page.waitForTimeout(1000);
    const eVis = await page.evaluate(() => {
        const el = document.querySelector('#modal-body [data-key="hvac.eta_II"]');
        return el && el.offsetParent !== null;
    });
    const cVis = await page.evaluate(() => {
        const el = document.querySelector('#modal-body [data-key="hvac.cop_value"]');
        return el && el.offsetParent !== null;
    });
    if (eVis && !cVis) ok('carnot: eta_II visible, cop_value hidden');
    else fail('carnot visibility', `eta=${eVis}, cop=${cVis}`);

    // Constant → opposite
    await page.locator('#modal-body [data-key="hvac.cop_mode"]').selectOption('constant');
    await page.waitForTimeout(1000);
    const eVis2 = await page.evaluate(() => {
        const el = document.querySelector('#modal-body [data-key="hvac.eta_II"]');
        return el && el.offsetParent !== null;
    });
    const cVis2 = await page.evaluate(() => {
        const el = document.querySelector('#modal-body [data-key="hvac.cop_value"]');
        return el && el.offsetParent !== null;
    });
    if (!eVis2 && cVis2) ok('constant: cop_value visible, eta_II hidden');
    else fail('constant visibility', `eta=${eVis2}, cop=${cVis2}`);

    // Close modal
    await page.locator('.modal-close').click();
    await page.waitForTimeout(400);

    // Mode tabs
    await page.locator('.mode-tab[data-mode="sweep"]').click();
    await page.waitForTimeout(400);
    if (await page.locator('#sweep-view').evaluate(el => el.classList.contains('active'))) ok('Sweep view shown');
    else fail('Sweep view not active', '');

    await page.locator('.mode-tab[data-mode="single"]').click();
    await page.waitForTimeout(400);
    if (await page.locator('#single-view').evaluate(el => el.classList.contains('active'))) ok('Single view restored');
    else fail('Single view not active', '');

    // ── T7: Chart Rendering ──
    // Re-open HVAC modal to set cop_mode back to carnot
    await page.locator('#sec-hvac .sec-gear').click();
    await page.waitForTimeout(400);
    await page.locator('#modal-body [data-key="hvac.cop_mode"]').selectOption('carnot');
    await page.locator('.modal-close').click();
    await page.waitForTimeout(600);

    // Trigger simulation and set up a direct response listener
    console.log('    Triggering simulation...');
    
    // Inject a flag that gets set when worker responds
    await page.evaluate(() => {
        window.__simDone = false;
        window.__simResult = null;
        window.__simError = null;
        
        // Intercept the worker onmessage to detect simulate_complete
        const origHandler = state.worker.onmessage;
        state.worker.addEventListener('message', (e) => {
            if (e.data && e.data.type === 'simulate_complete') {
                window.__simDone = true;
                window.__simResult = e.data.summary?.kwh_per_kg_fresh;
            }
            if (e.data && e.data.type === 'simulate_error') {
                window.__simDone = true;
                window.__simError = e.data.message;
            }
        });
        
        try {
            const yaml = generateYaml();
            state.worker.postMessage({ type: 'simulate', projectYaml: yaml });
        } catch(e) { window.__simError = e.message; window.__simDone = true; }
    });

    // Wait for result
    const gotResult = await page.waitForFunction(
        () => window.__simDone === true,
        { timeout: 300000 }
    ).then(() => true).catch(() => false);

    const res = await page.evaluate(() => ({
        kwhkg: window.__simResult,
        err: window.__simError
    }));
    
    if (gotResult && res.kwhkg !== null) {
        ok(`Simulate complete — kWh/kg = ${res.kwhkg}`);
    } else if (gotResult && res.err) {
        fail('Simulate error', res.err);
    } else {
        fail('Simulate timeout (5 min)', `kwhkg=${res.kwhkg}, err=${res.err}`);
    }

    const mwh = (await page.textContent('#s-mwh')) || '--';
    console.log(`    DOM s-mwh: ${mwh}`);

    // Chart canvases
    for (const id of ['chart-monthly', 'chart-donut', 'chart-seasonal', 'chart-climate']) {
        if (await page.locator(`#${id}`).count() > 0) ok(`Canvas #${id} exists`);
        else fail(`Canvas #${id} missing`, '');
    }

    await browser.close();
}

(async () => {
    await test_t5_url_state();
    await test_t6_t7_combined();

    console.log(`\n${'='.repeat(50)}`);
    console.log(`Passed: ${passes} | Failed: ${fails} | Total: ${passes + fails}`);
    console.log(`${'='.repeat(50)}`);
    process.exit(fails > 0 ? 1 : 0);
})();
