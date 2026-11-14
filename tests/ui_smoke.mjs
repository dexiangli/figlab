// 真实交互冒烟测试：用 CDP 驱动无头 Edge，真点按钮、真拖曲线、真选单元格。
// 不装任何 npm 包，Node 22 自带 WebSocket 与 fetch。
// 用法： node tests/ui_smoke.mjs [port] [fig]
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const PORT = Number(process.argv[2] || 8778);
const FIG = process.argv[3] || "eis_wide";
const EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const CDP = 9333;
const profile = mkdtempSync(join(tmpdir(), "figlab-cdp-"));

const sleep = ms => new Promise(r => setTimeout(r, ms));
// 等某个表达式变真（渲染要排队，固定 sleep 不可靠）
async function waitFor(expr, ms = 12000, step = 150) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    try { if (await evaluate(expr)) return true; } catch {}
    await sleep(step);
  }
  return false;
}

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

async function click(x, y, mods = 0) {
  await send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y, modifiers: mods });
  await send("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left",
                                           clickCount: 1, modifiers: mods });
  await send("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left",
                                           clickCount: 1, modifiers: mods });
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
    } catch { /* 页面还没就绪 */ }
    await sleep(200);
  }

  const out = {};
  out.points = await evaluate("S.points.length");
  // 真实图可能在用（用户自己删过点），所以只比"跑测试前后有没有多出来"，
  // 不假设数据集是干净的。
  await waitFor("!!(S.sheet && S.sheet.data)", 15000);
  out.excludedBase = await evaluate(
    "(S.sheet.data && S.sheet.data.rows || []).filter(r=>String(r.include)!=='1').length");
  out.connectOrig = await evaluate("connectNow()");
  // 这份图是用户真实在用的：整份规格留底，收尾原样写回
  out.specOrig = await evaluate("JSON.stringify(S.spec)");
  out.fastBefore = await evaluate("S.spec.series.filter(s=>s.off_x||s.off_y).length");

  // ---- 1. 真点一次「适应」按钮，看状态文本有没有立刻变
  const fitBox = await evaluate("(()=>{const r=document.querySelector('#fit').getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]})()");
  await click(fitBox[0], fitBox[1]);
  await sleep(120);

  // ---- 2. 点单元格 + Shift 点另一格：Excel 式整块选中
  const cells = await evaluate(`(()=>{
    const tds=[...document.querySelectorAll('#sheetBox td[data-field]')];
    const a=tds[12], b=tds[12+18];
    const ra=a.getBoundingClientRect(), rb=b.getBoundingClientRect();
    return {a:[ra.x+6,ra.y+6], b:[rb.x+6,rb.y+6], fieldA:a.dataset.field, fieldB:b.dataset.field};
  })()`);
  await click(cells.a[0], cells.a[1]);
  await sleep(80);
  out.selAfterClick = await evaluate("S.sheet.sel.size");
  const SHIFT = 8;
  await click(cells.b[0], cells.b[1], SHIFT);
  await sleep(120);
  out.selAfterShift = await evaluate("S.sheet.sel.size");
  out.selCells = await evaluate("document.querySelectorAll('#sheetBox td.selcell').length");

  // ---- 3. 真拖一条曲线（移线模式）
  await evaluate("document.querySelector('#moveToggle').click()");
  const pt = await evaluate(`(()=>{
    const p=S.points.find(p=>p.curve==='${(await evaluate("(S.spec.series.find(s=>s.include)||{}).curve"))}');
    const r=document.querySelector('#stage').getBoundingClientRect();
    return {x:r.x+p.nx*r.width, y:r.y+p.ny*r.height, curve:p.curve,
            off0:[p.off_x||0,p.off_y||0]};
  })()`);
  out.dragCurve = pt.curve;
  out.offBefore = await evaluate("S.spec.series.map(s=>[s.curve,s.off_x||0,s.off_y||0])");
  await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: pt.x, y: pt.y });
  await send("Input.dispatchMouseEvent", { type: "mousePressed", x: pt.x, y: pt.y,
                                           button: "left", clickCount: 1 });
  for (let k = 1; k <= 4; k++) {
    await send("Input.dispatchMouseEvent", { type: "mouseMoved",
                                             x: pt.x, y: pt.y - k * 6, button: "left" });
    await sleep(70);
  }
  await send("Input.dispatchMouseEvent", { type: "mouseReleased", x: pt.x, y: pt.y - 24,
                                           button: "left", clickCount: 1 });
  await sleep(700);
  out.offsetAfterDrag = await evaluate(
    `(()=>{const s=S.spec.series.find(x=>x.curve===${JSON.stringify(pt.curve)});return [s.off_x||0,s.off_y||0]})()`);
  out.offsetChip = await evaluate("document.querySelectorAll('#curveList .ofs').length");
  out.status = await evaluate("$('status').textContent");
  // 移线模式用完就关：它会把后面的单击抢成"拖线"（本来也是真实用法，不该留着）
  await evaluate("document.querySelector('#moveToggle').click()");
  out.moveModeOff = await evaluate("!!S.moveMode === false");

  // ---- 4. 归零：把这一轮真的动过的曲线（可能不止一条）全部复位
  await evaluate(`(async()=>{
     for(const s of S.spec.series){
       if(Math.abs(s.off_x||0)>1e-9 || Math.abs(s.off_y||0)>1e-9){
         const d=await post('/api/curve-shift',{figure:S.fid,curve:s.curve,dx:0,dy:0});
         if(d.ok) S.spec=d.spec;
       }
     }
     return true; })()`);
  await sleep(300);
  out.offsetAfterReset = await evaluate(
    `(()=>{const s=S.spec.series.find(x=>x.curve===${JSON.stringify(pt.curve)});return [s.off_x||0,s.off_y||0]})()`);
  out.offsetMax = await evaluate("Math.max(0,...S.spec.series.map(s=>Math.abs(s.off_x||0)+Math.abs(s.off_y||0)))");

  // ---- 5. 快速通道耗时 vs 全量导出耗时（服务端自己报的响应时间，用页面计时）
  out.fastMs = await evaluate(`(async()=>{const t=performance.now();
     await post('/api/spec',{figure:S.fid,patch:{style:{line_width_pt:S.spec.style.line_width_pt}},fast:true});
     return Math.round(performance.now()-t)})()`);
  out.fullMs = await evaluate(`(async()=>{const t=performance.now();
     const d=await post('/api/export',{figure:S.fid});
     return [Math.round(performance.now()-t), d.export_status, d.verify_status]})()`);

  // ---- 6. 需求单真的没了
  out.hasReq = await evaluate("!!document.querySelector('#reqSec') || !!document.querySelector('#reqTop')");

  // ---- 7. 框选删点：真拉一个框 → 点被圈中 → Esc 取消（不改任何数据）
  await evaluate("document.querySelector('#boxToggle').click()");
  out.boxMode = await evaluate("!!S.boxMode");
  const box = await evaluate(`(()=>{const r=document.querySelector('#stage').getBoundingClientRect();
     return [r.x + r.width*0.30, r.y + r.height*0.30,
             r.x + r.width*0.72, r.y + r.height*0.66]})()`);
  await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: box[0], y: box[1] });
  await send("Input.dispatchMouseEvent", { type: "mousePressed", x: box[0], y: box[1],
                                           button: "left", clickCount: 1 });
  for (let k = 1; k <= 5; k++) {
    await send("Input.dispatchMouseEvent", {
      type: "mouseMoved", button: "left",
      x: box[0] + (box[2] - box[0]) * k / 5, y: box[1] + (box[3] - box[1]) * k / 5 });
    await sleep(50);
  }
  out.marqueeSeen = await evaluate("$('marquee').style.display === 'block'");
  await send("Input.dispatchMouseEvent", { type: "mouseReleased", x: box[2], y: box[3],
                                           button: "left", clickCount: 1 });
  await sleep(250);
  out.picked = await evaluate("(S.picked||[]).length");
  out.pickedDots = await evaluate("document.querySelectorAll('#hotlayer .hot.pick').length");
  out.barShown = await evaluate("$('boxbar').classList.contains('show')");
  out.boxInfo = await evaluate("$('boxInfo').textContent.trim()");
  // Esc 取消，不能动数据
  await send("Input.dispatchKeyEvent", { type: "rawKeyDown", key: "Escape",
                                         code: "Escape", windowsVirtualKeyCode: 27 });
  await send("Input.dispatchKeyEvent", { type: "keyUp", key: "Escape",
                                         code: "Escape", windowsVirtualKeyCode: 27 });
  await sleep(200);
  out.pickedAfterEsc = await evaluate("(S.picked||[]).length");

  // 操作条按钮必须真的能点到（框选模式下按在操作条上不能又起一个框）
  await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: box[0], y: box[1] });
  await send("Input.dispatchMouseEvent", { type: "mousePressed", x: box[0], y: box[1],
                                           button: "left", clickCount: 1 });
  await send("Input.dispatchMouseEvent", { type: "mouseMoved", button: "left",
                                           x: box[2], y: box[3] });
  await sleep(60);
  await send("Input.dispatchMouseEvent", { type: "mouseReleased", x: box[2], y: box[3],
                                           button: "left", clickCount: 1 });
  await sleep(250);
  out.pickedAgain = await evaluate("(S.picked||[]).length");
  // 把提交动作换成桩：只验证按钮→动作这段接线，绝不动真实数据
  await evaluate("window.__origBoxApply = window.boxApply; window.boxApply = m => { window.__boxMode = m; };");
  const btn = await evaluate(`(()=>{const f=id=>{const r=document.querySelector(id).getBoundingClientRect();
     return [r.x+r.width/2, r.y+r.height/2]};
     return {ex:f('#boxExclude'), del:f('#boxDelete'), cancel:f('#boxCancel')}})()`);
  await click(btn.ex[0], btn.ex[1]);
  await sleep(120);
  out.excludeBtn = await evaluate("window.__boxMode || null");
  out.stillPicked = await evaluate("(S.picked||[]).length");
  await click(btn.del[0], btn.del[1]);
  await sleep(120);
  out.deleteBtn = await evaluate("window.__boxMode || null");
  await click(btn.cancel[0], btn.cancel[1]);
  await sleep(120);
  out.pickedAfterCancel = await evaluate("(S.picked||[]).length");
  await evaluate("window.boxApply = window.__origBoxApply;");
  out.segState = await evaluate("JSON.stringify(S.segments||{})");
  out.excludedRows = await evaluate("(S.sheet.data && S.sheet.data.rows || []).filter(r=>String(r.include)!=='1').length");
  await evaluate("document.querySelector('#boxToggle').click()");
  out.boxModeAfter = await evaluate("!!S.boxMode");

  // ---- 8. 连线画法：一键循环（三档都过一遍，最后回到原档）
  // 不假设初始档位：用户可能把图设成了散点。只看"三档都出现、每档行为对、回到原档"。
  async function snap(){
    return await evaluate(`(()=>{
      const v = Object.values(S.lineVerts||{});
      return {mode: connectNow(),
              label: $('connectToggle').textContent.trim(),
              verts: v, sum: v.reduce((a,b)=>a+b, 0),
              points: (S.points||[]).length,
              spec: (S.spec.style||{}).connect};
    })()`);
  }
  out.modeStart = (await snap()).mode;
  out.steps = [await snap()];
  for (let k = 0; k < 3; k++) {
    const want = await evaluate(
      "({segment:'smooth',smooth:'scatter',scatter:'segment'})[connectNow()]");
    await evaluate("document.querySelector('#connectToggle').click()");
    await waitFor("connectNow() === " + JSON.stringify(want));
    await sleep(900);
    out.steps.push(await snap());
  }
  out.modeEnd = out.steps[out.steps.length - 1].mode;
  out.modesSeen = [...new Set(out.steps.map(x => x.mode))].sort().join(",");
  out.specConnectAfter = out.steps[out.steps.length - 1].spec;

  // ---- 9. 锁定一条曲线再框选：线多时只删这一条的点
  await evaluate("document.querySelector('#boxToggle').click()");
  await waitFor("!!S.boxMode");
  out.aimTarget = await evaluate(`(()=>{const c={};S.points.forEach(p=>c[p.curve]=(c[p.curve]||0)+1);
     const ks=Object.keys(c).sort((a,b)=>c[b]-c[a]); return ks[Math.min(2,ks.length-1)]})()`);
  await evaluate(`setAim(${JSON.stringify(out.aimTarget)})`);
  await sleep(300);
  out.aimDown = await evaluate("$('boxCurve').selectedOptions[0].textContent.trim()");
  out.aimRow = await evaluate("document.querySelectorAll('#curveList .curve.aim').length");
  out.dim = await evaluate(`(()=>{let d=0,t=0;
     document.querySelectorAll('#svgbox [id^="cv"]').forEach(g=>{t++;if(g.style.opacity==='0.14')d++});
     return [d,t]})()`);
  const bigBox = await evaluate(`(()=>{const r=document.querySelector('#stage').getBoundingClientRect();
     return [r.x + r.width*0.08, r.y + r.height*0.08,
             r.x + r.width*0.94, r.y + r.height*0.92]})()`);
  await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: bigBox[0], y: bigBox[1] });
  await send("Input.dispatchMouseEvent", { type: "mousePressed", x: bigBox[0], y: bigBox[1],
                                           button: "left", clickCount: 1 });
  for (let k = 1; k <= 5; k++) {
    await send("Input.dispatchMouseEvent", { type: "mouseMoved", button: "left",
      x: bigBox[0] + (bigBox[2]-bigBox[0])*k/5, y: bigBox[1] + (bigBox[3]-bigBox[1])*k/5 });
    await sleep(50);
  }
  await send("Input.dispatchMouseEvent", { type: "mouseReleased", x: bigBox[2], y: bigBox[3],
                                           button: "left", clickCount: 1 });
  await sleep(350);
  out.aimPicked = await evaluate("(S.picked||[]).length");
  out.aimCurveCount = await evaluate("[...new Set((S.picked||[]).map(i=>S.points[i].curve))].length");
  out.aimPickedAll = await evaluate(`(S.picked||[]).every(i=>S.points[i].curve===${JSON.stringify(out.aimTarget)})`);
  // 同一个框，切回「全部曲线」→ 立刻重算出更多点、更多曲线
  await evaluate(`$('boxCurve').value='-1'; $('boxCurve').dispatchEvent(new Event('change'))`);
  await sleep(350);
  out.allPicked = await evaluate("(S.picked||[]).length");
  out.allCurveCount = await evaluate("[...new Set((S.picked||[]).map(i=>S.points[i].curve))].length");
  out.dropAll = await evaluate("$('boxCurve').selectedOptions[0].textContent.trim()");
  // Esc 三下：清掉框里的点 → 退出框选模式 → 解除曲线锁定
  for (let k = 0; k < 3; k++) {
    await send("Input.dispatchKeyEvent", { type: "rawKeyDown", key: "Escape",
                                           code: "Escape", windowsVirtualKeyCode: 27 });
    await send("Input.dispatchKeyEvent", { type: "keyUp", key: "Escape",
                                           code: "Escape", windowsVirtualKeyCode: 27 });
    await sleep(200);
  }
  out.pickedAfterEsc2 = await evaluate("(S.picked||[]).length");
  out.aimAfterEsc = await evaluate("S.aim === null");
  // 单击曲线上某个点 → 锁定它（不靠下拉）
  const hp = await evaluate(`(()=>{const p=S.points[Math.floor(S.points.length*0.6)];
     const r=document.querySelector('#stage').getBoundingClientRect();
     return [r.x+p.nx*r.width, r.y+p.ny*r.height, p.curve]})()`);
  await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: hp[0], y: hp[1] });
  await send("Input.dispatchMouseEvent", { type: "mousePressed", x: hp[0], y: hp[1],
                                           button: "left", clickCount: 1 });
  await send("Input.dispatchMouseEvent", { type: "mouseReleased", x: hp[0], y: hp[1],
                                           button: "left", clickCount: 1 });
  await sleep(300);
  out.clickTarget = hp[2];
  out.clickAim = await evaluate("S.aim");
  // 收尾：解除锁定、退出框选、把画法还原成进页面时的样子（可能不是 segment）
  await evaluate("setAim(null); boxSet(false); clearBoxSel()");
  // 整份规格原样写回：测试改了画法、锁定、框选状态，用户不该为此收拾
  await evaluate(`(async()=>{ await post('/api/export',
     {figure:S.fid, spec:${out.specOrig}, deliver:false}); })()`);
  await sleep(1200);
  out.connectRestored = await evaluate("connectNow()");
  out.specRestored = await evaluate(
    "(S.spec.style||{}).connect === " + JSON.stringify(out.connectOrig));
  out.finalAim = await evaluate("S.aim === null");
  out.finalBoxMode = await evaluate("!!S.boxMode");
  out.excludedRows2 = await evaluate("(S.sheet.data && S.sheet.data.rows || []).filter(r=>String(r.include)!=='1').length");
  out.errors = errors;
  console.log(JSON.stringify(out, null, 1));

  const bad = [];
  if (out.selAfterClick !== 1) bad.push("单击没有选中 1 行");
  if (out.selAfterShift < 2) bad.push("Shift 连选没生效");
  if (out.selCells < 2) bad.push("选中格没有高亮");
  if (!(out.offsetAfterDrag[1] > 0.5)) bad.push("拖曲线没写进偏移");
  if (!out.moveModeOff) bad.push("移线模式没关掉（会抢后面的单击）");
  if (out.offsetChip < 1) bad.push("曲线列表没显示 Δ 徽标");
  if (out.offsetMax > 1e-9) bad.push("归零没生效（仍有偏移 " + out.offsetMax + "）");
  if (out.hasReq) bad.push("需求单还在");
  if (!out.boxMode) bad.push("框选模式按钮没生效");
  if (!out.marqueeSeen) bad.push("拉框时没有出现选框");
  if (!(out.picked > 0)) bad.push("框选没选中任何点");
  if (out.pickedDots !== out.picked) bad.push("选中点没有高亮");
  if (!out.barShown) bad.push("框选后没出现操作条");
  if (out.pickedAfterEsc !== 0) bad.push("Esc 没有清空框选");
  if (out.excludedRows !== out.excludedBase)
    bad.push("冒烟测试动了真实数据（被排除行 " + out.excludedBase + " → " + out.excludedRows + "）");
  if (!(out.pickedAgain > 0)) bad.push("第二次拉框没选中点");
  if (out.excludeBtn !== "exclude") bad.push("「不画」按钮没接到动作（框选模式下按钮被当成拉框）");
  if (out.deleteBtn !== "delete") bad.push("「删行」按钮没接到动作");
  if (out.pickedAfterCancel !== 0) bad.push("取消按钮没清空选择");
  if (out.boxModeAfter) bad.push("框选模式没有退出");
  if (out.fastMs > 400) bad.push("快渲染超过 400 ms（实际 " + out.fastMs + "）");
  if (!out.specRestored) bad.push("收尾没把规格还原成进页面时那份");
  if (out.modesSeen !== "scatter,segment,smooth") bad.push("三档没走全：" + out.modesSeen);
  if (out.modeEnd !== out.modeStart) bad.push("点三下没回到原档：" + out.modeStart +
    " → " + out.modeEnd);
  const byMode = {};
  out.steps.forEach(x => { byMode[x.mode] = x; });
  const CNAME = {scatter: "散点", segment: "折线", smooth: "平滑"};
  Object.keys(CNAME).forEach(m => {
    if (!byMode[m]) { bad.push("没经过 " + m + " 档"); return; }
    if (!byMode[m].label.includes(CNAME[m]))
      bad.push("按钮文案没跟着变：" + byMode[m].mode + " → " + byMode[m].label);
    if (byMode[m].spec !== m) bad.push("规格没跟着落盘：" + m + " → " + byMode[m].spec);
  });
  if (out.steps.some(x => x.points !== out.steps[0].points))
    bad.push("切换画法改动了数据点数：" + out.steps.map(x => x.points).join(","));
  if (byMode.scatter && byMode.scatter.sum !== 0)
    bad.push("散点模式下还在画线：" + JSON.stringify(byMode.scatter.verts));
  if (byMode.smooth && byMode.segment && !(byMode.smooth.sum > byMode.segment.sum * 2))
    bad.push("平滑没有加密曲线：" + byMode.smooth.sum + " vs " + byMode.segment.sum);
  if (!out.aimDown.includes("·")) bad.push("下拉没显示锁定曲线：" + out.aimDown);
  if (out.aimRow !== 1) bad.push("曲线列表没高亮锁定的那条（" + out.aimRow + " 行）");
  if (!(out.dim[0] > 0)) bad.push("锁定后其他曲线没有淡出（" + JSON.stringify(out.dim) + "）");
  if (!(out.aimPicked > 0)) bad.push("锁定后拉框一个点都没选中");
  if (out.aimCurveCount !== 1 || !out.aimPickedAll) bad.push("锁定后仍框到了别的曲线");
  if (!(out.allPicked > out.aimPicked)) bad.push("切回「全部曲线」没有重算出更多点（" +
    out.allPicked + " vs " + out.aimPicked + "）");
  if (!(out.allCurveCount > 1)) bad.push("切回「全部曲线」仍然只有一条线被选中");
  if (out.dropAll !== "全部曲线") bad.push("下拉没回到「全部曲线」");
  if (out.pickedAfterEsc2 !== 0) bad.push("Esc 没清空框选");
  if (!out.aimAfterEsc) bad.push("Esc 没解除曲线锁定");
  if (out.clickAim !== out.clickTarget) bad.push("单击曲线没锁定它（点了 " + out.clickTarget +
    "，锁成 " + out.clickAim + "）");
  if (!out.finalAim) bad.push("收尾没解除锁定");
  if (out.finalBoxMode) bad.push("收尾没退出框选模式");
  if (out.excludedRows2 !== out.excludedBase)
    bad.push("这轮操作动了真实数据（被排除行 " + out.excludedBase + " → " + out.excludedRows2 + "）");
  if (out.errors.length) bad.push("控制台有报错：" + out.errors.join(" | "));
  console.log(bad.length ? "❌ " + bad.join("；") : "✅ 交互冒烟全部通过");
  return bad.length ? 1 : 0;
}

main().then(code => {
  try { ws && ws.close(); } catch {}
  edge.kill();
  setTimeout(() => { try { rmSync(profile, { recursive: true, force: true }); } catch {} process.exit(code); }, 300);
}).catch(e => { console.error("测试崩溃：", e); edge.kill(); process.exit(2); });
