// Optional fresh-browser checks; never use an existing browser profile.
import fs from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import path from 'node:path';
const [kind, file] = process.argv.slice(2);
let browser;
try {
  const module = path.resolve('.benchmark-tools/node_modules/playwright/index.mjs');
  const {chromium} = await import(pathToFileURL(module));
  browser = await chromium.launch({headless: true, args: ['--disable-gpu']});
  const context = await browser.newContext({viewport: {width: 640, height: 640}, serviceWorkers: 'block'});
  const source = await fs.readFile(file, 'utf8');
  await context.route('**/*', route => route.request().url() === 'http://benchmark.invalid/'
    ? route.fulfill({contentType: 'text/html', body: kind === 'snake' ? source : `<body>${source}</body>`})
    : route.abort());
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('http://benchmark.invalid/');
  const checks = kind === 'snake' ? await page.evaluate(() => {
    if (!window.bench) return {api_present: false};
    window.bench.reset(20261013);
    const start = window.bench.state();
    window.bench.step('left');
    const next = window.bench.state();
    window.bench.reset(20261013);
    const again = window.bench.state();
    let seed = 20261013 >>> 0;
    seed ^= seed << 13; seed ^= seed >>> 17; seed ^= seed << 5; seed >>>= 0;
    const cells = [];
    for (let y = 0; y < 20; y++) for (let x = 0; x < 20; x++)
      if (!(y === 10 && [8,9,10].includes(x))) cells.push([x,y]);
    const expectedFood = cells[seed % cells.length];
    for (let i = 0; i < 21; i++) window.bench.step('right');
    const wallDead = window.bench.state().alive === false;
    window.bench.reset(20261013);
    for (let i = 0; i < 10; i++) window.bench.step('up');
    window.bench.step('left'); window.bench.step('left');
    const eaten = window.bench.state();
    window.bench.reset(20261013);
    const fresh = window.bench.state(); fresh.snake[0][0] = -99;
    const copySafe = window.bench.state().snake[0][0] === 10;
    return {api_present: true, initial_snake: JSON.stringify(start.snake) === '[[10,10],[9,10],[8,10]]',
      initial_score: start.score === 0, starts_paused: start.paused === true,
      reversal_ignored: JSON.stringify(next.direction) === '[1,0]',
      paused_step_moves: next.snake[0][0] === 11,
      wall_collision: wallDead, state_copy: copySafe,
      food_growth: eaten.score === 1 && eaten.snake.length === 4 && eaten.alive === true,
      seeded_food: JSON.stringify(start.food) === JSON.stringify(expectedFood),
      seeded_reset: JSON.stringify(start) === JSON.stringify(again)};
  }) : {svg_rendered: await page.locator('svg').count() === 1};
  await page.screenshot({path: file + '.png'});
  console.log(JSON.stringify({status: 'completed', checks, page_errors: errors, screenshot: path.basename(file) + '.png'}));
} catch (error) {
  console.log(JSON.stringify({status: 'error', message: error.message.slice(0, 500)}));
  process.exitCode = 1;
} finally { if (browser) await browser.close(); }
