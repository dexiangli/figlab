"use strict";

const $ = id => document.getElementById(id);
const figure = new URLSearchParams(location.search).get("id");
let figureTitle = figure;
const NS = "http://www.w3.org/2000/svg";
const coordinates = ["x", "y", "w", "h"];
let layout = {page:[18, 12], panels:[]};
let selected, draft, controller, drag, dirty = false;
let available = false;
const images = new Map();
const panelList = () => draft || layout.panels;
const status = message => { $("status").textContent = message; };
const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
const round = value => Math.round(value * 100) / 100;
const markChanged = () => { dirty = true; status("布局已修改 · 点击「保存组图」保留"); };
window.hasUnsavedLayout = () => dirty;
window.addEventListener("beforeunload", event => {
  if (dirty) { event.preventDefault(); event.returnValue = ""; }
});

async function json(url, body) {
  const response = await fetch(url, body === undefined ? {} : {
    method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)
  });
  const data = await response.json();
  if (!response.ok || data.error) throw new Error(data.error || "操作失败");
  return data;
}

function box(panel, change = panel) {
  const values = coordinates.map(key => Number(change[key] ?? panel[key]));
  if (!values.every(Number.isFinite)) throw new Error("面板坐标无效");
  const [x, y, w, h] = values;
  const width = round(clamp(w, 5, 100)), height = round(clamp(h, 5, 100));
  Object.assign(panel, {x:round(clamp(x, 0, 100 - width)),
    y:round(clamp(y, 0, 100 - height)), w:width, h:height});
}

function place(element, panel) {
  for (const [index, style] of ["left", "top", "width", "height"].entries()) {
    element.style[style] = panel[coordinates[index]] + "%";
  }
}

function draw() {
  const canvas = $("canvas");
  canvas.style.aspectRatio = `${layout.page[0]} / ${layout.page[1]}`;
  canvas.style.width = `min(100%, ${layout.page[0] / layout.page[1] * 66}vh)`;
  canvas.querySelectorAll(".panel").forEach(element => element.remove());
  $("empty").hidden = !!panelList().length;
  panelList().forEach((panel, index) => {
    const element = document.createElement("div");
    element.className = "panel" + (panel.id === selected ? " selected" : "");
    element.title = panel.title;
    place(element, panel);
    const source = panel.photo || images.get(panel.figure)?.url;
    if (source) {
      const image = document.createElement("img");
      image.src = source;
      image.alt = panel.title;
      element.append(image);
    } else {
      element.textContent = panel.figure ? "正在读取项目图…" : "待放入图件";
    }
    const label = document.createElement("span");
    label.className = "letter";
    label.textContent = String.fromCharCode(65 + index);
    element.append(label);
    const handle = document.createElement("span");
    handle.className = "handle";
    if (!draft) element.append(handle);
    element.onpointerdown = event => startDrag(event, panel, element, event.target === handle);
    element.ondblclick = () => { if (panel.figure && !draft) parent.loadFigure(panel.figure); };
    canvas.append(element);
  });
  syncFields();
}

function syncFields() {
  const source = $("figures").selectedOptions[0]?.textContent || "";
  $("sourceTitle").textContent = source;
  $("sourceTitle").hidden = !source;
  $("figures").title = source;
  for (const [index, id] of ["width", "height"].entries()) {
    $(id).value = layout.page[index];
    $(id).disabled = !!draft;
  }
  const panel = panelList().find(item => item.id === selected);
  $("panelSettings").hidden = !panel;
  if (panel) {
    const index = panelList().indexOf(panel);
    $("panelTitle").textContent = `${String.fromCharCode(65 + index)} · ${panel.title}`;
    coordinates.forEach(key => { $(key).value = panel[key]; $(key).disabled = !!draft; });
  }
  for (const id of ["addPhoto", "placeholder", "grid", "remove", "save", "export", "print"]) {
    $(id).disabled = !!draft;
  }
  $("addFigure").disabled = $("replace").disabled = !!draft || !$("figures").value;
  const copied = parent.figuresToPaste?.().length || 0;
  $("pasteFigures").disabled = !!draft || !copied || layout.panels.length >= 26;
  $("pasteFigures").textContent = copied ? `粘贴图片（${copied}）` : "粘贴图片";
  $("ask").disabled = !!draft || !available || !layout.panels.length;
  $("discard").hidden = !draft;
  $("apply").hidden = !draft || !!controller;
}

function startDrag(event, panel, element, resize) {
  if (draft || event.button !== 0) return;
  event.preventDefault();
  selected = panel.id;
  document.querySelector(".panel.selected")?.classList.remove("selected");
  element.classList.add("selected");
  syncFields();
  element.setPointerCapture(event.pointerId);
  const bounds = $("canvas").getBoundingClientRect();
  const original = {...panel};
  drag = true;
  element.onpointermove = motion => {
    const dx = (motion.clientX - event.clientX) * 100 / bounds.width;
    const dy = (motion.clientY - event.clientY) * 100 / bounds.height;
    box(panel, resize ? {w:clamp(original.w + dx, 5, 100 - original.x),
                         h:clamp(original.h + dy, 5, 100 - original.y)} :
                         {x:original.x + dx, y:original.y + dy});
    place(element, panel);
    syncFields();
  };
  element.onlostpointercapture = () => {
    element.onpointermove = null;
    drag = false;
    if (coordinates.some(key => panel[key] !== original[key])) markChanged();
  };
}

async function refreshImages(force = false) {
  const ids = [...new Set(panelList().map(panel => panel.figure).filter(Boolean))];
  let changed = false;
  for (const id of ids) {
    try {
      const query = "?id=" + encodeURIComponent(id);
      const {revision} = await json("/api/board/revision" + query);
      const previous = images.get(id);
      if (!force && previous?.revision === revision) continue;
      const response = await fetch("/api/board/preview" + query);
      if (!response.ok) throw new Error("无法预览项目图");
      const svg = await response.text();
      const url = URL.createObjectURL(new Blob([svg], {type:"image/svg+xml"}));
      if (previous) URL.revokeObjectURL(previous.url);
      images.set(id, {revision, svg, url});
      changed = true;
    } catch (error) {
      const previous = images.get(id);
      if (previous) { URL.revokeObjectURL(previous.url); images.delete(id); changed = true; }
      status(`${id} · ${error.message}`);
    }
  }
  if (changed && !drag) draw();
}

function arrangePanels() {
  const n = layout.panels.length;
  if (!n) return;
  const columns = Math.ceil(Math.sqrt(n)), rows = Math.ceil(n / columns);
  layout.panels.forEach((panel, index) => box(panel, {
    x:(index % columns)*100/columns+2, y:Math.floor(index/columns)*100/rows+2,
    w:100/columns-4, h:100/rows-4}));
}

function addPanels(contents) {
  if (draft || !contents.length) return false;
  if (layout.panels.length + contents.length > 26) {
    status("每张组图最多 26 个面板，请移除部分面板或新建组图");
    return false;
  }
  const empty = layout.panels.length === 0;
  for (const content of contents) {
    const index = layout.panels.length;
    const panel = {id:crypto.randomUUID(), x:2 + 48*(index % 2), y:2 + 48*(Math.floor(index / 2) % 2),
      w:46, h:46, ...content};
    layout.panels.push(panel);
    selected = panel.id;
  }
  if (empty && contents.length > 1) arrangePanels();
  markChanged();
  draw();
  refreshImages();
  return true;
}

function pasteFigures() {
  const copied = parent.figuresToPaste?.() || [];
  const availableIds = new Set([...$("figures").options].map(option => option.value));
  const sources = copied.filter(item => availableIds.has(item.figure));
  if (sources.length !== copied.length) {
    parent.finishFigurePaste(copied.filter(item => !availableIds.has(item.figure)).map(item => item.figure));
    syncFields();
  }
  if (!addPanels(sources)) return false;
  parent.finishFigurePaste(sources.map(item => item.figure));
  syncFields();
  status(`已粘贴 ${sources.length} 张图 · 保存组图可保留布局`);
  return true;
}

function chosenFigure() {
  const option = $("figures").selectedOptions[0];
  return {figure:option.value, title:option.textContent};
}

function svgNode(name, attrs) {
  const node = document.createElementNS(NS, name);
  Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
  return node;
}

function combinedSvg() {
  const [w, h] = layout.page.map(value => value * 72 / 2.54);
  const root = svgNode("svg", {width:`${layout.page[0]}cm`, height:`${layout.page[1]}cm`, viewBox:`0 0 ${w} ${h}`});
  root.append(svgNode("rect", {width:w, height:h, fill:"white"}));
  layout.panels.forEach((panel, index) => {
    const x = panel.x * w / 100, y = panel.y * h / 100;
    const size = {x, y, width:panel.w*w/100, height:panel.h*h/100};
    if (panel.figure) {
      const source = images.get(panel.figure)?.svg;
      if (!source) throw new Error(`无法导出：${panel.title} 的预览尚未载入`);
      const child = new DOMParser().parseFromString(source, "image/svg+xml").documentElement;
      const prefix = `panel${index}-`;
      const ids = new Set(Array.from(child.querySelectorAll("[id]"), node => node.id));
      child.querySelectorAll("*").forEach(node => {
        if (node.id) node.id = prefix + node.id;
        for (const attr of Array.from(node.attributes)) {
          const value = attr.value.replace(/url\(#([^)]*)\)/g, (_, id) => `url(#${prefix}${id})`);
          if (value !== attr.value) attr.value = value;
          else if (attr.localName === "href" && value.startsWith("#") && ids.has(value.slice(1))) {
            attr.value = `#${prefix}${value.slice(1)}`;
          }
        }
      });
      Object.entries(size).forEach(([key, value]) => child.setAttribute(key, value));
      root.append(child);
    } else if (panel.photo) {
      root.append(svgNode("image", {...size, href:panel.photo, preserveAspectRatio:"xMidYMid meet"}));
    } else {
      throw new Error("请先填入或移除占位面板，再导出");
    }
    const label = svgNode("text", {x:x+size.width*.02, y:y+12, "font-size":12,
      "font-weight":"bold", "font-family":"Arial,sans-serif"});
    label.textContent = String.fromCharCode(65 + index);
    root.append(label);
  });
  return root;
}

async function exportBoard(print) {
  if (!layout.panels.length) return status("请先添加面板");
  await refreshImages();
  try {
    const svg = combinedSvg();
    if (print) {
      $("printpage").replaceChildren(svg);
      const css = document.createElement("style");
      css.textContent = `@page {size: ${layout.page[0]}cm ${layout.page[1]}cm; margin:0}`;
      document.head.append(css);
      window.print();
      css.remove();
      return;
    }
    const blob = new Blob([new XMLSerializer().serializeToString(svg)], {type:"image/svg+xml"});
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${figureTitle.replace(/[\\/:*?"<>|]/g, "-")}.svg`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    status(`已导出 ${layout.panels.length} 个面板 · ${layout.page.join(" × ")} cm`);
  } catch (error) { status(error.message); }
}

function log(message) {
  const item = document.createElement("li");
  item.textContent = String(message).slice(0, 300);
  $("log").hidden = false;
  $("log").append(item);
  $("log").scrollTop = $("log").scrollHeight;
}

async function ask() {
  const prompt = $("prompt").value.trim();
  if (!prompt || draft) return;
  const run = new AbortController();
  controller = run;
  draft = structuredClone(layout.panels);
  $("log").replaceChildren();
  log("已提交布局要求，收到操作后将逐步更新画布。");
  draw();
  let complete = false;
  try {
    const response = await fetch("/api/board/ai", {method:"POST", signal:run.signal,
      headers:{"Content-Type":"application/json"}, body:JSON.stringify({prompt, page:layout.page,
        panels:draft.map(({id,title,x,y,w,h}, index) => ({id,title:`${String.fromCharCode(65+index)} · ${title}`,x,y,w,h}))})});
    if (!response.ok) throw new Error("无法连接 AI 布局助手");
    const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
    let pending = "";
    try {
      while (controller === run) {
        const {value, done} = await reader.read();
        if (done || controller !== run) break;
        pending += value;
        const lines = pending.split("\n");
        pending = lines.pop();
        for (const line of lines.filter(Boolean)) {
          const action = JSON.parse(line);
          if (action.error) throw new Error(action.error);
          if (action.done) { complete = true; continue; }
          if (action.id) {
            const panel = draft.find(item => item.id === action.id);
            if (!panel || !coordinates.every(key => Number.isFinite(action[key]))) continue;
            box(panel, action);
            selected = panel.id;
            draw();
          }
          if (action.message) log(action.message);
        }
        // Give the browser a paint opportunity between arriving steps.
        await new Promise(resolve => setTimeout(resolve, 0));
      }
    } finally { await reader.cancel(); }
    if (controller === run && !complete) throw new Error("布局更新提前中断");
  } catch (error) {
    if (controller === run) { log(error.message); draft = null; }
  } finally {
    if (controller === run) {
      controller = null;
      if (complete) log("布局预览完成，可以应用或取消。");
      draw();
    }
  }
}

async function loadFigures() {
  const select = $("figures");
  const keep = select.value;
  const {figures} = await json("/api/project");
  figureTitle = figures.find(item => item.id === figure)?.title || figure;
  $("boardName").textContent = figureTitle;
  select.replaceChildren(...figures.filter(item => item.exists && item.preset !== "board")
    .map(item => new Option(item.title || item.id, item.id)));
  if ([...select.options].some(option => option.value === keep)) select.value = keep;
  syncFields();
}

async function start() {
  const [saved, settings] = await Promise.all([json("/api/board?id=" + encodeURIComponent(figure)), json("/api/board/settings")]);
  layout = saved;
  available = settings.ai;
  $("boardName").textContent = figure;
  $("aiNote").textContent = available ? "布局要求、面板标题和位置会发送给 AI；图片留在本机。" : "AI 尚未配置，仍可手动排版。";
  $("prompt").disabled = !available;
  const toggleProperties = $("toggleProperties");
  toggleProperties.onclick = () => {
    const hidden = $("boardProperties").toggleAttribute("hidden");
    document.querySelector("main").classList.toggle("collapsed", hidden);
    toggleProperties.textContent = hidden ? "‹" : "›";
    toggleProperties.title = hidden ? "展开组图属性栏" : "收起组图属性栏";
    toggleProperties.setAttribute("aria-expanded", String(!hidden));
  };
  for (const [index, id] of ["width", "height"].entries()) $(id).onchange = () => {
    layout.page[index] = clamp(Number($(id).value), 3, 60);
    markChanged(); draw();
  };
  for (const [index, key] of coordinates.entries()) {
    const label = document.createElement("label");
    label.textContent = ["距左（%）", "距上（%）", "宽（%）", "高（%）"][index];
    const input = document.createElement("input");
    Object.assign(input, {id:key, type:"number", step:"0.1", min:0, max:100});
    input.onchange = () => {
      const panel = layout.panels.find(item => item.id === selected);
      if (!panel || draft) return;
      box(panel, {[key]:input.value}); markChanged(); draw();
    };
    label.append(input);
    $("geometry").append(label);
  }
  $("figures").onchange = syncFields;
  $("addFigure").onclick = () => addPanels([chosenFigure()]);
  $("pasteFigures").onclick = pasteFigures;
  $("placeholder").onclick = () => addPanels([{title:"占位面板"}]);
  window.addEventListener("keydown", event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "v" &&
        !event.target.matches("input, textarea, [contenteditable]")) {
      if (pasteFigures()) event.preventDefault();
    }
  });
  $("addPhoto").onclick = () => $("photo").click();
  $("photo").onchange = () => {
    const file = $("photo").files[0];
    $("photo").value = "";
    if (!file) return;
    if (!/^image\/(png|jpeg|webp)$/.test(file.type) || file.size > 8*1024*1024) {
      return status("请选择 8 MB 以内的 PNG、JPEG 或 WebP 图片");
    }
    const reader = new FileReader();
    reader.onload = () => addPanels([{photo:reader.result, title:file.name}]);
    reader.onerror = () => status("照片读取失败");
    reader.readAsDataURL(file);
  };
  $("replace").onclick = () => {
    const panel = layout.panels.find(item => item.id === selected);
    delete panel.photo;
    Object.assign(panel, chosenFigure());
    markChanged(); draw(); refreshImages();
  };
  $("remove").onclick = () => {
    layout.panels = layout.panels.filter(item => item.id !== selected);
    selected = null;
    markChanged(); draw();
  };
  $("grid").onclick = () => {
    if (!layout.panels.length) return;
    arrangePanels();
    markChanged(); draw();
  };
  $("save").onclick = async () => {
    const snapshot = JSON.stringify(layout);
    $("save").disabled = true;
    try {
      await json("/api/board/save", {id:figure, layout:JSON.parse(snapshot)});
      if (JSON.stringify(layout) === snapshot) { dirty = false; status("已保存到项目"); }
    } catch (error) { status(error.message); }
    finally { syncFields(); }
  };
  $("export").onclick = () => exportBoard(false);
  $("print").onclick = () => exportBoard(true);
  $("ask").onclick = ask;
  $("apply").onclick = () => { layout.panels = draft; draft = null; markChanged(); draw(); };
  $("discard").onclick = () => {
    controller?.abort(); controller = null; draft = null;
    log("已取消预览。"); draw();
  };
  $("refresh").onclick = () => {
    loadFigures().catch(error => status(error.message));
    refreshImages(true);
  };
  window.refreshBoard = () => { loadFigures().catch(error => status(error.message)); refreshImages(); };
  draw();
  await loadFigures();
  await refreshImages();
  async function poll() {
    if (!document.hidden && !drag) await refreshImages();
    setTimeout(poll, 1800);
  }
  setTimeout(poll, 1800);
}

start().catch(error => status(error.message));
