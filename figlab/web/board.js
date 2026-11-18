"use strict";

const $ = id => document.getElementById(id);
const figure = new URLSearchParams(location.search).get("id");
let figureTitle = figure;
const NS = "http://www.w3.org/2000/svg";
const coordinates = ["x", "y", "w", "h"];
const defaultGrid = {preset:"auto", custom:"", gapX:2, gapY:2};
const gridFields = ["gridPreset", "customGrid", "gridGapX", "gridGapY"];
const edgeMarginMm = 0.5;
const labelSizePt = 8;
const pagePoints = () => layout.page.map(cm => cm * 72 / 2.54);
const panelLetter = index => String.fromCharCode(97 + index);
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
  const [pageWidth, pageHeight] = pagePoints();
  const width = panel.w * pageWidth / 100, height = panel.h * pageHeight / 100;
  const frame = panelFrame(width, height, images.get(panel.figure)?.aspect);
  const image = element.querySelector("img");
  if (image) Object.assign(image.style, {
    left:`${100 * frame.x / width}%`, top:`${100 * frame.y / height}%`,
    width:`${100 * frame.width / width}%`, height:`${100 * frame.height / height}%`,
  });
  const label = element.querySelector(".letter");
  if (label) Object.assign(label.style, {
    left:`${100 * frame.x / width}%`,
    top:`${100 * (frame.y - frame.band) / height}%`,
    fontSize:`${100 * frame.labelSize / pageWidth}cqw`,
  });
}

function panelFrame(width, height, aspect) {
  const labelSize = Math.min(labelSizePt, height / 3);
  const band = labelSize * 1.4;
  const innerHeight = height - band;
  const fittedWidth = aspect ? Math.min(width, innerHeight * aspect) : width;
  const fittedHeight = aspect ? fittedWidth / aspect : innerHeight;
  return {x:(width-fittedWidth)/2, y:band+(innerHeight-fittedHeight)/2,
    width:fittedWidth, height:fittedHeight, band, labelSize};
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
    label.textContent = panelLetter(index);
    element.append(label);
    const handle = document.createElement("span");
    handle.className = "handle";
    if (!draft) element.append(handle);
    element.onpointerdown = event => startDrag(event, panel, element, event.target === handle);
    element.ondblclick = () => { if (panel.figure && !draft) parent.loadFigure(panel.figure); };
    place(element, panel);
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
    $("panelTitle").textContent = `${panelLetter(index)} · ${panel.title}`;
    coordinates.forEach(key => { $(key).value = panel[key]; $(key).disabled = !!draft; });
  }
  for (const id of ["addPhoto", "placeholder", "grid", "remove", "save", "export", "print"]) {
    $(id).disabled = !!draft;
  }
  gridFields.forEach(id => { $(id).disabled = !!draft; });
  $("trimExport").disabled = !!draft;
  $("boardNote").disabled = !!draft;
  const notes = panelList().flatMap((panel, index) => {
    const items = images.get(panel.figure)?.notes || [];
    return items.map(note => {
      const li = document.createElement("li");
      li.textContent = `${panelLetter(index)} · ${note}`;
      return li;
    });
  });
  $("panelNotes").replaceChildren(...notes);
  $("panelNotes").hidden = !notes.length;
  $("grid").disabled = !!draft || !layout.panels.length;
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
      const {revision, notes} = await json("/api/board/revision" + query);
      const previous = images.get(id);
      if (!force && previous?.revision === revision) continue;
      const response = await fetch("/api/board/preview" + query);
      if (!response.ok) throw new Error("无法预览项目图");
      const {svg, aspect} = trimProjectSvg(await response.text());
      const url = URL.createObjectURL(new Blob([svg], {type:"image/svg+xml"}));
      if (previous) URL.revokeObjectURL(previous.url);
      images.set(id, {revision, svg, url, aspect, notes});
      changed = true;
    } catch (error) {
      const previous = images.get(id);
      if (previous) { URL.revokeObjectURL(previous.url); images.delete(id); changed = true; }
      status(`${id} · ${error.message}`);
    }
  }
  if (changed && !drag) draw();
}

function trimProjectSvg(source) {
  const root = new DOMParser().parseFromString(source, "image/svg+xml").documentElement;
  const original = root.viewBox?.baseVal;
  if (!original?.width || !original.height) return {svg:source};
  const aspect = original.width / original.height;
  const figure = root.querySelector('[id="figure_1"]');
  const backdrop = figure?.querySelector(':scope > [id="patch_1"]');
  if (!backdrop) return {svg:source, aspect};

  const measure = document.createElement("div");
  measure.style.cssText = "position:fixed;left:-10000px;top:0;visibility:hidden;pointer-events:none";
  measure.setAttribute("aria-hidden", "true");
  measure.append(root);
  document.body.append(measure);
  try {
    let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity;
    const inverse = root.getCTM().inverse();
    for (const node of figure.querySelectorAll("path, rect, line, polyline, polygon, text, use, image, circle, ellipse")) {
      if (backdrop.contains(node) || node.closest("defs, [clip-path]")) continue;
      const bounds = node.getBBox();
      if (!bounds.width && !bounds.height) continue;
      const matrix = inverse.multiply(node.getCTM());
      for (const x of [bounds.x, bounds.x+bounds.width]) {
        for (const y of [bounds.y, bounds.y+bounds.height]) {
          const point = new DOMPoint(x, y).matrixTransform(matrix);
          left = Math.min(left, point.x); right = Math.max(right, point.x);
          top = Math.min(top, point.y); bottom = Math.max(bottom, point.y);
        }
      }
    }
    if (!Number.isFinite(left) || right <= left || bottom <= top) return {svg:source, aspect};
    const padding = 2;
    left = Math.max(original.x, left-padding);
    top = Math.max(original.y, top-padding);
    right = Math.min(original.x+original.width, right+padding);
    bottom = Math.min(original.y+original.height, bottom+padding);
    const width = right-left, height = bottom-top;
    if (width <= 0 || height <= 0) return {svg:source, aspect};
    root.setAttribute("viewBox", `${left} ${top} ${width} ${height}`);
    root.setAttribute("width", `${width}pt`);
    root.setAttribute("height", `${height}pt`);
    return {svg:new XMLSerializer().serializeToString(root), aspect:width/height};
  } catch {
    return {svg:source, aspect};
  } finally {
    measure.remove();
  }
}

function gridPositions(page, count, settings) {
  const {preset, custom, gapX, gapY} = settings;
  const autoColumns = Math.ceil(Math.sqrt(count));
  const format = preset === "custom" ? custom : preset;
  const [columns, rows] = preset === "auto"
    ? [autoColumns, Math.ceil(count / autoColumns)]
    : format.split("x").map(Number);
  if (count > columns * rows) throw new Error(`当前有 ${count} 个面板，请选择容量更大的网格或自动排版。`);

  const [width, height] = page.map(cm => cm * 10);
  const margin = edgeMarginMm;
  const cellWidth = (width - 2 * margin - (columns - 1) * gapX) / columns;
  const cellHeight = (height - 2 * margin - (rows - 1) * gapY) / rows;
  if (cellWidth < .05 * width || cellHeight < .05 * height) {
    throw new Error("间距过大。请减小间距，或增大画布。");
  }
  return Array.from({length:count}, (_, index) => ({
    x: round((margin + index % columns * (cellWidth + gapX)) / width * 100),
    y: round((margin + Math.floor(index / columns) * (cellHeight + gapY)) / height * 100),
    w: Math.floor(cellWidth / width * 10000 + 1e-9) / 100,
    h: Math.floor(cellHeight / height * 10000 + 1e-9) / 100,
  }));
}

function arrangePanels(settings) {
  const positions = gridPositions(layout.page, layout.panels.length, settings);
  layout.panels.forEach((panel, index) => box(panel, positions[index]));
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
  if (empty && contents.length > 1) arrangePanels(defaultGrid);
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
  const [w, h] = pagePoints();
  const boxes = layout.panels.map(panel => {
    const frame = panelFrame(panel.w*w/100, panel.h*h/100, images.get(panel.figure)?.aspect);
    return {...frame, x:panel.x*w/100+frame.x, y:panel.y*h/100+frame.y};
  });
  const padding = edgeMarginMm * 72 / 25.4;
  const crop = layout.trimExport !== false;
  const left = crop ? Math.max(0, Math.min(...boxes.map(box => box.x)) - padding) : 0;
  const top = crop ? Math.max(0, Math.min(...boxes.map(box => box.y-box.band)) - padding) : 0;
  const right = crop ? Math.min(w, Math.max(...boxes.map(box => box.x+box.width)) + padding) : w;
  const bottom = crop ? Math.min(h, Math.max(...boxes.map(box => box.y+box.height)) + padding) : h;
  const width = right-left, height = bottom-top;
  const cm = value => (value * 2.54 / 72).toFixed(3);
  const root = svgNode("svg", {width:`${cm(width)}cm`, height:`${cm(height)}cm`,
    viewBox:`${left} ${top} ${width} ${height}`});
  root.append(svgNode("rect", {x:left, y:top, width, height, fill:"white"}));
  layout.panels.forEach((panel, index) => {
    const {band, labelSize, ...size} = boxes[index];
    const {x, y} = size;
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
    const label = svgNode("text", {x, y:y-band+labelSize, "font-size":labelSize,
      "font-weight":"bold", "font-family":"Arial,sans-serif"});
    label.textContent = panelLetter(index);
    root.append(label);
  });
  return root;
}

async function exportBoard(print) {
  if (!layout.panels.length) return status("请先添加面板");
  await refreshImages();
  try {
    const svg = combinedSvg();
    const width = svg.getAttribute("width"), height = svg.getAttribute("height");
    if (print) {
      $("printpage").replaceChildren(svg);
      const css = document.createElement("style");
      css.textContent = `@page {size: ${width} ${height}; margin:0}`;
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
    status(`已导出 ${layout.panels.length} 个面板 · ${width} × ${height}`);
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
  $("boardNote").value = layout.note || "";
  $("boardNote").oninput = () => {
    layout.note = $("boardNote").value;
    markChanged();
  };
  const grid = {...defaultGrid, ...layout.grid};
  $("gridPreset").value = grid.preset;
  $("customGrid").value = grid.custom;
  const showCustom = () => { $("customGridField").hidden = $("gridPreset").value !== "custom"; };
  $("gridPreset").onchange = showCustom;
  showCustom();
  $("gridGapX").value = grid.gapX;
  $("gridGapY").value = grid.gapY;
  $("trimExport").checked = layout.trimExport !== false;
  $("trimExport").onchange = () => {
    layout.trimExport = $("trimExport").checked;
    markChanged();
  };
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
    const [gapX, gapY] = ["gridGapX", "gridGapY"].map(id => $(id).valueAsNumber);
    if (![gapX, gapY].every(gap => Number.isFinite(gap) && gap >= 0)) {
      status("请输入大于或等于 0 的横向和纵向间距。");
      return;
    }
    const preset = $("gridPreset").value;
    const input = $("customGrid").value.trim();
    const size = /^(\d+)\s*[x×*]\s*(\d+)$/i.exec(input);
    if (preset === "custom" && (!size || size.slice(1).some(value => Number(value) < 1 || Number(value) > 26))) {
      status("请输入列 × 行，例如 1*3 或 4×2。列数和行数须为 1–26 的整数。");
      return;
    }
    const settings = {preset, custom:preset === "custom" ? `${Number(size[1])}x${Number(size[2])}` : input, gapX, gapY};
    try {
      arrangePanels(settings);
      layout.grid = settings;
      markChanged(); draw();
    } catch (error) {
      status(error.message);
    }
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
