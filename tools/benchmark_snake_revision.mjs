// Independent regression checks for the specific review findings.
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const [file] = process.argv.slice(2);
let browser, checks = {}, errors = [];
try {
  const {chromium} = await import(pathToFileURL(path.resolve('.benchmark-tools/node_modules/playwright/index.mjs')));
  browser = await chromium.launch({headless:true,args:['--disable-gpu']});
  const context = await browser.newContext({viewport:{width:1280,height:1100},serviceWorkers:'block'});
  const source = await fs.readFile(file,'utf8');
  await context.route('**/*', r => r.request().url()==='http://benchmark.invalid/'
    ? r.fulfill({contentType:'text/html',body:source}) : r.abort());
  await context.addInitScript(() => {
    const request = window.requestAnimationFrame.bind(window);
    const cancel = window.cancelAnimationFrame.bind(window);
    window.__reviewFrames = new Set();
    window.requestAnimationFrame = callback => {
      const id = request(t => { window.__reviewFrames.delete(id); callback(t); });
      window.__reviewFrames.add(id); return id;
    };
    window.cancelAnimationFrame = id => {window.__reviewFrames.delete(id);cancel(id);};
  });
  const page = await context.newPage();page.setDefaultTimeout(3000);
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('http://benchmark.invalid/');
  await page.waitForTimeout(100);
  checks = await page.evaluate(() => {
    const zoom = document.querySelector('meta[name=viewport]')?.content || '';
    const canvas=document.querySelector('canvas');
    const described=canvas?.getAttribute('aria-describedby')?.split(/\s+/).some(id=>document.getElementById(id)?.textContent.trim());
    return {zoom_allowed:!/(user-scalable\s*=\s*no|maximum-scale\s*=\s*1(?:\.0)?(?:\s*,|$))/i.test(zoom),
      canvas_description:!!(canvas?.getAttribute('aria-label')||described||canvas?.textContent.trim()),
      factory_present:typeof window.createSnakeGame==='function',
      idle_frames_stopped:window.__reviewFrames.size===0};
  });
  if(checks.factory_present) Object.assign(checks,await page.evaluate(() => {
    const a=window.createSnakeGame(20261013), b=window.createSnakeGame(20261013);
    const before=JSON.stringify(b.state());a.step('up');
    const isolated=JSON.stringify(b.state())===before;
    const snap=b.state();snap.snake[0][0]=-99;snap.direction[0]=-99;
    const copied=b.state().snake[0][0]===10&&b.state().direction[0]===1;
    // A Hamiltonian cycle grows a snake without moving through occupied cells.
    const cycle=[[0,0]];
    for(let y=0;y<20;y++) {
      if(y%2===0) for(let x=1;x<20;x++)cycle.push([x,y]);
      else for(let x=19;x>0;x--)cycle.push([x,y]);
    }
    for(let y=19;y>0;y--)cycle.push([0,y]);
    const index=new Map(cycle.map((v,i)=>[v.join(','),i]));
    const engine=window.createSnakeGame(20261013);
    let state=engine.state(), steps=0;
    while(state.alive&&state.snake.length<400&&steps<160000) {
      const head=state.snake[0],next=cycle[(index.get(head.join(','))+1)%400];
      engine.step(next[0]>head[0]?'right':next[0]<head[0]?'left':next[1]>head[1]?'down':'up');
      state=engine.state();steps++;
    }
    return {independent_engines:isolated,engine_state_copied:copied,
      full_board_reached:state.snake.length===400&&state.score===397,
      full_board_win:state.won===true&&state.food===null&&(!state.alive||state.paused),
      full_board_steps:steps};
  }));
  await page.dispatchEvent('body','keydown',{key:' ',code:'Space',repeat:true});
  checks.pause_autorepeat_ignored=await page.evaluate(()=>window.bench.state().paused);
  await page.evaluate(()=>window.bench.reset(20261013));
  await page.getByRole('button',{name:/^start$/i}).click();
  await page.keyboard.press('ArrowUp');await page.waitForTimeout(180);
  checks.keyboard_works=await page.evaluate(()=>JSON.stringify(window.bench.state().direction)==='[0,-1]');
  await page.emulateMedia({reducedMotion:'reduce'});
  checks.reduced_motion=await page.evaluate(()=>document.getAnimations().length===0);
  await page.getByRole('button',{name:/^pause$/i}).click();await page.waitForTimeout(50);
  checks.pause_frames_stopped=await page.evaluate(()=>window.__reviewFrames.size===0);
  await page.getByRole('button',{name:/^restart$/i}).click();
  checks.restart_frames_stopped=await page.evaluate(()=>window.bench.state().paused&&window.__reviewFrames.size===0);
  Object.assign(checks,await page.evaluate(async()=>{
    const regions=[...document.querySelectorAll('[aria-live=polite],[aria-live=assertive],[role=status],[role=alert]')];
    let mutations=0;const observer=new MutationObserver(rows=>{mutations+=rows.length;});
    for(const node of regions)observer.observe(node,{childList:true,characterData:true,subtree:true});
    window.bench.step('right');window.bench.step('right');window.bench.step('right');
    await Promise.resolve();observer.disconnect();
    return {live_status_present:regions.length>0,unchanged_ticks_do_not_announce:regions.length>0&&mutations===0,
      live_mutations_on_unchanged_ticks:mutations};
  }));
  for(const [width,height] of [[640,640],[375,667],[812,375]]) {
    await page.setViewportSize({width,height});
    await page.evaluate(()=>scrollTo(0,0));
    checks[`header_reachable_${width}x${height}`]=await page.evaluate(()=>{
      const node=document.querySelector('h1,.topbar,.brand,.title');
      return !!node&&node.getBoundingClientRect().top>=-1;
    });
  }
  await page.setViewportSize({width:375,height:667});
  const controls=await page.getByRole('button',{name:/^(move )?up$/i}).count();
  checks.direction_labels=controls===1&&await page.getByRole('button',{name:/^(move )?down$/i}).count()===1&&
    await page.getByRole('button',{name:/^(move )?left$/i}).count()===1&&await page.getByRole('button',{name:/^(move )?right$/i}).count()===1;
  if(checks.direction_labels) {
    await page.getByRole('button',{name:/^restart$/i}).click();await page.getByRole('button',{name:/^start$/i}).click();
    await page.getByRole('button',{name:/^(move )?up$/i}).click();await page.waitForTimeout(180);
    checks.mobile_controls=await page.evaluate(()=>JSON.stringify(window.bench.state().direction)==='[0,-1]');
  }
  await page.screenshot({path:file+'.review.png',fullPage:true});
  console.log(JSON.stringify({checks,page_errors:errors}));
} catch(error) {console.log(JSON.stringify({checks,page_errors:errors,error:error.message}));process.exitCode=1;}
finally{if(browser)await browser.close();}
