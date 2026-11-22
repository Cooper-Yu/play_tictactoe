// Browser fixture only: verifies the explicit resume request, with no robot connection.
const http=require('node:http'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const web=path.join(__dirname,'../tictactoe_gui/web');
let requests=[];
let state={state:'blocked',busy:false,job:4,message:'Interrupted drawing',camera_fresh:true,robot_fresh:true,
 continuation:{available:true,original_job:4,stage:'drawing'},
 game:{size:3,mode:'classic',phase:'blocked',revision:4,turn:'X',human:'X',input_source:'handwriting',opponent:'human',board:Array.from({length:3},()=>Array(3).fill(''))}};
const server=http.createServer((req,res)=>{
 const reply=(data,code=200)=>{res.writeHead(code,{'Content-Type':'application/json'});res.end(JSON.stringify(data));};
 if(req.method==='POST'){
  let body='';req.on('data',b=>body+=b);req.on('end',()=>{requests.push({path:req.url,...JSON.parse(body)});state={...state,state:'running',busy:true};reply({accepted:true,job:5},202);});return;
 }
 if(req.url==='/api/config')return reply({token:'fixture',environment:'real',vision_available:true,width_mm:138,height_mm:177,workstation_url:'/'});
 if(req.url==='/api/status')return reply(state);
 const name=req.url==='/'?'game.html':req.url.slice(1);
 if(!['game.html','game.js','game.css'].includes(name))return reply({},404);
 res.writeHead(200,{'Content-Type':name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html'});res.end(fs.readFileSync(path.join(web,name)));
});
(async()=>{await new Promise(r=>server.listen(0,'127.0.0.1',r));let browser;
 try{
  browser=await chromium.launch({channel:'chrome',headless:true});const p=await browser.newPage();const errors=[];
  p.on('pageerror',e=>errors.push(e.message));p.on('dialog',d=>d.accept());
  await p.goto(`http://127.0.0.1:${server.address().port}/`);
  await p.waitForFunction(()=>!document.querySelector('#resume-turn').hidden && !document.querySelector('#resume-turn').disabled);
  assert(await p.locator('#submit-handwriting').isDisabled());
  await p.locator('#resume-turn').click();
  await p.waitForFunction(()=>document.querySelector('#resume-turn').disabled);
  assert.deepEqual(requests,[{path:'/api/game/resume',revision:4,original_job:4,inspected:true}]);
  assert.deepEqual(errors,[]);
  console.log('PASS: inspected paused turn uses one resume request, never handwriting replay');
 }finally{await browser?.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1;});
