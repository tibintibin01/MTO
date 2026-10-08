// Local visual/data-contract checks. No real records, live searches or publication.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),net=require('node:net'),os=require('node:os');
const {spawn}=require('node:child_process'),{chromium}=require('playwright');
const {SECRET,snapshot}=require('./property-preview-fixture.cjs');
const ROOT=path.resolve(__dirname,'..'),OUTPUT=path.resolve(ROOT,'..','..','design-preview','property-workspace-20261008');
const LABEL=process.argv.includes('--baseline')?'baseline':'coastal';
const fsSync=require('node:fs');
const BROWSER=process.env.MTO_TEST_BROWSER_EXECUTABLE||(process.platform==='win32'&&fsSync.existsSync('C:/Program Files/Google/Chrome/Application/chrome.exe')?'C:/Program Files/Google/Chrome/Application/chrome.exe':undefined);
const HISTORY_ROUTE=/\/api\/public\/property\/DEMO-A\/history(?:\?|$)/;
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const median=values=>values.slice().sort((a,b)=>a-b)[Math.floor(values.length/2)];
async function port(){const server=net.createServer();await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const number=server.address().port;await new Promise(resolve=>server.close(resolve));return number;}
(async()=>{
  await fs.mkdir(OUTPUT,{recursive:true});const temp=await fs.mkdtemp(path.join(os.tmpdir(),'mto-property-design-'));
  const fixture=path.join(temp,'snapshot.json');await fs.writeFile(fixture,JSON.stringify(snapshot()));
  const base='http://127.0.0.1:'+await port();
  const server=spawn(process.execPath,[path.join(ROOT,'node_modules/next/dist/bin/next'),'start','--hostname','127.0.0.1','--port',base.split(':').pop()],
    {cwd:ROOT,windowsHide:true,env:{...process.env,NODE_ENV:'production',MTO_PORTAL_LOOKUP_SECRET:SECRET,MTO_PORTAL_PUBLISH_TOKEN:SECRET,BLOB_READ_WRITE_TOKEN:'',MTO_PORTAL_SNAPSHOT_PATH:fixture}});
  let log='',browser,checks=0;server.stdout.on('data',data=>log+=data);server.stderr.on('data',data=>log+=data);
  const check=(condition,message)=>{assert.ok(condition,message);checks++;};
  try{
    for(let i=0;i<100;i++){try{if((await fetch(base)).ok)break;}catch{}if(i===99)throw Error('Local server unavailable');await sleep(200);}
    browser=await chromium.launch({headless:true,...(BROWSER?{executablePath:BROWSER}:{}),chromiumSandbox:true});
    async function context(options){const ctx=await browser.newContext({serviceWorkers:'allow',...options});await ctx.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());return ctx;}
    async function ready(page,query='DEMO-A'){
      await page.goto(base+'/property/'+query,{waitUntil:'networkidle'});
      await page.getByText('1 payment(s) on record',{exact:true}).waitFor();
    }
    for(const width of [320,390,768,1440]){
      const ctx=await context({viewport:{width,height:900}}),page=await ctx.newPage();const errors=[];
      page.on('pageerror',error=>errors.push(error.message));const control=await ctx.newCDPSession(page);await control.send('Network.setBypassServiceWorker',{bypass:true});await ready(page);
      check(errors.length===0,'No property runtime errors at '+width+': '+JSON.stringify(errors));
      check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'No property-page horizontal overflow at '+width);
      const main=page.locator('main');const text=await main.innerText();
      for(const value of ['DEMO OWNER A','₱2,530.65','₱1,107.58','₱3,538.23','₱100.00','2027'])check(text.includes(value),'Published field preserved: '+value+' at '+width);
      check(text.includes('Records published:'),'Actual publication timestamp retained');
      if(LABEL!=='baseline')check(await main.locator('.property-stat').filter({hasText:'Last Payment'}).locator('.property-stat-value').innerText()==='2026-10-01','Payment date is distinct from covered tax year');
      const soa=page.getByRole('link',{name:'Download SOA',exact:true});check((await soa.getAttribute('href'))==='/api/public/property/DEMO-A/soa','SOA source identifier retained');
      const billing=page.getByRole('button').filter({hasText:'Billing Breakdown'});await billing.click();check(await billing.getAttribute('aria-expanded')==='true','Billing toggle state');
      check((await main.innerText()).includes('₱421.78'),'Stored penalty visible unchanged');
      check((await main.innerText()).includes('DEMO-001'),'Official receipt number visible unchanged');
      if(LABEL!=='baseline'){
        check(await main.locator('img').count()===0,'Decorative property photos removed');
        check((await main.innerText()).includes('Discount applied'),'Applied-discount meaning explicit');
        check((await main.innerText()).includes('It has not been transferred'),'Unapplied credit not netted across years');
      }
      await page.locator('footer').scrollIntoViewIfNeeded();await page.waitForFunction(()=>{const image=document.querySelector('footer img');return image?.complete&&image.naturalWidth>0;});
      await page.locator('header').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(OUTPUT,LABEL+'-'+width+'.png'),fullPage:true,animations:'disabled'});
      await ctx.close();
    }
    if(LABEL!=='baseline'){
      const ctx=await context({viewport:{width:390,height:900},reducedMotion:'reduce'}),page=await ctx.newPage();
      const control=await ctx.newCDPSession(page);await control.send('Network.setBypassServiceWorker',{bypass:true});
      await page.goto(base+'/property/DEMO-B',{waitUntil:'networkidle'});await page.getByText('2 payment(s) on record',{exact:true}).waitFor();
      check((await page.locator('main').innerText()).includes('DEMO OWNER B'),'Second duplicate account owner isolated');
      check(!((await page.locator('main').innerText()).includes('₱2,530.65')),'No first-account balance leak');
      check(await page.getByText('Fully Paid',{exact:true}).isVisible(),'Settled account state');
      await page.goto(base+'/property/DEMO-PENDING',{waitUntil:'networkidle'});await page.getByText('No payment records found',{exact:true}).waitFor();
      check((await page.locator('main').innerText()).includes('Not Yet Billed'),'Pending account not shown as settled');
      await page.screenshot({path:path.join(OUTPUT,'pending-mobile.png'),fullPage:true,animations:'disabled'});
      await ctx.close();
      // A fresh context keeps outage interception independent of prior pages.
      const errorContext=await context({viewport:{width:390,height:900},reducedMotion:'reduce'}),errorPage=await errorContext.newPage();
      const errorControl=await errorContext.newCDPSession(errorPage);await errorControl.send('Network.setBypassServiceWorker',{bypass:true});
      let historyIntercepts=0;const requestURLs=[];errorPage.on('request',request=>{if(request.url().includes('/api/'))requestURLs.push(request.url());});
      await errorPage.route(HISTORY_ROUTE,route=>{historyIntercepts++;return route.fulfill({status:503,contentType:'application/json',body:'{"detail":"Synthetic unavailable history"}'});});
      await errorPage.goto(base+'/property/DEMO-A',{waitUntil:'networkidle'});
      try{await errorPage.getByRole('button',{name:'Retry payment history',exact:true}).waitFor({timeout:10000});}catch(error){console.log(JSON.stringify({historyIntercepts,requestURLs,visibleText:(await errorPage.locator('main').innerText()).slice(0,2600)}));await errorPage.screenshot({path:path.join(OUTPUT,'diagnostic-history-state.png'),fullPage:true});throw error;}
      check(historyIntercepts>0,'Synthetic outage was actually injected');
      const failed=await errorPage.locator('main').innerText();check(!failed.includes('0 payment(s) on record'),'Unavailable count is not zero');
      check(!failed.includes('No payment records found'),'History failure is not an empty-history assertion');
      await errorPage.screenshot({path:path.join(OUTPUT,'history-error-mobile.png'),fullPage:true,animations:'disabled'});
      await errorPage.unroute(HISTORY_ROUTE);await errorPage.getByRole('button',{name:'Retry payment history',exact:true}).click();await errorPage.getByText('1 payment(s) on record',{exact:true}).waitFor();check(true,'History retry recovers');
      await errorContext.close();
      // Worker-owned fetches are not page-route requests after clientsClaim.
      // Each injected initial failure gets a fresh context; production worker
      // rules remain unchanged and the retry is tested against the real fixture.
      const mismatchContext=await context({viewport:{width:390,height:900}}),mismatchPage=await mismatchContext.newPage();
      let mismatchIntercepts=0;await mismatchPage.route(HISTORY_ROUTE,route=>{mismatchIntercepts++;return route.fulfill({status:409,contentType:'application/json',body:'{"code":"PORTAL_SNAPSHOT_CHANGED","detail":"Refresh to use the same published record."}'});});
      await mismatchPage.goto(base+'/property/DEMO-A',{waitUntil:'networkidle'});await mismatchPage.getByRole('button',{name:'Retry payment history',exact:true}).waitFor();
      check(mismatchIntercepts>0,'Synthetic snapshot mismatch was actually injected');check(!((await mismatchPage.locator('main').innerText()).includes('DEMO-001')),'Mismatched-snapshot history withheld');await mismatchContext.close();
      const selectedContext=await context({viewport:{width:390,height:900}}),selectedPage=await selectedContext.newPage();
      await selectedPage.goto(base+'/property/06-0001-00001?account='+'a'.repeat(64),{waitUntil:'networkidle'});await selectedPage.getByText('1 payment(s) on record',{exact:true}).waitFor();
      check((await selectedPage.getByRole('link',{name:'Download SOA',exact:true}).getAttribute('href')).endsWith('?account='+'a'.repeat(64)),'SOA retains opaque selected account');
      await selectedPage.goto(base+'/property/DEMO-MISSING',{waitUntil:'networkidle'});await selectedPage.getByRole('heading',{name:'Could not load property'}).waitFor();
      check(await selectedPage.getByRole('link',{name:'New search'}).isVisible(),'Missing property offers safe recovery');await selectedContext.close();
    }
    if(process.argv.includes('--contracts-only')){
      const result={status:'PASS',checks,scope:'Synthetic localhost contracts only; no baseline performance claim'};
      await fs.writeFile(path.join(OUTPUT,'contracts.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));return;
    }
    const runs=[];
    for(let i=0;i<3;i++){
      const ctx=await context({viewport:{width:390,height:844}}),page=await ctx.newPage(),cdp=await ctx.newCDPSession(page);
      await cdp.send('Network.enable');await cdp.send('Network.setCacheDisabled',{cacheDisabled:true});await cdp.send('Network.setBypassServiceWorker',{bypass:true});
      await cdp.send('Emulation.setCPUThrottlingRate',{rate:4});await cdp.send('Network.emulateNetworkConditions',{offline:false,latency:100,downloadThroughput:1.6*1024*1024/8,uploadThroughput:750*1024/8});
      await page.addInitScript(()=>{window.__propertyMetrics={lcp:0,cls:0};new PerformanceObserver(list=>{for(const entry of list.getEntries())window.__propertyMetrics.lcp=entry.startTime;}).observe({type:'largest-contentful-paint',buffered:true});new PerformanceObserver(list=>{for(const entry of list.getEntries())if(!entry.hadRecentInput)window.__propertyMetrics.cls+=entry.value;}).observe({type:'layout-shift',buffered:true});});
      await ready(page);await sleep(750);runs.push(await page.evaluate(()=>({...window.__propertyMetrics,resources:performance.getEntriesByType('resource').map(entry=>({name:new URL(entry.name).pathname,encoded:entry.encodedBodySize}))})));await ctx.close();
    }
    const report={label:LABEL,scope:'Synthetic localhost only',checks,runs,medians:{lcpMs:median(runs.map(run=>run.lcp)),cls:median(runs.map(run=>run.cls)),
      encodedResourceBytes:median(runs.map(run=>run.resources.reduce((sum,entry)=>sum+entry.encoded,0))),encodedJSBytes:median(runs.map(run=>run.resources.filter(entry=>entry.name.endsWith('.js')).reduce((sum,entry)=>sum+entry.encoded,0)))}};
    await fs.writeFile(path.join(OUTPUT,LABEL+'-measurement-'+Date.now()+'.json'),JSON.stringify(report,null,2));
    if(LABEL!=='baseline'){
      const before=JSON.parse(await fs.readFile(path.join(OUTPUT,'baseline.json'),'utf8'));
      check(report.medians.encodedResourceBytes<=before.medians.encodedResourceBytes,'Property resource budget');
      check(report.medians.encodedJSBytes<=before.medians.encodedJSBytes,'No extra property JavaScript');
      check(report.medians.lcpMs<=before.medians.lcpMs*1.15+100,'Property lab loading budget');
      report.comparison={before:before.medians,resourceDelta:report.medians.encodedResourceBytes-before.medians.encodedResourceBytes,jsDelta:report.medians.encodedJSBytes-before.medians.encodedJSBytes};
    }
    report.checks=checks;report.status='PASS';await fs.writeFile(path.join(OUTPUT,LABEL+'.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({label:LABEL,checks,medians:report.medians,comparison:report.comparison,output:OUTPUT},null,2));
  }finally{if(browser)await browser.close();server.kill();await fs.writeFile(path.join(OUTPUT,LABEL+'-server.log'),log);}
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
