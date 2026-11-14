// 第十四层 · 选线（单击图上的曲线 → 选中它）
// 真浏览器（CDP 驱动无头 Edge）真点，验证：
//   1. 普通模式（不先开框选）单击一条线 → 选中它、底部出现选中条、其它线淡出、列表高亮；
//   2. 再点同一条 / 点空白 / Esc → 取消；
//   3. 「只看这条」只保留它（写 include），再点「恢复全部」按原样还原；
//   4. 选中是纯显示层：点来点去不改数据、不改规格里跟显示无关的东西；
//   5. 收尾整份规格写回，控制台 0 报错。
// 用法： node tests/layer14_select.mjs [port] [fig]
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const PORT = Number(process.argv[2] || 8778);
const FIG = process.argv[3] || "eis_wide";
const EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const CDP = 9335;
const profile = mkdtempSync(join(tmpdir(), "figlab-pick-"));

const sleep = ms => new Promise(r => setTimeout(r, ms));
const bad = [];
const check = (ok, msg, extra) => {
  console.log(`  [${ok ? "通过" : "失败"}] ${msg}${extra === undefined ? "" : "  " + extra}`);
  if (!ok) bad.push(msg + (extra === undefined ? "" : "（" + extra + "）"));
};

const edge = spawn(EDGE, [
  "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
  `--remote-debugging-port=${CDP}`, `--user-data-dir=${profile}`,
  "--window-size=1600,950", "about:blank"
], { stdio: "ignore" });

let ws = null, id = 0;
const waiting = new Map();
const errors = [];

function send(method, params = {}) {
  return new Promise((resolve, reject) => {
    const mid = ++id;
    waiting.set(mid, { resolve, reject });
    ws.send(JSON.stringify({ id: mid, method, params }));
  });
}
async function evaluate(expr, awaitPromise = true) {
  const r = await send("Runtime.evaluate", {
    expression: expr, awaitPromise, returnByValue: true, userGesture: true
  });
  if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails));
  return r.result.value;
}
async function click(x, y) {
  await send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y });
  await send("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", clickCount: 1 });
  await send("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", clickCount: 1 });
  await sleep(260);
}
// 某条曲线中段一点的屏幕坐标（避开端点，免得压到标注/别的线）
async function pointOn(curve, frac = 0.55) {
  return evaluate(`(()=>{
    const ps = S.points.filter(p=>p.curve===${JSON.stringify(curve)});
    const p = ps[Math.max(0, Math.min(ps.length-1, Math.round(ps.length*${frac})))];
    const r = document.querySelector('#stage').getBoundingClientRect();
    return [r.x + p.nx*r.width, r.y + p.ny*r.height];
  })()`);
}
async function emptySpot() {
  // 图区左上角往里一点：坐标轴框外面，基本不会有数据点
  return evaluate(`(()=>{
    const r = document.querySelector('#stage').getBoundingClientRect();
    return [r.x + r.width*0.04, r.y + r.height*0.06];
  })()`);
}

async function main() {
  let ver = null;
  for (let i = 0; i < 60 && !ver; i++) {
    try { ver = await (await fetch(`http://127.0.0.1:${CDP}/json/version`)).json(); }
    catch { await sleep(200); }
  }
  if (!ver) throw new Error("CDP 未就绪");
  const tgt = await (await fetch(`http://127.0.0.1:${CDP}/json/new?about:blank`,
                                 { method: "PUT" })).json();
  ws = new WebSocket(tgt.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  ws.onmessage = ev => {
    const m = JSON.parse(ev.data);
    if (m.id && waiting.has(m.id)) {
      const w = waiting.get(m.id); waiting.delete(m.id);
      m.error ? w.reject(new Error(JSON.stringify(m.error))) : w.resolve(m.result);
    } else if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error") {
      errors.push(m.params.args.map(a => a.value ?? a.description).join(" "));
    } else if (m.method === "Runtime.exceptionThrown") {
      errors.push(m.params.exceptionDetails.text + " " +
                  (m.params.exceptionDetails.exception?.description || ""));
    }
  };
  await send("Runtime.enable");
  await send("Page.enable");
  await send("Page.navigate", { url: `http://127.0.0.1:${PORT}/?fig=${FIG}` });
  for (let i = 0; i < 100; i++) {
    try {
      const n = await evaluate("window.S && S.points ? S.points.length : 0", false);
      if (n > 0) break;
    } catch {}
    await sleep(200);
  }

  console.log("\n[1] 页面就绪");
  const nPts = await evaluate("S.points.length");
  check(nPts > 0, "图上有数据点", nPts + " 点");
  const specOrig = await evaluate("JSON.stringify(S.spec)");
  const incOrig = await evaluate("JSON.stringify(S.spec.series.map(s=>[s.curve,s.include]))");

  // 挑一条参与绘制的曲线
  const curve = await evaluate(
    "(S.spec.series.find(s=>s.include && S.points.some(p=>p.curve===s.curve))||{}).curve");
  check(!!curve, "挑到一条可点的曲线", curve);

  console.log("\n[2] 普通模式单击曲线（不先开框选）");
  const pt = await pointOn(curve);
  // 点哪个点就应该选哪条线：先问浏览器"这个坐标上压着谁"，再拿它当预期
  const expectCurve = await evaluate(`(()=>{
    const el = document.elementFromPoint(${pt[0]}, ${pt[1]});
    const h = el && el.closest ? el.closest('.hot') : null;
    return h ? S.points[+h.dataset.i].curve : null;
  })()`);
  await click(pt[0], pt[1]);
  const st1 = await evaluate(`(()=>({
    aim: S.aim,
    bar: document.querySelector('#aimbar').classList.contains('show'),
    name: document.querySelector('#aimName').textContent,
    cnt: document.querySelector('#aimCnt').textContent,
    body: document.body.classList.contains('hasaim'),
    rowAim: [...document.querySelectorAll('#curveList .curve')].filter(r=>r.classList.contains('aim')).map(r=>r.dataset.curve),
    opac: [...document.querySelectorAll('#svgbox [id^="cv"]')].map(g=>[g.id, g.style.opacity])
  }))()`);
  check(st1.aim === expectCurve && !!expectCurve, "点中哪条线就选中哪条", st1.aim);
  check(st1.bar, "底部弹出选中条");
  check(st1.name.includes(String(expectCurve).split(" ")[0]), "选中条显示曲线名", st1.name);
  check(/\d+ 点/.test(st1.cnt), "选中条显示点数", st1.cnt);
  check(st1.body, "页面进入「有选中」状态");
  check(st1.rowAim.length === 1 && st1.rowAim[0] === expectCurve, "左侧曲线列表只高亮这一行",
        JSON.stringify(st1.rowAim));
  const gidSelf = await evaluate(`S.curveGids[${JSON.stringify(expectCurve)}]`);
  const dimOthers = st1.opac.filter(([gid, op]) => !gid.startsWith("cv" + gidSelf) && op === "0.14");
  const litSelf = st1.opac.filter(([gid, op]) => gid.startsWith("cv" + gidSelf) && op !== "0.14");
  check(dimOthers.length > 0, "其它曲线淡出", dimOthers.length + " 组");
  check(litSelf.length > 0, "选中那条线保持原亮度", litSelf.length + " 组");

  console.log("\n[3] 再点同一条 / 点空白 → 取消");
  await click(pt[0], pt[1]);
  const st2 = await evaluate(`(()=>({aim:S.aim,
    bar:document.querySelector('#aimbar').classList.contains('show')}))()`);
  check(st2.aim === null, "再点同一条线取消选中");
  check(!st2.bar, "选中条收起");
  await click(pt[0], pt[1]);
  const sp = await emptySpot();
  await click(sp[0], sp[1]);
  const st3 = await evaluate("S.aim");
  check(st3 === null, "点空白处取消选中", String(st3));

  console.log("\n[4] 「只看这条」→「恢复全部」");
  await click(pt[0], pt[1]);
  const btn = await evaluate(`(()=>{const r=document.querySelector('#aimFocus').getBoundingClientRect();
    return [r.x+r.width/2, r.y+r.height/2]})()`);
  await click(btn[0], btn[1]);
  await sleep(900);
  const fo = await evaluate(`(()=>({
    focus: S.aimFocus,
    inc: S.spec.series.map(s=>[s.curve, s.include]),
    label: document.querySelector('#aimFocus').textContent,
    drawn: S.spec.series.filter(s=>s.include).length
  }))()`);
  check(fo.focus === expectCurve, "进入「只看这条」", String(fo.focus));
  check(fo.drawn === 1 && fo.inc.find(x => x[0] === expectCurve)[1] === true,
        "只保留选中那条参与绘制", fo.drawn + " 条");
  check(fo.label.includes("恢复"), "按钮变成「恢复全部」", fo.label);

  const btn2 = await evaluate(`(()=>{const r=document.querySelector('#aimFocus').getBoundingClientRect();
    return [r.x+r.width/2, r.y+r.height/2]})()`);
  await click(btn2[0], btn2[1]);
  await sleep(900);
  const back = await evaluate("JSON.stringify(S.spec.series.map(s=>[s.curve,s.include]))");
  check(back === incOrig, "点「恢复全部」按原样还原显隐");
  check((await evaluate("S.aimFocus")) === null, "退出只看模式");

  console.log("\n[5] 「表」按钮跳到这条曲线");
  const tb = await evaluate(`(()=>{const r=document.querySelector('#aimSheet').getBoundingClientRect();
    return [r.x+r.width/2, r.y+r.height/2]})()`);
  await click(tb[0], tb[1]);
  await sleep(500);
  check((await evaluate("S.sheet.curve")) === expectCurve, "表格切到选中曲线", await evaluate("S.sheet.curve"));
  check((await evaluate("S.src")) === "work", "数据源切到「处理后」");

  console.log("\n[6] 换一张图：选中不能残留（否则新图所有曲线都会被判成「非目标」而淡成一片）");
  // 真实点击已经在 [2] 验过；这里只关心"换图时旧选中会不会残留"，直接设一个即可
  await evaluate("setAim(S.points[0].curve)");
  check((await evaluate("S.aim")) !== null, "先选中一条", await evaluate("S.aim"));
  await evaluate("(async()=>{ await loadFigure('eis_main'); return 1; })()");
  await sleep(1200);
  const sw = await evaluate(`(()=>({
    aim: S.aim,
    anyDim: [...document.querySelectorAll('#svgbox [id^="cv"]')].some(g=>g.style.opacity==='0.14'),
    bar: document.querySelector('#aimbar').classList.contains('show')
  }))()`);
  check(sw.aim === null, "换图后自动清空选中", String(sw.aim));
  check(!sw.anyDim, "新图没有被整体淡出");
  check(!sw.bar, "选中条已收起");
  await evaluate("(async()=>{ await loadFigure(" + JSON.stringify(FIG) + "); return 1; })()");
  await sleep(1200);

  console.log("\n[7] Esc 取消");
  await send("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
  await send("Input.dispatchKeyEvent", { type: "keyUp", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
  await sleep(250);
  check((await evaluate("S.aim")) === null, "Esc 取消选中");
  check(!(await evaluate("document.querySelector('#aimbar').classList.contains('show')")),
        "选中条收起");

  console.log("\n[8] 收尾：整份规格写回，用户数据不受影响");
  // 跟 ui_smoke 一样走 /api/export（它就是"按页面这份规格落盘并渲染"），deliver:false 不碰桌面
  await evaluate(`(async()=>{
    const r = await fetch('/api/export', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({figure: S.fid, spec: JSON.parse(${JSON.stringify(specOrig)}), deliver: false})});
    return (await r.json()).ok;
  })()`);
  await sleep(400);
  const after = await evaluate("JSON.stringify(S.spec.series.map(s=>[s.curve,s.include]))");
  check(after === incOrig, "收尾后显隐与开始时一致");
  check((await evaluate("S.points.length")) > 0, "图仍然正常", await evaluate("S.points.length"));
  check(errors.length === 0, "控制台无报错", errors.join(" | "));

  console.log("\n" + "=".repeat(60));
  console.log(bad.length ? `失败 ${bad.length} 项：\n - ` + bad.join("\n - ")
                         : "选线：全部通过");
  console.log("=".repeat(60));
  return bad.length ? 1 : 0;
}

main().then(code => {
  try { ws && ws.close(); } catch {}
  edge.kill();
  setTimeout(() => { try { rmSync(profile, { recursive: true, force: true }); } catch {} process.exit(code); }, 300);
}).catch(e => { console.error("测试崩溃：", e); edge.kill(); process.exit(2); });
