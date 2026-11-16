'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../tictactoe_gui/web/workbench.js'),'utf8');
const code=source.slice(source.indexOf('async function poll()'),source.indexOf('function drawRaw()'));
let active=0,maximum=0,calls=0,release;
const context=vm.createContext({polling:false,state:{camera:{}},render(){},AbortSignal,
  fetch(){calls++;active++;maximum=Math.max(maximum,active);return new Promise(resolve=>{
    release=()=>{active--;resolve({ok:true,json:async()=>({state:'ready',fresh:true,camera:{}})})};});}});
vm.runInContext(code,context);
(async()=>{
 const first=context.poll();
 await Promise.all(Array.from({length:20},()=>context.poll()));
 assert.equal(calls,1);assert.equal(maximum,1);
 release();await first;assert.equal(context.state.state,'ready');assert.equal(context.polling,false);
 context.fetch=async()=>{throw new Error('simulated timeout')};
 await context.poll();assert.equal(context.polling,false);assert.equal(context.state.fresh,false);
 context.fetch=async()=>({ok:true,json:async()=>({state:'ready',fresh:true,camera:{}})});
 await context.poll();assert.equal(context.state.fresh,true);
 console.log('Polling: overlapping requests coalesce, failure releases guard, recovery resumes');
})().catch(e=>{console.error(e);process.exitCode=1});