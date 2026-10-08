// Synthetic local production-server tests; never contact the municipal API.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),os=require('node:os'),path=require('node:path'),net=require('node:net');
const {spawn}=require('node:child_process'),{createHmac}=require('node:crypto');
const {chromium}=require('playwright');
const fsSync=require('node:fs');
const BROWSER=process.env.MTO_TEST_BROWSER_EXECUTABLE||(process.platform==='win32'&&fsSync.existsSync('C:/Program Files/Google/Chrome/Application/chrome.exe')?'C:/Program Files/Google/Chrome/Application/chrome.exe':undefined);
const ROOT=path.resolve(__dirname,'..');
const SECRET='synthetic-test-secret-not-production-0123456789';
const hash=(value,len=64)=>createHmac('sha256',SECRET).update(value.trim().toUpperCase()).digest('hex').slice(0,len);
let count=0;
function check(condition,message){assert.ok(condition,message);count++;}
function record(key,status,balance,paid){return {td_number:'06-0001-00001',td_lookup_hash:hash('06-0001-00001'),pin_lookup_hash:hash('PIN-'+key),pin_masked:'PIN-****',public_account_key:key.repeat(64),owner_name:key==='a'?'P***':'J***',barangay:'TEST BARANGAY',kind:'TEST PROPERTY',status,balance,total_credit:0,total_due:2000,total_paid:paid,assessed_value:100000,assessment_as_of_year:2026,billing_breakdown:[],last_payment:null,payment_history:[]};}
function snapshot(published=new Date().toISOString()){return {schema_version:2,owner_lookup_version:2,published_at:published,record_count:2,checksum:'c'.repeat(64),properties:[record('a','UPDATED',0,2000),record('b','DELINQUENT',1000,1000)],owner_lookup_index:{[hash('PEÑA',24)]:[0],[hash('PEÑ',24)]:[0]}};}
async function freePort(){const server=net.createServer();await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const port=server.address().port;await new Promise(resolve=>server.close(resolve));return port;}

(async()=>{
 const temp=await fs.mkdtemp(path.join(os.tmpdir(),'mto-portal-regression-'));
 const fixture=path.join(temp,'snapshot.json');await fs.writeFile(fixture,JSON.stringify(snapshot()));
 const output=path.join(ROOT,'..','portal-verification');await fs.mkdir(output,{recursive:true});
 const port=await freePort(),base='http://127.0.0.1:'+port;
 const child=spawn(process.execPath,[path.join(ROOT,'node_modules/next/dist/bin/next'),'start','--hostname','127.0.0.1','--port',String(port)],{cwd:ROOT,windowsHide:true,env:{...process.env,NODE_ENV:'production',MTO_PORTAL_LOOKUP_SECRET:SECRET,MTO_PORTAL_PUBLISH_TOKEN:SECRET,MTO_PORTAL_SNAPSHOT_PATH:fixture,MTO_PORTAL_MAX_SNAPSHOT_AGE_HOURS:'36'}});
 let serverLog='';child.stdout.on('data',d=>serverLog+=d);child.stderr.on('data',d=>serverLog+=d);
 let browser;
 try{
  for(let i=0;i<80;i++){try{const r=await fetch(base+'/');if(r.ok)break;}catch{}await new Promise(r=>setTimeout(r,200));if(i===79)throw new Error('Local server did not start: '+serverLog);}
  async function api(route){const r=await fetch(base+route);return {status:r.status,headers:r.headers,body:await r.json()};}
  let r=await api('/api/health');check(r.status===200&&r.body.ok,'Fresh snapshot must be ready');
  const iconManifestResponse=await fetch(base+'/manifest.json');
  const iconManifest=await iconManifestResponse.json();
  check(iconManifestResponse.ok&&iconManifest.icons.length===4,'Manifest serves four regular/maskable exports');
  for(const icon of iconManifest.icons){
   check(icon.src.startsWith('/icons/portal-20261008/'),'Installed-app icon URL is versioned');
   const response=await fetch(base+icon.src);
   check(response.ok&&response.headers.get('content-type').includes('image/png'),'Manifest icon is served as PNG');
   const hosted=Buffer.from(await response.arrayBuffer());
   check(hosted.equals(await fs.readFile(path.join(ROOT,'public',icon.src.slice(1)))),'Served icon matches checked asset bytes');
  }
  const faviconResponse=await fetch(base+'/favicon.ico');
  check(faviconResponse.ok&&Buffer.from(await faviconResponse.arrayBuffer()).equals(
   await fs.readFile(path.join(ROOT,'app/favicon.ico'))),'Next favicon endpoint serves approved ICO');
  check(r.body.publication_protocol.name==='private-direct-v1'&&r.body.publication_protocol.max_compressed_bytes===33554432,'Increased transport capacity advertised');
  check(/^[a-f0-9]{64}$/.test(r.body.expanded_payload_sha256),'Health exposes actual JSON-byte hash');
  for(const endpoint of ['prepare','commit']){
   const response=await fetch(base+'/api/portal-snapshot/'+endpoint,{method:'POST',headers:{'content-type':'application/json'},body:'{}'});
   check(response.status===401,'Unauthenticated '+endpoint+' cannot access storage');check(response.headers.get('cache-control')==='no-store','No cached publication controls');
  }
  let privateResponse=await fetch(base+'/api/portal-snapshot/commit',{method:'POST',headers:{'content-type':'application/json',authorization:'Bearer '+SECRET},body:'{"ticket":"bad"}'});
  check(privateResponse.status===400,'Invalid ticket rejected before storage access');
  for(const prefix of ['/api/public','/api/v1/public']){
   r=await api(prefix+'/property/06-0001-00001');check(r.status===409&&r.body.matches.length===2,'Duplicate accounts preserved');
   r=await api(prefix+'/property/06000100001');check(r.status===409&&r.body.matches.length===2,'Undashed TDN must preserve ambiguity');
   r=await api(prefix+'/property/06000100001?account='+'a'.repeat(64));check(r.status===200&&r.body.balance===0&&r.body.total_paid===2000,'Selected account isolation');
   check(r.body.published_at&&r.body.freshness.ok,'Actual publication metadata');
   r=await api(prefix+'/property/06000100001?account='+'b'.repeat(64));check(r.status===200&&r.body.balance===1000,'Second account not merged');
   r=await api(prefix+'/find?name='+encodeURIComponent('Peña'));check(r.status===200&&r.body.count===1,'Unicode owner name lookup');
   r=await api(prefix+'/find?name='+encodeURIComponent('Pen\u0303a'));check(r.status===200&&r.body.count===1,'Decomposed Unicode owner name lookup');
   r=await api(prefix+'/property/06%200001%2000001');check(r.status===409,'Spaced TDN alias retains account isolation');
   r=await api(prefix+'/property/%25BAD');check(r.status===400,'Malformed percent input must not produce a server error');
   r=await api(prefix+'/property/PIN-a/history?snapshot='+'d'.repeat(64));check(r.status===409&&r.body.code==='PORTAL_SNAPSHOT_CHANGED','History must match the property snapshot');
   r=await api(prefix+'/property/PIN-a/history?snapshot='+'c'.repeat(64));check(r.status===200&&Array.isArray(r.body),'Legacy history array contract');
  }
  let tick=0;
  async function replaceFixture(data){await fs.writeFile(fixture,JSON.stringify(data));const time=new Date(Date.now()+ ++tick*1000);await fs.utimes(fixture,time,time);}
  await replaceFixture(snapshot(new Date(Date.now()-40*3600000).toISOString()));
  r=await api('/api/health');check(r.status===503&&!r.body.ok,'Stale health must block');
  for(const route of ['/api/public/property/PIN-a','/api/public/property/PIN-a/history','/api/public/find?name=Pe%C3%B1a','/api/v1/public/property/PIN-a']){
   r=await api(route);check(r.status===503&&r.body.code==='PORTAL_SNAPSHOT_STALE','Stale lookup blocked: '+route);check(!('balance' in r.body),'Do not return stale financial figures');check(r.headers.get('cache-control')==='no-store','Financial API no-store');
  }
  let soa=await fetch(base+'/api/public/property/PIN-a/soa');check(soa.status===503&&!((await soa.text()).includes('PHP 2,000')),'Stale statement withheld');
  await replaceFixture(snapshot(new Date(Date.now()+3600000).toISOString()));r=await api('/api/health');check(r.status===503&&r.body.status==='invalid_timestamp','Future timestamp must not make records ready');
  await replaceFixture(snapshot('2026-10-06T03:00:00'));r=await api('/api/health');check(r.status===503&&r.body.status==='invalid_timestamp','Timezone-less publication timestamp blocked');
  const legacy=snapshot();delete legacy.owner_lookup_version;await replaceFixture(legacy);r=await api('/api/public/find?name=Pe%C3%B1a');check(r.status===503,'Legacy Unicode index must request an update, not return a false empty result');
  await replaceFixture(snapshot());
  browser=await chromium.launch({headless:true,...(BROWSER?{executablePath:BROWSER}:{}),chromiumSandbox:true});
  const measurements=[];
  for(const width of [320,390,1440]){
   const c=await browser.newContext({viewport:{width,height:width===320?700:844},serviceWorkers:'block'}),p=await c.newPage();
   await p.goto(base,{waitUntil:'networkidle'});await p.waitForTimeout(400);
   if(width===390){
    const iconLinks=await p.locator('link[rel="icon"]').evaluateAll(items=>items.map(item=>item.getAttribute('href')));
    const appleLinks=await p.locator('link[rel="apple-touch-icon"]').evaluateAll(items=>items.map(item=>({href:item.getAttribute('href'),sizes:item.getAttribute('sizes')})));
    check(iconLinks.length>0&&iconLinks.every(href=>href.startsWith('/icons/portal-20261008/')||href.startsWith('/icon.png')||href.startsWith('/favicon.ico')),'Rendered browser metadata has no old seal icon link');
    check(appleLinks.length>0&&appleLinks.every(item=>item.sizes==='180x180'),'Rendered Apple touch icons declare actual 180px exports');
    for(const item of appleLinks){
     const response=await fetch(base+item.href);
     check(response.ok&&Buffer.from(await response.arrayBuffer()).equals(await fs.readFile(path.join(ROOT,'app/apple-icon.png'))),'Rendered Apple touch URL serves the approved mark');
    }
   }
   const input=p.getByRole('textbox',{name:'Tax Declaration Number or PIN'}),button=p.getByRole('button',{name:'Search property',exact:true});
   const box=await button.boundingBox();
   await p.screenshot({path:path.join(output,'initial-'+width+'.png')});
   console.log(JSON.stringify({width,searchButton:box}));
   check(box.y+box.height<=(width===320?700:844),'Search action within initial viewport at '+width);
   check(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'No horizontal overflow at '+width);
   check(await p.getByRole('navigation',{name:'Main navigation'}).getByRole('link',{name:'Help',exact:true}).isVisible(),'Mobile Help available');
   await input.focus();const focus=await input.evaluate(el=>({width:parseFloat(getComputedStyle(el).outlineWidth),color:getComputedStyle(el).outlineColor}));check(focus.width>=2,'Visible keyboard focus');
   await button.click();check(await input.getAttribute('aria-invalid')==='true','Invalid search field marked');check(await p.getByRole('alert').filter({hasText:'Enter a Tax Declaration'}).isVisible(),'Search error announced');
   const toggle=p.locator('button[aria-controls="owner-finder"]');await toggle.click();check(await toggle.getAttribute('aria-expanded')==='true','Owner toggle expanded');await toggle.click();
   await input.fill('06000100001');await button.click();await p.getByRole('heading',{name:'2 separate accounts use this identifier'}).waitFor();check(await p.getByRole('region',{name:'Matching property accounts'}).getByRole('button').count()===2,'Duplicate chooser retains separate accounts');
   await p.screenshot({path:path.join(output,'home-'+width+'.png'),fullPage:true});measurements.push({width,searchButton:box});
   await c.close();
  }
  const c=await browser.newContext({viewport:{width:390,height:844},serviceWorkers:'block'}),p=await c.newPage();
  await p.route('**/api/public/property/PIN-a/history?*',route=>route.fulfill({status:503,contentType:'application/json',body:'{"detail":"Synthetic history outage"}'}));
  await p.goto(base+'/property/PIN-a',{waitUntil:'networkidle'});
  await p.getByRole('button',{name:'Retry payment history'}).waitFor();
  check(await p.getByText('No payment records found',{exact:true}).count()===0,'History error is never presented as empty');
  check(!((await p.locator('main').innerText()).includes('0 payment(s) on record')),'Unknown payment count is not zero');
  check((await p.locator('main').innerText()).includes('Records published:'),'Actual publication date in property header');
  check(!((await p.locator('main').innerText()).includes('AS OF ')),'No fabricated current-date header');
  await p.screenshot({path:path.join(output,'history-error.png'),fullPage:true});
  await p.unroute('**/api/public/property/PIN-a/history?*');await p.getByRole('button',{name:'Retry payment history'}).click();await p.getByText('No payment records found',{exact:true}).waitFor();check(true,'Genuine loaded-empty history remains available');
  await c.close();
  const nojs=await browser.newContext({viewport:{width:390,height:844},javaScriptEnabled:false});const np=await nojs.newPage();await np.goto(base,{waitUntil:'networkidle'});const fallback=np.locator('main noscript p');check(await fallback.isVisible()&&(await fallback.innerText()).includes('JavaScript is required for property lookup.'),'No-JS assistance stays visible');check(await np.locator('main noscript a[href="/help"]').isVisible(),'No-JS assistance link stays usable');await nojs.close();
  const robots=await (await fetch(base+'/robots.txt')).text(),sitemap=await (await fetch(base+'/sitemap.xml')).text();check(robots.includes('Disallow: /property/'),'Robots do not index property records');check(!sitemap.includes('/property/'),'Sitemap does not disclose property account URLs');
  check((await fetch(base+'/admin/login')).url===base+'/','Public admin route remains blocked');
  await fs.writeFile(path.join(output,'portal-regression.json'),JSON.stringify({passed:count,scope:'Synthetic local production build only; no live mutations or real taxpayer records',measurements},null,2));
  console.log(JSON.stringify({passed:count,measurements,artifacts:output},null,2));
 }finally{if(browser)await browser.close();child.kill();await fs.writeFile(path.join(output,'local-server.log'),serverLog);}
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
