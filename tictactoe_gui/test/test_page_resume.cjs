'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const web = path.join(__dirname, '../tictactoe_gui/web');
const events = {};
const timers = new Map();
let nextTimer = 0, reads = 0;
const context = {
  document: {hidden: true, addEventListener: (name, fn) => {events[name] = fn;}},
  window: {addEventListener: (name, fn) => {events[name] = fn;}},
  setTimeout: (fn, delay) => {const id = ++nextTimer; timers.set(id, {fn, delay}); return id;},
  clearTimeout: id => timers.delete(id),
  sending: false, token: 'old-token', frame: 'old-frame', renderedPerception: 'old-preview',
  perceptionRequest: {abort() {}},
  refresh: async () => {reads++;}, render() {}, updatePerception() {},
  act() {throw Error('Resume must never submit a command');}
};
vm.createContext(context);
const game = fs.readFileSync(path.join(web, 'game.js'), 'utf8');
vm.runInContext(game.slice(game.indexOf('let pollTimer;'),
                          game.indexOf("perception.addEventListener('toggle'")), context);
(async () => {
  await vm.runInContext('poll()', context);
  assert.equal(timers.size, 1);
  assert.equal([...timers.values()][0].delay, 1500);
  context.document.hidden = false;
  events.visibilitychange(); events.focus(); events.pageshow(); events.online();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(timers.size, 1, 'Resume events must not duplicate polling loops');
  assert.equal([...timers.values()][0].delay, 350);
  assert.equal(context.token, undefined);
  assert.equal(context.frame, undefined);
  assert.equal(reads, 2);

  const canvasEvents = {}; let canvasPaints=0;
  const canvas = {
    document: {hidden:false, addEventListener:(name,fn)=>{canvasEvents[name]=fn;}},
    window: {addEventListener:(name,fn)=>{canvasEvents[name]=fn;}},
    token:'old', imageSequence:10, strokes:[[1,2]], paint:()=>{canvasPaints++;}, poll:()=>{reads++;}
  };
  vm.createContext(canvas);
  const source = fs.readFileSync(path.join(web,'canvas.js'),'utf8');
  vm.runInContext(source.slice(source.indexOf('function resumeCanvas()')),canvas);
  canvasEvents.focus();
  assert.equal(canvas.token,null);
  assert.equal(canvasPaints,1,'Controls must disable immediately while a new session token is pending');
  assert.equal(canvas.imageSequence,undefined);
  assert.deepEqual(canvas.strokes,[[1,2]],'Draft strokes must survive focus changes');
  console.log('PASS: background recovery, one polling loop, no command replay, canvas draft preserved');
})().catch(error => {console.error(error); process.exitCode = 1;});