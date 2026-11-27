// Local HTTP fixture only. No workstation or robot endpoints are contacted.
const http = require('node:http'), fs = require('node:fs'), path = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const web = path.join(__dirname, '../tictactoe_gui/web');
let posts = 0;
const state = {state:'running',busy:true,job:8,camera_fresh:true,robot_fresh:true,
 game:{size:3,mode:'classic',phase:'drawing_win_line',revision:8,winner:'O',human:'X',
 input_source:'vision',opponent:'ai',turn:'X',win_length:3,
 board:[['O','O','O'],['','O',''],['O','','']],
 winning_cells:[[0,2],[1,1],[2,0]],winning_line:{status:'drawing'}}};
const server = http.createServer((req,res)=>{
 const reply = (data,code=200)=>{res.writeHead(code,{'Content-Type':'application/json'});res.end(JSON.stringify(data));};
 if(req.method==='POST'){posts++;return reply({},400);}
 if(req.url==='/api/config')return reply({token:'fixture',environment:'real',vision_available:true,width_mm:138,height_mm:177});
 if(req.url==='/api/status')return reply(state);
 const file=req.url==='/'?'game.html':req.url.slice(1);
 if(!['game.html','game.js','game.css'].includes(file))return reply({},404);
 res.writeHead(200,{'Content-Type':file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html'});
 res.end(fs.readFileSync(path.join(web,file)));
});
(async()=>{await new Promise(r=>server.listen(0,'127.0.0.1',r));let browser;
 try{
  browser=await chromium.launch({channel:'chrome',headless:true});const p=await browser.newPage();
  const errors=[];p.on('pageerror',e=>errors.push(e.message));
  await p.goto(`http://127.0.0.1:${server.address().port}/`);
  await p.waitForFunction(()=>document.querySelector('#status').textContent==='Drawing the winning line…');
  const line=await p.locator('#win-line').evaluate(el=>({hidden:el.hidden,transform:el.style.transform}));
  assert(!line.hidden);
  const expectedAngle=await p.locator('#board').evaluate(el=>{
   const a=el.children[2].getBoundingClientRect(),b=el.children[6].getBoundingClientRect();
   return Math.atan2((b.top+b.height/2)-(a.top+a.height/2),(b.left+b.width/2)-(a.left+a.width/2));
  });
  const actualAngle=Number(line.transform.match(/rotate\(([-.0-9]+)rad\)/)[1]);
  assert(Math.abs(actualAngle-expectedAngle)<.0001,line.transform);
  state.busy=false;state.state='ready';state.game.phase='finished';state.game.winning_line.status='completed';
  await p.waitForFunction(()=>document.querySelector('#status').textContent!=='Drawing the winning line…');
  assert(!await p.locator('#win-line').evaluate(el=>el.hidden));
  assert.equal(posts,0);assert.deepEqual(errors,[]);
  console.log('PASS: backend win cells align the GUI line; drawing state shown; polling submits no motion');
 }finally{await browser?.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1;});
