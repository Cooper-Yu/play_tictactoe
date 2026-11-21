// Browser acceptance fixture only: does not launch ROS or move any robot.
const http=require('node:http'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const web=path.join(__dirname,'../tictactoe_gui/web');
let state={state:'ready',busy:false,job:0,message:'Fixture',game:null},requests=[];
function reply(res,data,code=200){res.writeHead(code,{'Content-Type':'application/json'});res.end(JSON.stringify(data));}
const server=http.createServer((req,res)=>{
 if(req.method==='POST'){let body='';req.on('data',c=>body+=c);req.on('end',()=>{const d=JSON.parse(body);requests.push({path:req.url,...d});state.job++;
 if(req.url==='/api/game/start')state.game={...d,phase:'player',revision:state.job,turn:d.mark,human:d.mark,board:Array.from({length:d.size},()=>Array(d.size).fill(''))};
 if(req.url==='/api/game/handwriting'){state.busy=true;state.state='running';}
 reply(res,{accepted:true,job:state.job});});return;}
 if(req.url==='/api/config')return reply(res,{token:'fixture',environment:'sim',vision_available:true});
 if(req.url==='/api/status')return reply(res,state);
 const name=req.url==='/'?'game.html':req.url.slice(1);
 if(!['game.html','game.js','game.css'].includes(name))return reply(res,{},404);
 res.writeHead(200,{'Content-Type':name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html'});res.end(fs.readFileSync(path.join(web,name)));
});
(async()=>{await new Promise(r=>server.listen(0,'127.0.0.1',r));let browser;
 try{browser=await chromium.launch({channel:'chrome',headless:true});const p=await browser.newPage({viewport:{width:1400,height:1000}});let errors=[];p.on('pageerror',e=>errors.push(e.message));p.on('dialog',d=>d.accept());await p.goto(`http://127.0.0.1:${server.address().port}/`);await p.waitForFunction(()=>!document.querySelector('#start').disabled);
 for(const mode of ['3','four']){
 await p.locator(`input[value="${mode}"]`).check();await p.locator('#opponent').selectOption('human');await p.locator('#input-source').selectOption('handwriting');await p.locator('#start').click();await p.locator('#handwriting').waitFor({state:'visible'});
 const b=await p.locator('#handwriting').boundingBox();
 async function line(a,c){await p.mouse.move(b.x+a[0]*b.width,b.y+a[1]*b.height);await p.mouse.down();await p.mouse.move(b.x+c[0]*b.width,b.y+c[1]*b.height,{steps:6});await p.mouse.up();}
 await line([.1,.1],[.2,.2]);await line([.2,.1],[.1,.2]);await p.locator('#undo-stroke').click();assert.equal(await p.locator('#stroke-count').innerText(),'1 strokes');await p.locator('#clear-draft').click();assert(await p.locator('#submit-handwriting').isDisabled());
 await line([.1,.1],[.2,.2]);await line([.2,.1],[.1,.2]);const beforeResume=requests.length;await p.evaluate(()=>window.dispatchEvent(new Event('pageshow')));await p.waitForTimeout(1100);assert.equal(requests.length,beforeResume);assert.equal(await p.locator('#stroke-count').innerText(),'2 strokes');
 await p.locator('#submit-handwriting').click();await p.waitForFunction(()=>document.querySelector('#submit-handwriting').disabled);const request=requests.at(-1);assert.equal(request.path,'/api/game/handwriting');assert.equal(request.strokes.length,2);assert(!('row' in request));assert(!('col' in request));assert.equal(state.game.board[0][0],'');assert.equal(state.game.turn,'X');
 state.game.board[0][0]='X';state.game.turn='O';state.game.revision=state.job;state.busy=false;state.state='done';await p.waitForFunction(()=>document.querySelector('#board button').dataset.mark==='X');assert((await p.locator('#status').innerText()).includes("Player O's turn"));
 }
 assert.deepEqual(errors,[]);console.log('PASS: 3x3/9x9 handwriting, undo, clear, poll retention, row/column-free request, camera-gated turns, resume without replay');
 }finally{if(browser)await browser.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1});
