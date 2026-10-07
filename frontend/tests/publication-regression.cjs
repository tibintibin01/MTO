// Synthetic-only protocol tests. Blob IO is replaced; no hosted data or tokens.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {createHash,randomBytes}=require('node:crypto'),{gzipSync}=require('node:zlib'),Module=require('node:module'),ts=require('typescript');
const originalLoad=Module._load;
Module._load=function(name,parent,isMain){if(name==='server-only')return {};return originalLoad.call(this,name,parent,isMain);};
require.extensions['.ts']=function(module,file){const code=ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,esModuleInterop:true}}).outputText;module._compile(code,file);};
const api=require('../lib/portalPublication.ts');
const SECRET='synthetic-publish-token-only-not-real-0123456789';
delete process.env.VERCEL_ENV;
process.env.MTO_PORTAL_PUBLISH_TOKEN=SECRET;process.env.MTO_PORTAL_LOOKUP_SECRET='synthetic-lookup-token-only-not-real-0123456789';
let passed=0;
const check=(value,message)=>{assert.ok(value,message);passed++;};
const sha=value=>createHash('sha256').update(value).digest('hex');
function snapshot(){return {schema_version:2,owner_lookup_version:2,record_count:2,published_at:new Date().toISOString(),checksum:'c'.repeat(64),
 properties:['a','b'].map(key=>({td_number:'06-0001-00001',public_account_key:key.repeat(64),owner_name:'P***',pin_masked:'PIN-****',
 total_paid:key==='a'?1234.56:789.12,balance:key==='a'?0:42.25,payment_history:[{or_number:'123****',amount:1234.56}]})),owner_lookup_index:{}};}
function descriptor(data,id='f'.repeat(32)){const raw=Buffer.from(JSON.stringify(data)),compressed=gzipSync(raw);return {raw,compressed,
 manifest:{protocol:api.PUBLICATION_PROTOCOL,upload_id:id,compressed_bytes:compressed.length,expanded_bytes:raw.length,
 payload_sha256:sha(compressed),expanded_payload_sha256:sha(raw),checksum:data.checksum,record_count:data.record_count,published_at:data.published_at}};}
function fake(bytes){
 let current=Buffer.from('{"previous":"Keep serving this"}'),etag='original-etag',writes=0,removed=[];const records=new Map();
 const io={
   head:async()=>({etag}),
   get:async(name,options)=>{check(options.access==='private'&&options.useCache===false,'Private origin read required');const data=name.includes('staging')?records.get(name):current;if(!data)return null;return {statusCode:200,stream:new ReadableStream({start(c){c.enqueue(data);c.close();}}),blob:{size:data.length,etag}};},
   put:async()=>{throw Error('Unexpected direct write')},
   del:async name=>{assert.ok(/^portal\/publication-staging\/[a-f0-9]{32}\.json\.gz$/.test(name));removed.push(name);records.delete(name);},
   issueSignedToken:async options=>{check(options.operations.length===1&&options.operations[0]==='put','Only PUT delegated');check(options.maximumSizeInBytes===bytes.compressed.length,'Exact signed upload size');check(!options.pathname.includes('*'),'No wildcard scope');check(options.allowedContentTypes[0]==='application/gzip','Gzip-only upload');return {fake:options.pathname};},
   presignUrl:async(token,options)=>{check(options.access==='private'&&!options.allowOverwrite&&!options.addRandomSuffix,'Private immutable staging');check(options.pathname===token.fake,'Exact file scope');return {presignedUrl:'https://vercel.com/api/blob/?pathname='+encodeURIComponent(options.pathname)+'&vercel-blob-signature=SYNTHETIC'};},
   store:async(data,options)=>{check(options.ifMatch===etag,'Atomic conditional write');check(options.rawBody.equals(bytes.raw),'Exact original JSON bytes');writes++;current=options.rawBody;etag='committed-etag';return {pathname:'portal/portal_snapshot_latest.json'};}
 };
 return {io,records,current:()=>current,writes:()=>writes,removed,change:()=>{etag='newer-publication';}};
}
async function reject(promise,code){await assert.rejects(promise,error=>error instanceof api.PublicationError&&error.code===code);passed++;}
(async()=>{
 check(api.MAX_COMPRESSED_BYTES===33554432&&api.MAX_EXPANDED_BYTES===62914560,'Bounded increased capacity');
 const req=new Request('https://portal.test',{headers:{authorization:'Bearer '+SECRET}});api.authorizePublication(req);check(true,'Authenticated writer accepted');
 assert.throws(()=>api.authorizePublication(new Request('https://portal.test')),/UNAUTHORIZED/);passed++;
 process.env.VERCEL_ENV='preview';assert.throws(()=>api.authorizePublication(req),/PUBLICATION_DISABLED_FOR_PREVIEW/);passed++;delete process.env.VERCEL_ENV;
 for(const [key,value,code] of [['compressed_bytes',33554433,'COMPRESSED_LIMIT_EXCEEDED'],['expanded_bytes',62914561,'EXPANDED_LIMIT_EXCEEDED'],['upload_id','../latest','INVALID_UPLOAD_ID'],['upload_id',['f'.repeat(32)],'INVALID_UPLOAD_ID'],['published_at','2026-10-07','INVALID_PUBLICATION_TIME'],['record_count',0,'INVALID_RECORD_COUNT']]){
  const bad=descriptor(snapshot()).manifest;bad[key]=value;assert.throws(()=>api.validateManifest(bad),e=>e.code===code);passed++;
 }
 const large=snapshot();large.properties[0].synthetic_fixture_padding=randomBytes(6*1024*1024).toString('base64');
 const bytes=descriptor(large),store=fake(bytes);check(bytes.compressed.length>4_500_000,'Fixture exceeds function body limit');
 const prepared=await api.preparePublication(bytes.manifest,store.io);check(JSON.stringify(prepared).length<4096,'Control response remains small');
 check(!JSON.stringify(prepared).includes(SECRET),'Secret absent from response');
 store.records.set('portal/publication-staging/'+bytes.manifest.upload_id+'.json.gz',bytes.compressed);
 const result=await api.commitPublication(prepared.ticket,store.io);check(result.uploaded&&result.payload_sha256===bytes.manifest.payload_sha256,'Entire larger payload verified');
 check(store.writes()===1&&JSON.parse(store.current()).properties.length===2,'No accounts trimmed');check(result.staging_removed&&store.removed.length===1,'Only helper staging object removed after commit');
 const replay=await api.commitPublication(prepared.ticket,store.io);check(replay.replay_verified&&store.writes()===1,'Lost response retry cannot overwrite data');
 await reject(api.commitPublication(prepared.ticket.slice(0,-1)+(prepared.ticket.endsWith('0')?'1':'0'),store.io),'TICKET_AUTHENTICATION_FAILED');
 assert.throws(()=>api.decodeTicket(prepared.ticket,SECRET,Date.now()+21*60*1000),e=>e.code==='TICKET_EXPIRED');passed++;
 const missingBytes=descriptor(snapshot(),'d'.repeat(32)),missing=fake(missingBytes),missingPrep=await api.preparePublication(missingBytes.manifest,missing.io);
 await reject(api.commitPublication(missingPrep.ticket,missing.io),'UPLOAD_NOT_COMPLETE');check(missing.writes()===0,'Incomplete upload does not replace current data');
 const changed=fake(missingBytes),changedPrep=await api.preparePublication(missingBytes.manifest,changed.io);changed.change();
 await reject(api.commitPublication(changedPrep.ticket,changed.io),'PUBLICATION_CHANGED_REVIEW_REQUIRED');check(changed.writes()===0,'Newer publication is preserved');
 const wrong=fake(missingBytes),wrongPrep=await api.preparePublication(missingBytes.manifest,wrong.io);
 wrong.records.set('portal/publication-staging/'+missingBytes.manifest.upload_id+'.json.gz',Buffer.alloc(missingBytes.compressed.length));
 await reject(api.commitPublication(wrongPrep.ticket,wrong.io),'PAYLOAD_HASH_MISMATCH');check(wrong.writes()===0,'Corrupted payload is not promoted');
 for(const [name,mutate,code] of [['owner',s=>s.properties[0].owner_name='RAW OWNER','UNMASKED_OWNER_REJECTED'],['receipt',s=>s.properties[0].payment_history[0].or_number='1234567','UNMASKED_RECEIPT_REJECTED'],['pin',s=>s.properties[0].pin_masked='RAW PIN','UNMASKED_PIN_REJECTED'],['account',s=>s.properties[1].public_account_key=s.properties[0].public_account_key,'ACCOUNT_ISOLATION_FAILED']]){
  const data=snapshot();mutate(data);const item=descriptor(data),fakeStore=fake(item),prep=await api.preparePublication(item.manifest,fakeStore.io);
  fakeStore.records.set('portal/publication-staging/'+item.manifest.upload_id+'.json.gz',item.compressed);await reject(api.commitPublication(prep.ticket,fakeStore.io),code);check(fakeStore.writes()===0,name+' unsafe data never promoted');
 }
 const control=new Request('https://portal.test',{method:'POST',body:'x'.repeat(api.MAX_CONTROL_BYTES+1)});await reject(api.controlBody(control),'BODY_TOO_LARGE');
 console.log(JSON.stringify({passed,scope:'Synthetic IO only, including a >4.5 MB upload. No hosted mutation.'}));
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
