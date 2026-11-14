// 第十五层 · 选线按钮（点「◎ 选线」→ 鼠标扫过就亮 → 单击选中 → 去改它）
// 真浏览器（CDP 驱动无头 Edge），验证：
//   1. 工具条上有「◎ 选线」按钮，初始没激活；
//   2. 点它才进模式：光标变十字、按钮点亮、状态栏给提示；
//   3. 鼠标移到线附近（离点 20 px，普通模式点不到的距离）→ 那条线亮、其余变淡、旁边报名字点数；
//   4. 单击 → 选中它、自动退出模式、右上角选中条出现；
//   5. 选中后点「删点」→ 进框选模式且下拉已锁定这条线（选择 → 改动的闭环）；
//   6. 互斥：开框选/移线时点「选线」会把它们关掉，反之亦然；
//   7. Esc 退出模式；收尾整份规格写回，控制台 0 报错。
// 用法： node tests/layer15_pick.mjs [port] [fig]
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const PORT = Number(process.argv[2] || 8778);
const FIG = process.argv[3] || "eis_wide";
const EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const CDP = 9336;
const profile = mkdtempSync(join(tmpdir(), "figlab-aimbtn-"));

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
const move = (x, y) => send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y });
async function click(x, y, hold = 260) {
  await move(x, y);
  await send("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", clickCount: 1 });
  await send("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", clickCount: 1 });
  await sleep(hold);
}
async function esc() {
  await send("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
  await send("Input.dispatchKeyEvent", { type: "keyUp", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
  await sleep(220);
}
const centerOf = sel => evaluate(`(()=>{const r=document.querySelector(${JSON.stringify(sel)}).getBoundingClientRect();
  return [r.x+r.width/2, r.y+r.height/2]})()`);
// 某条曲线中段某点的屏幕坐标，往下偏 20 px（有意离开顶点：普通模式 16 px 门槛点不到）
async function nearCurve(curve, frac = 0.5, dy = 20) {
  return evaluate(`(()=>{
    const ps = S.points.filter(p=>p.curve===${JSON.stringify(curve)});
    const p = ps[Math.max(0, Math.min(ps.length-1, Math.round(ps.length*${frac})))];
    const r = document.querySelector('#stage').getBoundingClientRect();
    return [r.x + p.nx*r.width, r.y + p.ny*r.height + ${dy}];
  })()`);
}
const pickState = () => evaluate(`(()=>({
  on: S.pickMode,
  btn: document.querySelector('#aimToggle').classList.contains('on'),
  body: document.body.classList.contains('pickmode'),
  hover: S.hoverCurve,
  tip: getComputedStyle(document.querySelector('#tip')).display,
  tipText: document.querySelector('#tip').textContent,
  aim: S.aim,
  bar: document.querySelector('#aimbar').classList.contains('show')
}))()`);

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
  await sleep(900);

  console.log("\n[1] 页面就绪，工具条上有「选线」按钮");
  const specOrig = await evaluate("JSON.stringify(S.spec)");
  const nPts = await evaluate("S.points.length");
  check(nPts > 0, "图上有数据点", nPts + " 点");
  const btnText = await evaluate("document.querySelector('#aimToggle').textContent");
  check(btnText.includes("选线"), "按钮文案是「选线」", btnText.trim());
  const st0 = await pickState();
  check(st0.on === false && !st0.btn, "初始没进选线模式");
  check((await evaluate("getComputedStyle(document.querySelector('#viewport')).cursor")) !== "crosshair",
        "初始光标不是十字");

  const curve = await evaluate(
    "(S.spec.series.find(s=>s.include && S.points.some(p=>p.curve===s.curve))||{}).curve");
  check(!!curve, "挑到一条可点的曲线", curve);

  console.log("\n[2] 点「选线」→ 进模式");
  const bb = await centerOf("#aimToggle");
  await click(bb[0], bb[1]);
  const st1 = await pickState();
  check(st1.on === true, "进了选线模式");
  check(st1.btn, "按钮点亮");
  check(st1.body, "页面进入选线状态");
  check((await evaluate("getComputedStyle(document.querySelector('#viewport')).cursor")) === "crosshair",
        "光标变成十字");
  check((await evaluate("document.querySelector('#status').textContent")).includes("选线模式"),
        "状态栏提示怎么用", await evaluate("document.querySelector('#status').textContent"));

  console.log("\n[3] 鼠标靠近线（离顶点 20 px）：该亮的那条亮起来");
  const pt = await nearCurve(curve);
  // 这一点的容差确实靠"选线模式放宽到 26 px"才够：普通 16 px 在这里是空的
  const tol = await evaluate(`(()=>{
    const r = document.querySelector('#stage').getBoundingClientRect();
    const nx = (${pt[0]} - r.left) / r.width, ny = (${pt[1]} - r.top) / r.height;
    return [!!nearestCurve(nx, ny, r.width, r.height, 16),
            !!nearestCurve(nx, ny, r.width, r.height, 26)];
  })()`);
  check(tol[0] === false && tol[1] === true, "20 px 处靠放宽的容差才点得到", JSON.stringify(tol));
  await move(pt[0], pt[1]);
  await sleep(260);
  const st2 = await pickState();
  check(!!st2.hover, "鼠标扫过时高亮了一条线", String(st2.hover));
  check(st2.tip === "block" && st2.tipText.includes("单击选中"), "旁边报出「单击选中…」", st2.tipText);
  check(/\d+ 点/.test(st2.tipText), "提示里带点数", st2.tipText);
  const gidH = await evaluate(`S.curveGids[${JSON.stringify(st2.hover)}]`);
  const paint = await evaluate(`(()=>{
    const gids = new Set([...document.querySelectorAll('#svgbox [id^="cv"]')].map(g=>g.id));
    const mine = [...gids].filter(x=>x.startsWith('cv' + ${gidH}));
    const others = [...gids].filter(x=>!x.startsWith('cv' + ${gidH}));
    const op = id => (document.getElementById(id)||{}).style.opacity;
    const thick = id => { const g = document.getElementById(id);
      const p = g.querySelector('path'); if(!p) return 0;
      return parseFloat(p.style.strokeWidth || 0) / (parseFloat(p.dataset.w0 || 0) || 1); };
    return {
      dim: others.map(op).filter(v=>v==='0.32').length,
      lit: mine.map(op).filter(v=>!v).length,
      thickLine: Math.max(...mine.filter(i=>i.includes('-line-')).map(thick), 0),
      thickOther: Math.max(...others.filter(i=>i.includes('-line-')).map(thick), 0)
    };
  })()`);
  check(paint.dim > 0, "其它曲线变淡（0.32）", paint.dim + " 组");
  check(paint.lit > 0, "悬停那条保持原亮度", paint.lit + " 组");
  check(paint.thickLine > 1.2, "悬停那条线加粗", paint.thickLine.toFixed(2) + "×");
  check(paint.thickOther < 1.2, "其它线没被加粗", paint.thickOther.toFixed(2) + "×");

  console.log("\n[4] 单击 → 选中它，模式自动退出");
  await click(pt[0], pt[1], 420);
  const st3 = await pickState();
  check(st3.aim === st2.hover, "选中的就是刚才亮起来的那条", st3.aim);
  check(st3.on === false && !st3.btn, "选完自动退出选线模式");
  check(st3.bar, "右上角选中条出现");
  check((await evaluate("document.querySelector('#aimName').textContent"))
          .includes(String(st3.aim).split(" ")[0]), "选中条写着曲线名",
        await evaluate("document.querySelector('#aimName').textContent"));
  check(st3.tip === "none", "提示气泡收起");

  console.log("\n[5] 选中后「删点」：选择 → 改动的闭环");
  const ab = await centerOf("#aimBox");
  await click(ab[0], ab[1], 400);
  const box = await evaluate(`(()=>({
    mode: S.boxMode,
    curve: S.boxCurveList.length ? S.boxCurveList[+document.querySelector('#boxCurve').value] : null,
    aim: S.aim
  }))()`);
  check(box.mode === true, "进入框选模式");
  check(!!box.curve && box.curve.curve === st3.aim, "框选范围已锁定这条线",
        box.curve && box.curve.curve);
  await esc();
  const afterEsc = await evaluate("(()=>({mode:S.boxMode, aim:S.aim}))()");
  check(afterEsc.mode === false, "Esc 退出框选");
  check(afterEsc.aim === st3.aim, "退出框选不丢选中", String(afterEsc.aim));

  console.log("\n[6] 模式和按钮互斥");
  await click(bb[0], bb[1]);                      // 再进选线
  check((await evaluate("S.pickMode")) === true, "再点「选线」重新进入");
  const bt = await centerOf("#boxToggle");
  await click(bt[0], bt[1], 400);
  const mix1 = await evaluate("(()=>({pick:S.pickMode, box:S.boxMode}))()");
  check(mix1.box === true && mix1.pick === false, "开框选会把选线关掉", JSON.stringify(mix1));
  await click(bb[0], bb[1], 300);
  const mix2 = await evaluate("(()=>({pick:S.pickMode, box:S.boxMode}))()");
  check(mix2.pick === true && mix2.box === false, "点选线会把框选关掉", JSON.stringify(mix2));
  const mt = await centerOf("#moveToggle");
  await click(mt[0], mt[1], 300);
  const mix3 = await evaluate("(()=>({pick:S.pickMode, move:S.moveMode}))()");
  check(mix3.move === true && mix3.pick === false, "开移线会把选线关掉", JSON.stringify(mix3));
  await click(mt[0], mt[1], 300);                 // 移线关掉，免得后面拖到线

  console.log("\n[7] Esc 退出选线模式");
  await click(bb[0], bb[1]);
  await esc();
  const escState = await pickState();
  check(escState.on === false && !escState.btn, "Esc 退出选线模式");
  check(escState.hover === null, "悬停高亮已清空", String(escState.hover));

  console.log("\n[8] 收尾：整份规格写回，用户数据不受影响");
  await evaluate(`(async()=>{
    const r = await fetch('/api/export', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({figure: S.fid, spec: JSON.parse(${JSON.stringify(specOrig)}), deliver: false})});
    return (await r.json()).ok;
  })()`);
  await sleep(500);
  check((await evaluate("S.points.length")) > 0, "图仍然正常", await evaluate("S.points.length"));
  check((await evaluate("document.querySelectorAll('#svgbox [id^=\"cv\"]').length")) > 1,
        "曲线都还画着");
  check(errors.length === 0, "控制台无报错", errors.join(" | "));

  console.log("\n" + "=".repeat(60));
  console.log(bad.length ? `失败 ${bad.length} 项：\n - ` + bad.join("\n - ")
                         : "选线按钮：全部通过");
  console.log("=".repeat(60));
  return bad.length ? 1 : 0;
}

main().then(code => {
  try { ws && ws.close(); } catch {}
  edge.kill();
  setTimeout(() => { try { rmSync(profile, { recursive: true, force: true }); } catch {} process.exit(code); }, 300);
}).catch(e => { console.error("测试崩溃：", e); edge.kill(); process.exit(2); });
