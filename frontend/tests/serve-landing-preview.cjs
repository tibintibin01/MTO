// Local-only preview with synthetic lookup settings and disabled blob storage.
const fs=require('node:fs/promises'),path=require('node:path'),os=require('node:os'),net=require('node:net');
const {spawn}=require('node:child_process');
const {SECRET,snapshot}=require('./property-preview-fixture.cjs');
const ROOT=path.resolve(__dirname,'..');
(async()=>{
  const directory=await fs.mkdtemp(path.join(os.tmpdir(),'mto-landing-preview-'));
  const fixture=path.join(directory,'snapshot.json');
  await fs.writeFile(fixture,JSON.stringify(snapshot()));
  const probe=net.createServer();await new Promise(resolve=>probe.listen(0,'127.0.0.1',resolve));
  const port=probe.address().port;await new Promise(resolve=>probe.close(resolve));
  const child=spawn(process.execPath,[path.join(ROOT,'node_modules/next/dist/bin/next'),'start',
    '--hostname','127.0.0.1','--port',String(port)],{cwd:ROOT,windowsHide:true,stdio:'inherit',env:{...process.env,
      NODE_ENV:'production',MTO_PORTAL_LOOKUP_SECRET:SECRET,
      MTO_PORTAL_PUBLISH_TOKEN:SECRET,BLOB_READ_WRITE_TOKEN:'',MTO_PORTAL_SNAPSHOT_PATH:fixture}});
  console.log('LOCAL DESIGN PREVIEW (synthetic status, no real records): http://127.0.0.1:'+port);
  // Refresh only the generated local timestamp; all example records stay synthetic.
  const timer=setInterval(async()=>{try{const snapshot=JSON.parse(await fs.readFile(fixture,'utf8'));
    snapshot.published_at=new Date().toISOString();await fs.writeFile(fixture,JSON.stringify(snapshot));}catch(error){
      console.error('Local fixture refresh failed: '+error.name);}},3600000);
  child.on('exit',code=>{clearInterval(timer);process.exitCode=code||0;});
  for(const signal of ['SIGINT','SIGTERM'])process.on(signal,()=>{clearInterval(timer);child.kill();});
})().catch(error=>{console.error(error.message);process.exitCode=1;});
