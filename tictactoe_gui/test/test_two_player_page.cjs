const http=require('node:http'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const web=path.join(__dirname,'../tictactoe_gui/web');
const out=process.env.TICTACTOE_GUI_TEST_OUTPUT || fs.mkdtempSync(path.join(require('node:os').tmpdir(),'two-player-gui-'));
fs.mkdirSync(out,{recursive:true});
let state={state:'ready',busy:false,job:0,message:'Fixture ready',game:null,camera_fresh:true,robot_fresh:true},requests=[];
function status(res,data,code=200){res.writeHead(code,{'Content-Type':'application/json'});res.end(JSON.stringify(data));}
const server=http.createServer((req,res)=>{let u=new URL(req.url,'http://localhost');
 if(req.method==='POST'){let bytes='';req.on('data',c=>bytes+=c);req.on('end',()=>{let d=JSON.parse(bytes);requests.push({path:u.pathname,...d});
 if(u.pathname==='/api/game/start'){state.job++;state.game={size:d.size,mode:d.mode,opponent:d.opponent,phase:'player',revision:state.job,turn:d.mark,human:d.mark,first:d.first,input_source:d.input_source,winner:null,win_length:d.size===3?3:4,board:Array.from({length:d.size},()=>Array(d.size).fill(''))};state.busy=false;state.state='ready';}
 else if(u.pathname==='/api/game/simulate-player'){state.busy=true;state.state='running';state.message='Drawing; camera confirmation pending';}
 status(res,{accepted:true,job:state.job});});return;}
 if(u.pathname==='/api/config')return status(res,{token:'local-fixture-only',environment:'real',vision_available:true,game_modes:['classic','four'],width_mm:140,height_mm:189});
 if(u.pathname==='/api/status')return status(res,state);
 if(u.pathname==='/api/game/perception')return status(res,{error:'No camera in frontend fixture'},503);
 const file=u.pathname==='/'?'game.html':u.pathname.slice(1);if(!['game.html','game.js','game.css'].includes(file)){res.writeHead(404);res.end();return;}
 res.writeHead(200,{'Content-Type':file.endsWith('js')?'text/javascript':file.endsWith('css')?'text/css':'text/html'});res.end(fs.readFileSync(path.join(web,file)));
});
function confirm(r,c){state.game.board[r][c]=state.game.turn;state.game.turn=state.game.turn==='X'?'O':'X';state.game.revision=++state.job;state.busy=false;state.state='ready';}
(async()=>{let browser;await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));try{browser=await chromium.launch({channel:'chrome',headless:true});const p=await browser.newPage({viewport:{width:1440,height:1100}});p.on('dialog',d=>d.accept());let errors=[];p.on('pageerror',e=>errors.push(e.message));await p.goto(`http://127.0.0.1:${server.address().port}/`);await p.waitForFunction(()=>!document.querySelector('#start').disabled);
 for(const [mode,size,mark] of [['3',3,'O'],['four',9,'X']]){
  await p.locator(`input[value="${mode}"]`).check();await p.locator('#opponent').selectOption('human');await p.locator('#mark').selectOption(mark);assert(await p.locator('#first-option').isHidden());assert.equal(await p.locator('#mark-label').innerText(),'First symbol');await p.locator('#start').click();await p.waitForFunction(()=>document.querySelector('#roles').textContent==='Player X · Player O');
  assert.equal(requests.at(-1).opponent,'human');assert.equal(requests.at(-1).first,'player');
  for(let row=0;row<2;row++){const before=state.game.turn;await p.getByRole('button',{name:`Row ${row+1}, column ${size}, Empty`,exact:true}).click();await p.waitForFunction(()=>document.querySelector('#board button').disabled);assert.equal(state.game.board[row][size-1],'','A click must not precommit the cell');assert.equal(requests.at(-1).path,'/api/game/simulate-player');confirm(row,size-1);await p.waitForFunction(([row,size,before])=>document.querySelectorAll('#board button')[row*size+size-1].dataset.mark===before,[row,size,before]);assert((await p.locator('#status').innerText()).includes(`Player ${state.game.turn}'s turn`));}
  await p.screenshot({path:path.join(out,`two-player-${size}.png`),fullPage:true});
  state.game.winner=mark;state.game.phase='finished';await p.waitForFunction(mark=>document.querySelector('#result').textContent===`Player ${mark} wins`,mark);

 }
 await p.locator('#opponent').selectOption('ai');await p.locator('#first').selectOption('player');await p.locator('#start').click();await p.waitForFunction(()=>document.querySelector('#roles').textContent.includes('AI plays'));assert.equal(requests.at(-1).opponent,'ai');assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'gui-result.json'),JSON.stringify({passed:true,requests,tests:['3x3 O first','9x9 X first','X/O alternating','no precommit before confirmation','dual winner labels','AI mode preserved'],pageErrors:errors},null,2));console.log('PASS: actual headless Chrome frontend controls and pending/confirmed turns');
 }finally{if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));}})().catch(e=>{console.error(e);process.exitCode=1});
