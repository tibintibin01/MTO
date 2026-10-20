// Reviewed local security backport. No ignored advisory or renewed exception.
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const ROOT=path.resolve(__dirname,'..'),VENDOR=path.join(ROOT,'vendor/braces-guarded');
const braces=require('braces');
const direct=require(VENDOR);
const fixtures=require('./braces-compatibility.json');
let checks=0;
const check=(value,message)=>{assert.ok(value,message);checks++;};

async function main(){
 check(fs.realpathSync(require.resolve('braces'))===path.join(VENDOR,'index.js'),'Root glob consumers must resolve to the guarded source');
 check(braces===direct,'Do not test a different copy from the installed dependency');
 const lock=JSON.parse(fs.readFileSync(path.join(ROOT,'package-lock.json'),'utf8'));
 const copies=Object.entries(lock.packages).filter(([name])=>name.endsWith('node_modules/braces'));
 check(copies.length>0,'Missing brace-expansion dependency');
 for(const [name,entry] of copies){
  check(entry.link===true&&entry.resolved==='vendor/braces-guarded','Every braces copy must use the explicit local override: '+name);
 }
 check(lock.packages['vendor/braces-guarded']?.dev===true,'Backport must remain development-only');
 const manifest=require(path.join(VENDOR,'package.json'));
 check(manifest.name==='@mto/braces-guarded'&&manifest.private===true,'Never impersonate a patched upstream npm release');
 check(!manifest.scripts,'No vendor lifecycle hooks');
 const upstream=require(path.join(VENDOR,'UPSTREAM.json'));
 check(upstream.package==='braces'&&upstream.version==='3.0.3','Upstream version must be disclosed');
 for(const name of ['LICENSE','index.js','lib/constants.js','lib/utils.js']){
  const hash=crypto.createHash('sha256').update(fs.readFileSync(path.join(VENDOR,name),'utf8').replace(/\r\n/g,'\n')).digest('hex');
  check(hash===upstream.sha256[name],'Unchanged upstream source/license drift: '+name);
 }
 for(const fixture of fixtures.cases){
  assert.deepEqual(braces(fixture.input,fixture.options),fixture.expected);checks++;
 }
 const deep=['{'.repeat(4500)+'x'+'}'.repeat(4500),'('.repeat(4500)+'x'+')'.repeat(4500),'({'.repeat(2200)+'x'+'})'.repeat(2200),'{'.repeat(4500)+'x'];
 for(const method of ['parse','compile','expand','stringify','create'])for(const input of deep){
  assert.throws(()=>braces[method](input,{maxDepth:Infinity,maxLength:Infinity}),error=>error instanceof SyntaxError&&error.message.startsWith('MTO_BRACES_MAX_DEPTH'));checks++;
 }
 for(const method of ['compile','expand','stringify']){
  let tree={type:'text',value:'x'};
  for(let depth=0;depth<5000;depth++)tree={type:'root',nodes:[tree]};
  assert.throws(()=>braces[method](tree),error=>error instanceof SyntaxError&&error.message.startsWith('MTO_BRACES_MAX_DEPTH'));checks++;
  const cyclic={type:'root',nodes:[]};cyclic.nodes.push(cyclic);
  assert.throws(()=>braces[method](cyclic),error=>error instanceof SyntaxError&&error.message.startsWith('MTO_BRACES_CYCLIC_AST'));checks++;
  const wide={type:'root',nodes:Array.from({length:30001},()=>({type:'text',value:'x'}))};
  assert.throws(()=>braces[method](wide),error=>error instanceof SyntaxError&&error.message.startsWith('MTO_BRACES_MAX_NODES'));checks++;
 }
 const cyclicParent={type:'other',nodes:[{type:'other',nodes:[]}]};cyclicParent.parent=cyclicParent;
 assert.throws(()=>braces.expand(cyclicParent),error=>error instanceof SyntaxError&&error.message.startsWith('MTO_BRACES_MAX_DEPTH'));checks++;
 // Literal quoted/escaped/bracketed braces must not be counted as nesting.
 for(const input of ['"'+'{'.repeat(4000)+'"','['+'{'.repeat(4000)+']','\\{'.repeat(4000)]){
  assert.doesNotThrow(()=>braces.compile(input));checks++;
 }
 const postcss=require('postcss'),tailwind=require('tailwindcss');
 const css=fs.readFileSync(path.join(ROOT,'app/globals.css'),'utf8');
 const compiled=await postcss([tailwind(require(path.join(ROOT,'tailwind.config.js')))]).process(css,{from:path.join(ROOT,'app/globals.css')});
 // Git checks out CRLF on Windows and LF on Ubuntu. Normalize only those
 // line endings, preserving every other byte of the captured original output.
 check(fixtures.css_baseline.normalization==='crlf-to-lf','CSS baseline normalization must stay explicit');
 check(crypto.createHash('sha256').update(compiled.css.replace(/\r\n/g,'\n')).digest('hex')===fixtures.css_baseline.sha256,'Compiler output must match the approved pre-backport CSS except Git line endings');
 // Changing the compiler/site source requires deliberate re-review of this
 // baseline, not changing the security limits or deleting the comparison.
 console.log(JSON.stringify({status:'PASS',checks,scope:'Build-only guarded backport; 90 upstream compatibility cases, recursive input/AST/cycle guards and identical CSS'}));
}
main().catch(error=>{console.error(error);process.exitCode=1;});
