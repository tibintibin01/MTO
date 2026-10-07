// Narrow, expiring build-only acceptance; never suppress production findings.
const fs=require('node:fs'),path=require('node:path'),{spawnSync}=require('node:child_process');
const ADVISORY='https://github.com/advisories/GHSA-vfj7-8cjw-p6xm';
const ROOT=path.resolve(__dirname,'..'),REPO=path.resolve(ROOT,'..');
const riskPath=path.join(REPO,'governance/accepted-risks/public-portal-build-only-braces-20261007.json');
function findings(report){
 if(!report||report.auditReportVersion!==2||!report.vulnerabilities||typeof report.vulnerabilities!=='object'||report.error)throw Error('AUDIT_REPORT_UNAVAILABLE');
 return report.vulnerabilities;
}
function evaluate(full,production,lock,risk,{now=Date.now(),trustedSource=false}={}){
 const all=findings(full),runtime=findings(production),blocking=[],accepted=[];
 if(Object.keys(runtime).length)blocking.push('PRODUCTION_VULNERABILITIES');
 const approved=risk.status==='APPROVED'&&risk.advisory==='GHSA-vfj7-8cjw-p6xm'&&risk.affected_package==='braces'&&
  risk.distribution_scope==='PUBLIC_PORTAL_TRUSTED_BUILD_ONLY'&&risk.review_due_date==='2026-10-14'&&
  risk.expires_at==='2026-10-14T23:59:59+08:00'&&Number.isFinite(Date.parse(risk.approved_at_utc))&&
  Date.parse(risk.approved_at_utc)<=now&&now<=Date.parse(risk.expires_at)&&trustedSource;
 const roots=new Map();
 function onlyApproved(name,seen=new Set()){
  if(roots.has(name))return roots.get(name);
  const item=all[name];if(!item||seen.has(name)||!Array.isArray(item.via)||!item.via.length)return false;
  const next=new Set(seen);next.add(name);
  const result=item.via.every(v=>typeof v==='string'?onlyApproved(v,next):
   v&&v.url===ADVISORY&&v.name==='braces'&&v.dependency==='braces'&&v.range==='<=3.0.3');
  roots.set(name,result);return result;
 }
 for(const [name,item] of Object.entries(all)){
  if(!['moderate','high','critical'].includes(item.severity))continue;
  const devOnly=Array.isArray(item.nodes)&&item.nodes.length>0&&item.nodes.every(node=>lock.packages?.[node]?.dev===true);
  if(approved&&devOnly&&onlyApproved(name))accepted.push(name);else blocking.push(name);
 }
 return {status:blocking.length?'BLOCKED':accepted.length?'PASS_WITH_ACCEPTED_BUILD_RISK':'PASS',
  production_findings:Object.keys(runtime).length,blocking,accepted_build_findings:accepted,
  advisory:accepted.length?'GHSA-vfj7-8cjw-p6xm':null,review_due:accepted.length?risk.review_due_date:null};
}
function trustedSource(){
 const remote=spawnSync('git',['-C',REPO,'remote','get-url','origin'],{encoding:'utf8',timeout:15000});
 if(remote.status!==0||remote.stdout.trim().replace(/\.git$/,'').replace(/\/$/,'').toLowerCase()!=='https://github.com/tibintibin01/mto')return false;
 const event=process.env.GITHUB_EVENT_NAME;
 if(event==='pull_request_target')return false;
 if(event==='pull_request'){
  try{const data=JSON.parse(fs.readFileSync(process.env.GITHUB_EVENT_PATH,'utf8'));
   return data.pull_request?.head?.repo?.fork===false&&
    data.pull_request.head.repo.full_name.toLowerCase()==='tibintibin01/mto'&&
    data.pull_request.base.repo.full_name.toLowerCase()==='tibintibin01/mto';
  }catch{return false;}
 }
 return !event||['push','workflow_dispatch'].includes(event);
}
function audit(omitDev){
 const args=['audit','--json',...(omitDev?['--omit=dev']:[])];
 const result=process.platform==='win32'?spawnSync('cmd.exe',['/d','/s','/c','npm.cmd '+args.join(' ')],{cwd:ROOT,encoding:'utf8',timeout:120000,maxBuffer:20*1024*1024,windowsHide:true}):
  spawnSync('npm',args,{cwd:ROOT,encoding:'utf8',timeout:120000,maxBuffer:20*1024*1024});
 if(![0,1].includes(result.status))throw Error('AUDIT_COMMAND_UNAVAILABLE');
 try{return JSON.parse(result.stdout);}catch{throw Error('AUDIT_REPORT_UNAVAILABLE');}
}
function main(){
 try{
  const result=evaluate(audit(false),audit(true),JSON.parse(fs.readFileSync(path.join(ROOT,'package-lock.json'),'utf8')),
   JSON.parse(fs.readFileSync(riskPath,'utf8')),{trustedSource:trustedSource()});
  console.log(JSON.stringify(result,null,2));return result.status==='BLOCKED'?2:0;
 }catch{console.error('SECURITY AUDIT BLOCKED: complete reports/approval/source validation unavailable. No exception was assumed.');return 2;}
}
module.exports={evaluate};if(require.main===module)process.exitCode=main();
