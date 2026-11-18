"use strict";

const $ = id => document.getElementById(id);
const figure = new URLSearchParams(location.search).get("id");
let figureTitle = figure;
const NS = "http://www.w3.org/2000/svg";
const coordinates = ["x", "y", "w", "h"];
const defaultGrid = {preset:"auto", custom:"", gapX:2, gapY:2};
const gridFields = ["gridPreset", "customGrid", "gridGapX", "gridGapY"];
const edgeMarginMm = 0.5;
const labelSizePt = 12;
const pagePoints = () => layout.page.map(cm => cm * 72 / 2.54);
const panelLetter = index => String.fromCharCode(97 + index);
let layout = {page:[18, 12], panels:[]};
let selected, draft, controller, drag, dirty = false;
let available = false;
const images = new Map();
const photos = new Map();
const imageKey = panel => JSON.stringify([panel.figure, !!panel.hideLegend]);
const panelImage = panel => images.get(imageKey(panel));
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
  const frame = chartFrame(panel, width, height);
  const image = element.querySelector("img");
  if (image) Object.assign(image.style, {
    left:`${100 * frame.x / width}%`, top:`${100 * frame.y / height}%`,
    width:`${100 * frame.width / width}%`, height:`${100 * frame.height / height}%`,
  });
  const label = element.querySelector(".letter");
  if (label) {
    const mark = panelLabelPosition(frame, panel);
    Object.assign(label.style, {
      left:`${100 * mark.x / width}%`, top:`${100 * mark.y / height}%`,
      fontSize:`${100 * frame.labelSize / pageWidth}cqw`,
    });
  }
}

function panelLabelPosition(frame, panel) {
  if (layout.uniformPanels && panel.figure) {
    // Align the marker just above the top tick and to the left of the axis.
    return {x:frame.x+Math.max(0, .24*frame.width-2.27*frame.labelSize), y:frame.y};
  }
  return {x:frame.x-frame.gutter, y:frame.y};
}

function panelAspect(panel) {
  if (panel.figure && layout.uniformPanels) return 89/55;
  const photo = photos.get(panel.id);
  if (photo && photo.source === panel.photo) {
    return photo.width / (layout.trimPhotos === false ? photo.height : photo.cropHeight);
  }
  return panelImage(panel)?.aspect;
}

function panelFrame(width, height, aspect) {
  const labelSize = Math.min(labelSizePt, width / 4, height / 3);
  const gutter = labelSize * 1.15;
  const innerWidth = width - gutter;
  const fittedWidth = aspect ? Math.min(innerWidth, height * aspect) : innerWidth;
  const fittedHeight = aspect ? fittedWidth / aspect : height;
  return {x:gutter+(innerWidth-fittedWidth)/2, y:(height-fittedHeight)/2,
    width:fittedWidth, height:fittedHeight, gutter, labelSize};
}

function uniformPanelWidth() {
  if (!layout.uniformPanels) return null;
  const [w, h] = pagePoints();
  const widths = panelList().filter(panel => panel.figure)
    .map(panel => Math.min(panel.w*w, panel.h*h*89/55)/100);
  return widths.length ? Math.min(...widths) : null;
}

function chartFrame(panel, width, height) {
  const uniform = layout.uniformPanels && panel.figure;
  if (uniform) {
    const fittedWidth = uniformPanelWidth();
    const fittedHeight = fittedWidth*55/89;
    return {x:(width-fittedWidth)/2, y:(height-fittedHeight)/2, width:fittedWidth,
      height:fittedHeight, gutter:0, labelSize:Math.min(labelSizePt, fittedWidth/4, fittedHeight/3)};
  }
  return panelFrame(width, height, panelAspect(panel));
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
    const photo = photos.get(panel.id);
    const source = (layout.trimPhotos !== false && photo?.source === panel.photo && photo?.url) ||
      panel.photo || panelImage(panel)?.url;
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
    $("panelLegendField").hidden = !panel.figure;
    $("hidePanelLegend").checked = !!panel.hideLegend;
    $("hidePanelLegend").disabled = !!draft;
  }
  for (const id of ["addPhoto", "placeholder", "grid", "remove", "save", "export", "print"]) {
    $(id).disabled = !!draft;
  }
  gridFields.forEach(id => { $(id).disabled = !!draft; });
  $("trimExport").disabled = !!draft;
  $("exportMargin").disabled = !!draft || layout.trimExport === false;
  $("trimPhotos").disabled = !!draft;
  $("uniformPanels").disabled = !!draft;
  $("boardNote").disabled = !!draft;
  const notes = panelList().flatMap((panel, index) => {
    const items = panelImage(panel)?.notes || [];
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
  const projectPanels = panelList().filter(panel => panel.figure);
  const previews = new Map(projectPanels.map(panel => [imageKey(panel), panel]));
  const fittedWidth = uniformPanelWidth();
  const uniformWidth = fittedWidth ? Math.max(20, fittedWidth*25.4/72).toFixed(1) : "";
  let changed = await refreshPhotos();
  for (const [key, previous] of images) {
    if (!previews.has(key)) {
      URL.revokeObjectURL(previous.url);
      images.delete(key);
    }
  }
  for (const [key, panel] of previews) {
    const id = panel.figure;
    try {
      const query = "?id=" + encodeURIComponent(id);
      const {revision, notes} = await json("/api/board/revision" + query);
      const previous = images.get(key);
      if (!force && previous?.revision === revision && previous.uniformWidth === uniformWidth) continue;
      const request = query + (uniformWidth ? "&panelWidth=" + uniformWidth : "")
        + (panel.hideLegend ? "&hideLegend=1" : "");
      const response = await fetch("/api/board/preview" + request);
      if (!response.ok) throw new Error("无法预览项目图");
      const source = await response.text();
      // Each uniform panel retains the same viewport so all axis frames align.
      const trimmed = trimProjectSvg(source);
      const {svg, aspect} = uniformWidth ? {svg:source, aspect:89/55} : trimmed;
      const url = URL.createObjectURL(new Blob([svg], {type:"image/svg+xml"}));
      if (previous) URL.revokeObjectURL(previous.url);
      images.set(key, {revision, svg, url, aspect, notes, uniformWidth,
        inkLeft:uniformWidth ? trimmed.inkLeft : 0});
      changed = true;
    } catch (error) {
      const previous = images.get(key);
      if (previous) { URL.revokeObjectURL(previous.url); images.delete(key); changed = true; }
      status(`${id} · ${error.message}`);
    }
  }
  if (changed && !drag) draw();
}

function photoSvg(photo, frame) {
  const root = svgNode("svg", {...frame, viewBox:`0 ${photo.top} ${photo.width} ${photo.cropHeight}`,
    overflow:"hidden"});
  root.append(svgNode("image", {x:0, y:0, width:photo.width, height:photo.height, href:photo.source}));
  return root;
}

async function photoBounds(source) {
  const image = new Image();
  image.src = source;
  await image.decode();
  const {naturalWidth:width, naturalHeight:height} = image;
  const canvas = document.createElement("canvas");
  const scale = Math.min(1, 1200 / Math.max(width, height));
  canvas.width = Math.max(1, Math.round(width*scale));
  canvas.height = Math.max(1, Math.round(height*scale));
  const context = canvas.getContext("2d", {willReadFrequently:true});
  context.drawImage(image, 0, 0, canvas.width, canvas.height);
  const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
  const rowHasContent = row => {
    const end = 4 * (row+1) * canvas.width;
    for (let i = end-4*canvas.width; i < end; i += 4) {
      if (pixels[i+3] > 20 && Math.min(pixels[i], pixels[i+1], pixels[i+2]) < 245) return true;
    }
    return false;
  };
  let first = 0, last = canvas.height-1;
  while (first <= last && !rowHasContent(first)) first++;
  while (last > first && !rowHasContent(last)) last--;
  const top = first <= last ? Math.max(0, Math.floor((first-2)*height/canvas.height)) : 0;
  const bottom = first <= last ? Math.min(height, Math.ceil((last+3)*height/canvas.height)) : height;
  const photo = {source, width, height, top, cropHeight:bottom-top};
  if (photo.cropHeight < height) {
    const svg = photoSvg(photo, {width, height:photo.cropHeight});
    photo.url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(svg)], {type:"image/svg+xml"}));
  }
  return photo;
}

async function refreshPhotos() {
  let changed = false;
  const panels = panelList().filter(panel => panel.photo);
  for (const [id, previous] of photos) {
    if (panels.some(panel => panel.id === id && panel.photo === previous.source)) continue;
    if (previous.url) URL.revokeObjectURL(previous.url);
    photos.delete(id);
    changed = true;
  }
  await Promise.all(panels.map(async panel => {
    if (photos.has(panel.id)) return;
    try {
      const parsed = await photoBounds(panel.photo);
      if (!panelList().some(item => item.id === panel.id && item.photo === panel.photo) || photos.has(panel.id)) {
        if (parsed.url) URL.revokeObjectURL(parsed.url);
        return;
      }
      photos.set(panel.id, parsed);
      changed = true;
    } catch {
      // Keep the original image available if its bounds cannot be inspected.
    }
  }));
  return changed;
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
    const inkLeft = (left-original.x) / original.width;
    root.setAttribute("viewBox", `${left} ${top} ${width} ${height}`);
    root.setAttribute("width", `${width}pt`);
    root.setAttribute("height", `${height}pt`);
    return {svg:new XMLSerializer().serializeToString(root), aspect:width/height, inkLeft};
  } catch {
    return {svg:source, aspect};
  } finally {
    measure.remove();
  }
}

function gridPositions(page, aspects, {preset, custom, gapX, gapY, uniformPanels = false}) {
  const [width, height] = page.map(cm => cm * 10);
  const auto = preset === "auto";
  const [columns, rowLimit] = auto ? [Math.ceil(Math.sqrt(aspects.length)), Infinity]
    : (preset === "custom" ? custom : preset).split("x").map(Number);
  if (aspects.length > columns * rowLimit) {
    throw new Error(`当前有 ${aspects.length} 个面板，请选择容量更大的网格或自动排版。`);
  }
  const rows = [];
  const labelWidthMm = uniformPanels ? 0 : labelSizePt * 1.15 * 25.4 / 72;
  for (let i = 0; i < aspects.length; i += columns) {
    const ratios = aspects.slice(i, i+columns);
    const slots = auto && !uniformPanels ? ratios.length : columns;
    const cellWidth = (width - 2*edgeMarginMm - (slots-1)*gapX) / slots;
    if (cellWidth < .05*width) throw new Error("横向间距过大，请减小间距或增大画布。");
    const contentWidth = cellWidth - Math.min(labelWidthMm, cellWidth*.2875);
    rows.push({count:ratios.length, width:cellWidth, height:Math.max(...ratios.map(ratio => contentWidth/ratio))});
  }
  const gapHeight = 2*edgeMarginMm + (rows.length-1)*gapY;
  const minimum = .05*height;
  const needed = rows.reduce((sum, row) => sum+Math.max(row.height, minimum), 0);
  const available = height-gapHeight;
  if (available < rows.length*minimum) throw new Error("纵向间距过大，请减小间距或增大画布。");
  const scale = needed > available && needed > rows.length*minimum
    ? (available-rows.length*minimum)/(needed-rows.length*minimum) : 1;
  let top = edgeMarginMm;
  return rows.flatMap(row => {
    const rowHeight = minimum + Math.max(0, row.height-minimum)*scale;
    const y = round(100*top/height);
    top += rowHeight+gapY;
    return Array.from({length:row.count}, (_, column) => ({
      x:round(100*(edgeMarginMm+column*(row.width+gapX))/width), y,
      w:Math.floor(row.width/width*10000+1e-9)/100,
      h:Math.floor(rowHeight/height*10000+1e-9)/100,
    }));
  });
}

function arrangePanels(settings) {
  const preview = [...$("canvas").querySelectorAll(".panel img")];
  const properties = layout.panels.map(panel => {
    const source = panel.photo || panelImage(panel)?.url;
    const image = preview.find(item => item.getAttribute("src") === source);
    return panelAspect(panel) || (image?.naturalWidth / image?.naturalHeight) || 1.618;
  });
  const positions = gridPositions(layout.page, properties, {...settings, uniformPanels:layout.uniformPanels});
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
    const frame = chartFrame(panel, panel.w*w/100, panel.h*h/100);
    return {...frame, x:panel.x*w/100+frame.x, y:panel.y*h/100+frame.y};
  });
  const marks = boxes.map((frame, index) => panelLabelPosition(frame, layout.panels[index]));
  const padding = (layout.exportMarginMm ?? edgeMarginMm) * 72 / 25.4;
  const crop = layout.trimExport !== false;
  const leftEdges = boxes.map((box, index) =>
    box.x+box.width*(panelImage(layout.panels[index])?.inkLeft || 0));
  const left = crop ? Math.min(...leftEdges, ...marks.map(mark => mark.x)) - padding : 0;
  const top = crop ? Math.min(...boxes.map(box => box.y)) - padding : 0;
  const right = crop ? Math.max(...boxes.map(box => box.x+box.width)) + padding : w;
  const bottom = crop ? Math.max(...boxes.map(box => box.y+box.height)) + padding : h;
  const width = right-left, height = bottom-top;
  const cm = value => (value * 2.54 / 72).toFixed(3);
  const root = svgNode("svg", {width:`${cm(width)}cm`, height:`${cm(height)}cm`,
    viewBox:`${left} ${top} ${width} ${height}`});
  root.append(svgNode("rect", {x:left, y:top, width, height, fill:"white"}));
  layout.panels.forEach((panel, index) => {
    const {gutter, labelSize, ...size} = boxes[index];
    if (panel.figure) {
      const source = panelImage(panel)?.svg;
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
      child.setAttribute("overflow", "visible");
      root.append(child);
    } else if (panel.photo) {
      const photo = photos.get(panel.id);
      if (layout.trimPhotos !== false && photo?.source === panel.photo && photo.cropHeight < photo.height)
        root.append(photoSvg(photo, size));
      else root.append(svgNode("image", {...size, href:panel.photo, preserveAspectRatio:"xMidYMid meet"}));
    } else {
      throw new Error("请先填入或移除占位面板，再导出");
    }
    const mark = marks[index];
    const label = svgNode("text", {x:mark.x, y:mark.y+labelSize*.8, "font-size":labelSize,
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
  $("trimPhotos").checked = layout.trimPhotos !== false;
  $("uniformPanels").checked = !!layout.uniformPanels;
  $("uniformPanels").onchange = () => {
    layout.uniformPanels = $("uniformPanels").checked;
    markChanged();
    refreshImages();
  };
  $("trimPhotos").onchange = () => {
    layout.trimPhotos = $("trimPhotos").checked;
    markChanged(); draw();
  };
  $("exportMargin").value = layout.exportMarginMm ?? edgeMarginMm;
  $("trimExport").onchange = () => {
    layout.trimExport = $("trimExport").checked;
    markChanged();
    syncFields();
  };
  $("exportMargin").onchange = () => {
    const value = $("exportMargin").valueAsNumber;
    if (!Number.isFinite(value) || value < 0) {
      $("exportMargin").value = layout.exportMarginMm ?? edgeMarginMm;
      status("请输入大于或等于 0 的导出白边。");
      return;
    }
    layout.exportMarginMm = value;
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
    delete panel.hideLegend;
    Object.assign(panel, chosenFigure());
    markChanged(); draw(); refreshImages();
  };
  $("hidePanelLegend").onchange = () => {
    const panel = layout.panels.find(item => item.id === selected);
    if (!panel?.figure || draft) return;
    panel.hideLegend = $("hidePanelLegend").checked;
    markChanged();
    refreshImages();
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
