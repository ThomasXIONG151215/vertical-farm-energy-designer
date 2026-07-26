const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  
  page.on('console', msg => {
    console.log(`[${msg.type()}] ${msg.text()}`);
  });
  page.on('pageerror', err => {
    console.log(`[PAGEERROR] ${err.message}`);
    console.log(err.stack);
  });
  page.on('worker', worker => {
    worker.on('console', msg => {
      console.log(`[WORKER ${msg.type()}] ${msg.text()}`);
    });
    worker.on('error', err => {
      console.log(`[WORKER ERROR] ${err.message}`);
    });
  });
  
  try {
    console.log('Navigating...');
    await page.goto('http://localhost:8080/', { waitUntil: 'domcontentloaded', timeout: 120000 });
    console.log('Page loaded');
    
    // Wait for worker to initialize - Pyodide + packages takes time
    console.log('Waiting for worker init...');
    await page.waitForTimeout(60000);
    console.log('Worker init wait done');
    
    // Try clicking Run Simulation
    await page.click('#run-btn');
    console.log('Clicked Run Simulation');
    
    // Wait for simulation to complete or error
    await page.waitForTimeout(120000);
    
  } catch (e) {
    console.error('Test error:', e.message);
  }
  
  await browser.close();
})();