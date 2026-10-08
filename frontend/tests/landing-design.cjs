// Reproducible, local-only landing-page visual/performance checks.
// No municipal records, credentials, uploads, or external browser requests.
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const net = require('node:net');
const {spawn} = require('node:child_process');
const {chromium} = require('playwright');
const {gzipSync} = require('node:zlib');
const ROOT = path.resolve(__dirname, '..');
const OUTPUT = path.resolve(ROOT, '..', '..', 'design-preview', 'portal-landing-20261008');
const LABEL = process.argv.includes('--baseline') ? 'baseline' : 'coastal';
const BROWSER = process.env.MTO_TEST_BROWSER_EXECUTABLE || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const SECRET = 'local-synthetic-landing-test-not-production';
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

async function freePort() {
  const server = net.createServer();
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  await new Promise(resolve => server.close(resolve));
  return port;
}
function median(values) { return values.slice().sort((a,b) => a-b)[Math.floor(values.length / 2)]; }
function contrast(foreground,background){
  const luminance=hex=>{
    const rgb=hex.match(/[a-f\d]{2}/gi).map(value=>parseInt(value,16)/255)
      .map(value=>value<=0.04045?value/12.92:((value+0.055)/1.055)**2.4);
    return rgb[0]*0.2126+rgb[1]*0.7152+rgb[2]*0.0722;
  };
  const a=luminance(foreground),b=luminance(background);return(Math.max(a,b)+0.05)/(Math.min(a,b)+0.05);
}

(async () => {
  await fs.mkdir(OUTPUT, {recursive:true});
  const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'mto-landing-design-'));
  const fixture = path.join(temp, 'snapshot.json');
  await fs.writeFile(fixture, JSON.stringify({schema_version:2, owner_lookup_version:2,
    published_at:new Date().toISOString(), record_count:0, checksum:'c'.repeat(64),
    properties:[], owner_lookup_index:{}}));
  const port = await freePort(), base = 'http://127.0.0.1:' + port;
  const server = spawn(process.execPath, [path.join(ROOT, 'node_modules/next/dist/bin/next'),
    'start', '--hostname', '127.0.0.1', '--port', String(port)], {cwd:ROOT, windowsHide:true,
    env:{...process.env, NODE_ENV:'production', MTO_PORTAL_LOOKUP_SECRET:SECRET,
      MTO_PORTAL_PUBLISH_TOKEN:SECRET, BLOB_READ_WRITE_TOKEN:'', MTO_PORTAL_SNAPSHOT_PATH:fixture}});
  let log = '', browser, checks = 0;
  server.stdout.on('data', data => { log += data; });
  server.stderr.on('data', data => { log += data; });
  const check = (condition, message) => { assert.ok(condition, message); checks++; };
  try {
    for (let attempt=0; attempt<100; attempt++) {
      try { if ((await fetch(base)).ok) break; } catch {}
      if (attempt===99) throw new Error('Local server did not become ready');
      await delay(200);
    }
    browser = await chromium.launch({headless:true, executablePath:BROWSER, chromiumSandbox:true});
    async function context(options) {
      const ctx = await browser.newContext({serviceWorkers:'allow', ...options});
      await ctx.route('**/*', route => new URL(route.request().url()).origin === base
        ? route.continue() : route.abort());
      return ctx;
    }
    const layouts = [];
    for (const width of [320,390,768,1440]) {
      const height = width===320 ? 700 : 900;
      const ctx = await context({viewport:{width,height}}), page = await ctx.newPage();
      const errors=[]; page.on('pageerror', error => errors.push(error.message));
      await page.goto(base, {waitUntil:'networkidle'});
      const input = page.getByRole('textbox', {name:'Tax Declaration Number or PIN',exact:true});
      const search = page.getByRole('button', {name:'Search property',exact:true});
      await search.waitFor({state:'visible'});
      const box = await search.boundingBox();
      check(box.y+box.height <= height, 'Search within initial viewport: '+width);
      check(await page.evaluate(() => document.documentElement.scrollWidth<=innerWidth), 'No overflow: '+width);
      check(errors.length===0, 'No browser runtime errors: '+width+' '+JSON.stringify(errors));
      // Load the footer's lazy seal before a full-page capture; viewport-only
      // performance runs below intentionally retain normal lazy loading.
      await page.locator('footer').scrollIntoViewIfNeeded();
      await page.waitForFunction(()=>{
        const image=document.querySelector('footer img');return image?.complete&&image.naturalWidth>0;
      },null,{timeout:10000});
      await page.locator('header').scrollIntoViewIfNeeded();
      await page.screenshot({path:path.join(OUTPUT,LABEL+'-'+width+'.png'), fullPage:true, animations:'disabled'});
      await input.focus();
      check(await input.evaluate(el => parseFloat(getComputedStyle(el).outlineWidth)>=2), 'Visible input focus: '+width);
      await search.click();
      check(await input.getAttribute('aria-invalid')==='true', 'Invalid field marked: '+width);
      check(await page.getByRole('alert').filter({hasText:'Enter a Tax Declaration'}).isVisible(), 'Error announced: '+width);
      const toggle=page.locator('button[aria-controls="owner-finder"]');
      await toggle.click();
      check(await page.getByRole('textbox',{name:'Owner name',exact:true}).isVisible(), 'Owner search available: '+width);
      await toggle.click();
      layouts.push({width,height,searchButton:box});
      await ctx.close();
    }
    const reduced=await context({viewport:{width:1440,height:900},reducedMotion:'reduce'});
    const rp=await reduced.newPage();await rp.goto(base,{waitUntil:'networkidle'});
    if(LABEL!=='baseline') {
      check(await rp.locator('.landing-art').isVisible(), 'Dimensional artwork visible on desktop');
      check(await rp.evaluate(() => document.getAnimations().every(animation =>
        animation.playState !== 'running' || Number(animation.effect.getComputedTiming().duration)<1)), 'Reduced motion honored');
    }
    await reduced.close();
    if(LABEL!=='baseline') {
      const zoom=await context({viewport:{width:640,height:450}}),zp=await zoom.newPage();
      await zp.goto(base,{waitUntil:'networkidle'});
      check(await zp.evaluate(()=>document.documentElement.scrollWidth<=innerWidth), '200%-equivalent narrow viewport reflow');
      check(await zp.getByRole('button',{name:'Search property',exact:true}).isVisible(), 'Search remains available at zoom-equivalent width');
      await zoom.close();
      for(const [name,fg,bg] of [['Search button','#ffffff','#155d53'],['Hero description','#cfdddf','#204b54'],
        ['Owner lookup','#ecd29f','#204b54'],['Card description','#52645e','#ffffff'],
        ['Card number','#617268','#ffffff'],['Card action','#185d51','#ffffff']]) {
        check(contrast(fg,bg)>=4.5, 'Text contrast: '+name);
      }
    }
    const nojs=await context({viewport:{width:390,height:900},javaScriptEnabled:false});
    const np=await nojs.newPage();await np.goto(base,{waitUntil:'networkidle'});
    // Playwright's text engine excludes noscript subtrees even when JS is off;
    // check the rendered paragraph and its assistance link directly instead.
    const fallback=LABEL==='baseline'
      ? np.getByText('JavaScript is required for property lookup.',{exact:false})
      : np.locator('main noscript p');
    check(await fallback.isVisible()&&(await fallback.innerText()).includes('JavaScript is required for property lookup.'), 'No-JS assistance retained');
    if(LABEL!=='baseline')check(await np.locator('main noscript a[href="/help"]').isVisible(), 'No-JS assistance link retained');
    await nojs.close();
    if(process.argv.includes('--screenshots-only')){
      console.log(JSON.stringify({label:LABEL,checks,scope:'Visual recapture only; stored performance measurements unchanged',output:OUTPUT},null,2));return;
    }
    // Real production bundle in an isolated Chrome process: same CPU/network
    // profile for both designs. These lab timings are not field Core Web Vitals.
    const runs=[];
    for(let index=0;index<3;index++) {
      const ctx=await context({viewport:{width:390,height:844}}), page=await ctx.newPage();
      const cdp=await ctx.newCDPSession(page);
      await cdp.send('Network.enable');await cdp.send('Network.setCacheDisabled',{cacheDisabled:true});
      await cdp.send('Network.setBypassServiceWorker',{bypass:true});
      await cdp.send('Emulation.setCPUThrottlingRate',{rate:4});
      await cdp.send('Network.emulateNetworkConditions',{offline:false,latency:100,
        downloadThroughput:1.6*1024*1024/8,uploadThroughput:750*1024/8});
      await page.addInitScript(() => {
        window.__landingMetrics={lcp:0,cls:0,longTaskMs:0,eventDurations:[]};
        new PerformanceObserver(list => { for(const entry of list.getEntries()) window.__landingMetrics.lcp=entry.startTime; })
          .observe({type:'largest-contentful-paint',buffered:true});
        new PerformanceObserver(list => { for(const entry of list.getEntries()) if(!entry.hadRecentInput) window.__landingMetrics.cls+=entry.value; })
          .observe({type:'layout-shift',buffered:true});
        new PerformanceObserver(list => { for(const entry of list.getEntries()) window.__landingMetrics.longTaskMs+=entry.duration; })
          .observe({type:'longtask',buffered:true});
        new PerformanceObserver(list=>{for(const entry of list.getEntries()) if(entry.interactionId>0) window.__landingMetrics.eventDurations.push(entry.duration);})
          .observe({type:'event',buffered:true,durationThreshold:16});
      });
      await page.goto(base,{waitUntil:'networkidle'});await delay(750);
      const metrics=await page.evaluate(() => ({...window.__landingMetrics,
        resources:performance.getEntriesByType('resource').map(entry => ({name:new URL(entry.name).pathname,
          encoded:entry.encodedBodySize,decoded:entry.decodedBodySize}))}));
      const scripts=metrics.resources.filter(resource => resource.name.endsWith('.js'));
      runs.push({...metrics,jsEncodedBytes:scripts.reduce((sum,resource)=>sum+resource.encoded,0),
        totalEncodedBytes:metrics.resources.reduce((sum,resource)=>sum+resource.encoded,0)});
      await page.getByRole('button',{name:'Search property',exact:true}).click();
      await page.getByRole('alert').filter({hasText:'Enter a Tax Declaration'}).waitFor();await delay(100);
      const durations=await page.evaluate(()=>window.__landingMetrics.eventDurations);
      // An absent event entry means it was below the observer's 16ms threshold.
      runs[runs.length-1].syntheticInteractionMs=Math.max(0,...durations);
      if(LABEL!=='baseline')check(runs[runs.length-1].syntheticInteractionMs<=200,'Synthetic search interaction budget');
      await ctx.close();
    }
    const html=await (await fetch(base)).text();
    const report={label:LABEL,status:'MEASURED',scope:'Local synthetic production build; no real records or external browser requests',
      checks,layouts,runs,medians:{lcpMs:median(runs.map(run=>run.lcp)),cls:median(runs.map(run=>run.cls)),
        longTaskMs:median(runs.map(run=>run.longTaskMs)),jsEncodedBytes:median(runs.map(run=>run.jsEncodedBytes)),
        totalEncodedBytes:median(runs.map(run=>run.totalEncodedBytes))},htmlGzipBytes:gzipSync(html).length};
    // Retain each measurement before enforcing budgets, including failures.
    await fs.writeFile(path.join(OUTPUT,LABEL+'-measurement-'+Date.now()+'.json'),JSON.stringify(report,null,2));
    check(report.medians.lcpMs>0, 'LCP measurement captured');
    if(LABEL!=='baseline') {
      check(report.medians.cls<=0.05, 'Layout stability budget: '+report.medians.cls);
      const baseline=JSON.parse(await fs.readFile(path.join(OUTPUT,'baseline.json'),'utf8'));
      // A modest lab variance allowance; payload comparison is deterministic.
      check(report.medians.lcpMs<=baseline.medians.lcpMs*1.15+100, 'No material lab LCP regression');
      check(report.medians.totalEncodedBytes<=baseline.medians.totalEncodedBytes, 'No increase in total transferred resources');
      check(report.medians.jsEncodedBytes<=baseline.medians.jsEncodedBytes+2500, 'Maximum 2.5KB extra compressed route JS: '+(report.medians.jsEncodedBytes-baseline.medians.jsEncodedBytes));
      report.comparison={baseline:baseline.medians,
        lcpDeltaMs:report.medians.lcpMs-baseline.medians.lcpMs,
        jsDeltaBytes:report.medians.jsEncodedBytes-baseline.medians.jsEncodedBytes,
        totalDeltaBytes:report.medians.totalEncodedBytes-baseline.medians.totalEncodedBytes};
    }
    report.checks=checks;report.status='PASS';
    await fs.writeFile(path.join(OUTPUT,LABEL+'.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify({label:LABEL,checks,medians:report.medians,comparison:report.comparison,output:OUTPUT},null,2));
  } finally {
    if(browser)await browser.close();server.kill();
    await fs.writeFile(path.join(OUTPUT,LABEL+'-server.log'),log);
  }
})().catch(error => { console.error(error.stack);process.exitCode=1; });
