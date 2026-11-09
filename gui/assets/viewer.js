/* viewer.js - Visor interactivo de membranas (D3 v7).
 *
 * Qué dibuja: el medio (SK) es el "espacio" (rectángulo grande). Cada hijo directo del medio
 * es una CÉLULA libre (círculo) que se puede arrastrar. Lo que hay dentro (vacuolas, otras
 * células internalizadas...) se dibuja anidado con d3.pack. Cada membrana con objetos propios
 * tiene un disco de "contenido" cuyo tamaño/color depende de sus objetos.
 * Zoom: rueda.  Mover el espacio: arrastrar el fondo.  Mover una célula: arrastrarla.
 * Secciones: 1 datos | 2 layout | 3 dibujo | 4 panel | 5 controles
 */
(function () {
"use strict";

// ===================================================== 1. DATOS =====
const rec = RECORDING;
const frames = rec.frames;                       // frames[i].t === i
const T = frames.length - 1;
const SKIN = Object.keys(frames[0].parents).find(n => frames[0].parents[n] === null);
const natural = (a, b) => a.localeCompare(b, undefined, { numeric: true });
const NAMES = Object.keys(rec.membranes).sort(natural);   // todas las que han existido alguna vez
const exists = (f, n) => n in f.parents;                  // las membranas disueltas desaparecen del frame
const sum = o => Object.values(o || {}).reduce((a, b) => a + b, 0);
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const link = n => `<a class="lnk" data-sel="${esc(n)}">${esc(n)}</a>`;

frames.forEach(f => {                            // hijos de cada membrana (solo las que existen en ese paso)
  f.children = {};
  Object.keys(f.parents).forEach(n => (f.children[n] = []));
  Object.entries(f.parents).forEach(([n, p]) => { if (p !== null) f.children[p].push(n); });
  Object.values(f.children).forEach(list => list.sort(natural));
});

const OBJECTS = [...new Set(frames.flatMap(f => Object.values(f.objects).flatMap(o => Object.keys(o))))].sort();
let maxTotal = 1; const maxByObj = {};
frames.forEach(f => {
  for (const n in f.objects) {
    maxTotal = Math.max(maxTotal, sum(f.objects[n]));
    for (const o in f.objects[n]) maxByObj[o] = Math.max(maxByObj[o] || 1, f.objects[n][o]);
  }
});

const fired = {};                                // fired[membrana][regla][paso] = veces
frames.forEach((f, i) => f.events.forEach(e => {
  ((fired[e.membrane] = fired[e.membrane] || {})[e.rule] = fired[e.membrane][e.rule] || new Array(T + 1).fill(0))[i] += e.times;
}));

// ==================================================== 2. LAYOUT =====
const leafR = tot => 10 + 3.5 * Math.sqrt(tot);  // radio del disco de contenido

function buildTree(f, name) {
  const tot = sum(f.objects[name]);
  const kids = f.children[name].map(k => buildTree(f, k));
  if (kids.length === 0) return { name, own: false, total: tot, r: leafR(tot) };
  const node = { name, own: false, total: tot, children: kids };
  if (tot > 0) node.children = [{ name, own: true, total: tot, r: leafR(tot) }, ...kids];
  return node;
}

const topCache = [];
function topLayouts(fi) {                        // un d3.pack por cada célula libre
  if (topCache[fi]) return topCache[fi];
  const f = frames[fi];
  return (topCache[fi] = f.children[SKIN].map(name => {
    const root = d3.hierarchy(buildTree(f, name));
    d3.pack().size([0, 0]).radius(d => d.data.r).padding(5)(root);
    return { name, root, ox: root.x, oy: root.y };
  }));
}

// huecos fijos en una rejilla: cada célula vuelve siempre a su sitio aunque desaparezca un rato
const slotNames = [...new Set(frames.flatMap(f => f.children[SKIN]))].sort(natural);
let maxR = 25;
for (let i = 0; i <= T; i++) topLayouts(i).forEach(l => (maxR = Math.max(maxR, l.root.r)));
const SLOT = 2 * maxR + 50;
const COLS = Math.max(1, Math.ceil(Math.sqrt(slotNames.length)));
const ROWS = Math.max(1, Math.ceil(slotNames.length / COLS));
const WORLD_W = COLS * SLOT, WORLD_H = ROWS * SLOT;
const slotPos = {};
slotNames.forEach((n, i) => (slotPos[n] = { x: (i % COLS + 0.5) * SLOT, y: (Math.floor(i / COLS) + 0.5) * SLOT }));
const userPos = {};                              // posiciones arrastradas por el usuario

function positionedNodes(fi) {                   // todos los círculos con coordenadas del mundo
  const out = [];
  for (const l of topLayouts(fi)) {
    const base = userPos[l.name] || slotPos[l.name];
    l.root.descendants().forEach(d => out.push({
      key: d.data.name + (d.data.own ? "#own" : ""),
      name: d.data.name, own: !!d.data.own, inner: !!d.children, top: l.name, depth: d.depth,
      mdepth: (d.data.own ? d.depth - 1 : d.depth) + 1,           // profundidad de la membrana
      x: base.x + d.x - l.ox, y: base.y + d.y - l.oy, r: d.r,
    }));
  }
  return out;
}

// =================================================== 3. DIBUJO =====
const svg = d3.select("#canvas");
const gWorld = svg.append("g");
gWorld.append("rect").attr("class", "world-bg").attr("rx", 18).attr("width", WORLD_W).attr("height", WORLD_H)
  .on("click", () => select(SKIN));
gWorld.append("text").attr("class", "world-title").attr("x", 14).attr("y", 24).text(`${SKIN} (medio)`);
const gNodes = gWorld.append("g");

let t = 0, K = 1, selected = null, colorMode = "total", highlight = "";

const zoom = d3.zoom().scaleExtent([0.03, 40]).on("zoom", ev => {
  gWorld.attr("transform", ev.transform); K = ev.transform.k; updateLOD();
});
svg.call(zoom).on("dblclick.zoom", null);

function fillOf(d) {
  if (d.inner) return null;                                    // membrana contenedora: la pone el CSS
  const objs = frames[t].objects[d.name] || {};
  if (colorMode === "total") return d3.interpolateBlues(0.12 + 0.78 * sum(objs) / maxTotal);
  if (colorMode === "depth") return d3.schemeTableau10[d.mdepth % 10];
  const o = colorMode.slice(4);
  return d3.interpolateOranges(0.08 + 0.85 * (objs[o] || 0) / (maxByObj[o] || 1));
}

function objLines(objs) {                        // hasta 3 líneas de 2 objetos
  const items = Object.entries(objs || {}).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  const lines = [];
  for (let i = 0; i < items.length && lines.length < 3; i += 2)
    lines.push(items.slice(i, i + 2).map(([o, n]) => `${o}×${n}`).join(" "));
  if (items.length > 6) lines[2] += " …";
  return lines;
}

const dragBehavior = d3.drag().clickDistance(4).on("drag", (ev, d) => {
  const cur = userPos[d.top] || slotPos[d.top];
  userPos[d.top] = { x: cur.x + ev.dx, y: cur.y + ev.dy };    // mueve la célula entera
  render(false);
});

function render(animate) {
  const nodes = positionedNodes(t), dur = animate ? 380 : 0, f = frames[t];
  const sel = gNodes.selectAll("g.node").data(nodes, d => d.key);
  sel.exit().transition().duration(dur).style("opacity", 0).remove();

  const enter = sel.enter().append("g").attr("transform", d => `translate(${d.x},${d.y})`).style("opacity", 0);
  enter.append("title");
  enter.append("circle").attr("r", 0);
  enter.append("text").attr("class", "label");
  enter.append("text").attr("class", "objs");
  enter.on("click", (ev, d) => select(d.name)).call(dragBehavior);

  const all = enter.merge(sel);
  all.attr("class", d => `node ${d.own ? "own" : "mem"}${d.inner ? " inner" : ""}`)
    .classed("selected", d => d.name === selected)
    .classed("dim", d => highlight !== "" && !d.name.toLowerCase().includes(highlight));
  all.transition().duration(dur).attr("transform", d => `translate(${d.x},${d.y})`).style("opacity", null);
  all.select("circle").transition().duration(dur).attr("r", d => d.r).style("fill", fillOf);
  all.select("title").text(d => `${d.name}${d.own ? " (contenido)" : ""}\n` + (objLines(f.objects[d.name]).join("\n") || "sin objetos"));

  all.each(function (d) {                        // textos: nombre y objetos
    const g = d3.select(this), lines = d.inner ? [] : objLines(f.objects[d.name]);
    const label = g.select("text.label"), objs = g.select("text.objs");
    const fit = (len, max) => Math.max(4, Math.min(max, 2 * d.r * 0.88 / (0.6 * Math.max(1, len))));   // letra que cabe en el círculo
    const p = f.parents[d.name], short = p && d.name.startsWith(p + "_") ? d.name.slice(p.length + 1) : d.name;
    if (d.own) label.text("");
    else if (d.inner) label.text(d.name).attr("y", -d.r - 4).style("font-size", null);
    else label.text(short).attr("y", lines.length ? -lines.length * 6 + 2 : 4).style("font-size", fit(short.length, 11) + "px");
    objs.attr("y", d.own ? -(lines.length - 1) * 5.5 + 3 : -lines.length * 6 + 14)
      .style("font-size", fit(Math.max(0, ...lines.map(l => l.length)), 10) + "px");
    objs.selectAll("tspan").data(lines).join("tspan").attr("x", 0).attr("dy", (l, i) => (i ? "1.15em" : 0)).text(l => l);
  });
  all.sort((a, b) => a.depth - b.depth);         // los contenedores siempre debajo de lo que contienen
  updateLOD();
}

function updateLOD() {                           // nivel de detalle: textos solo si hay sitio al hacer zoom
  gNodes.selectAll("text.label").attr("display", d => (!d.own && d.r * K > (d.inner ? 22 : 9)) ? null : "none");
  gNodes.selectAll("text.objs").attr("display", d => (!d.inner && d.r * K > 20) ? null : "none");
}

function fitView(animate) {
  const w = svg.node().clientWidth, h = svg.node().clientHeight;
  if (!w || !h) return;
  const k = Math.min(w / (WORLD_W + 40), h / (WORLD_H + 40));
  const tr = d3.zoomIdentity.translate((w - WORLD_W * k) / 2, (h - WORLD_H * k) / 2).scale(k);
  (animate ? svg.transition().duration(500) : svg).call(zoom.transform, tr);
}

function centerOn(name) {
  if (name === SKIN) return fitView(true);
  const n = positionedNodes(t).find(d => d.name === name && !d.own);
  const w = svg.node().clientWidth, h = svg.node().clientHeight;
  if (!n || !w) return;
  const k = Math.max(0.05, Math.min(20, 0.45 * Math.min(w, h) / (2 * n.r)));
  svg.transition().duration(500).call(zoom.transform, d3.zoomIdentity.translate(w / 2 - k * n.x, h / 2 - k * n.y).scale(k));
}

// ==================================================== 4. PANEL =====
const panel = document.getElementById("panel");

function fateCountsAt(fi) {                      // sucesos acumulados hasta el paso fi
  const c = {};
  frames.slice(0, fi + 1).forEach(f => f.fates.forEach(x => (c[x.event] = (c[x.event] || 0) + 1)));
  return c;
}

function renderOutcome() {
  const c = Object.entries(fateCountsAt(t));
  document.getElementById("outcome").innerHTML = "Sucesos: " +
    (c.length ? c.map(([e, n]) => `<span class="badge">${esc(e)} ×${n}</span>`).join("") : '<span class="badge none">ninguno</span>') +
    (t === T ? ` <span class="muted">(${esc(rec.status)})</span>` : "");
}

function renderHud() {
  const objs = frames[t].objects[SKIN] || {};
  document.getElementById("hud").innerHTML = `${link(SKIN)} (medio): ` + (objLines(objs).join("  ") || '<span class="muted">sin objetos</span>');
  const leg = colorMode === "total" ? `Color = nº total de objetos (0–${maxTotal})`
    : colorMode === "depth" ? "Color = profundidad de anidamiento"
    : `Color = nº de objeto ${colorMode.slice(4)} (0–${maxByObj[colorMode.slice(4)] || 0})`;
  document.getElementById("legend").textContent = leg;
}

function sparkline(name) {
  const W = 300, H = 92, m = { l: 26, r: 6, t: 6, b: 16 };
  const maxOf = o => Math.max(...frames.map(f => (f.objects[name] || {})[o] || 0));
  const objs = [...new Set(frames.flatMap(f => Object.keys(f.objects[name] || {})))].sort((a, b) => maxOf(b) - maxOf(a));
  if (!objs.length) return '<div class="muted">Sin objetos en ningún paso</div>';
  const shown = objs.slice(0, 6), ymax = Math.max(1, ...shown.map(maxOf));
  const x = i => m.l + (T ? i / T : 0.5) * (W - m.l - m.r);
  const y = v => H - m.b - v / ymax * (H - m.t - m.b);
  const lines = shown.map((o, j) => `<polyline fill="none" stroke="${d3.schemeTableau10[j]}" stroke-width="1.7" points="${
    frames.map((f, i) => `${x(i)},${y((f.objects[name] || {})[o] || 0)}`).join(" ")}"/>`).join("");
  const legend = shown.map((o, j) => `<span style="color:${d3.schemeTableau10[j]}">■</span> ${esc(o)}`).join(" &nbsp;");
  return `<svg width="${W}" height="${H}" style="background:#fafafa;border:1px solid #e5e7eb">
    <line x1="${m.l}" y1="${y(0)}" x2="${W - m.r}" y2="${y(0)}" stroke="#cbd5e1"/>
    ${lines}
    <line x1="${x(t)}" y1="${m.t}" x2="${x(t)}" y2="${H - m.b}" stroke="#e11d48" stroke-dasharray="3 2"/>
    <text x="2" y="${m.t + 8}" font-size="10" fill="#6b7280">${ymax}</text><text x="12" y="${y(0)}" font-size="10" fill="#6b7280">0</text>
    <text x="${m.l}" y="${H - 3}" font-size="10" fill="#6b7280">0</text>
    <text x="${W - m.r - 14}" y="${H - 3}" font-size="10" fill="#6b7280">${T}</text></svg>
    <div>${legend}${objs.length > 6 ? ` <span class="muted">(+${objs.length - 6} más)</span>` : ""}</div>`;
}

function membranePanel(name) {
  const f = frames[t], prev = frames[Math.max(0, t - 1)], parents = f.parents;
  const info = rec.membranes[name];
  let h = `<h3>Membrana seleccionada</h3><div class="title">${esc(name)}` +
    (info.type ? ` <span class="muted">(${esc(info.type)})</span>` : "") + "</div>";
  if (!exists(f, name)) {                         // se ha disuelto: solo queda su historia
    const alive = frames.filter(fr => exists(fr, name)).map(fr => fr.t);
    h += `<div class="muted">No existe en t=${t} (existió de t=${alive[0]} a t=${alive[alive.length - 1]}: se disolvió).</div>`;
    return h + "<h3>Evolución de sus objetos</h3>" + sparkline(name) + "<h3>Posición en el tiempo</h3>" + historyHtml(name);
  }
  const path = []; for (let p = name; p !== null; p = parents[p]) path.unshift(p);
  const kids = f.children[name];
  h += `<div>Ruta: ${path.map(link).join(" › ")}</div>`;
  h += `<div>Contiene (${kids.length}): ` + (kids.length ? kids.map(k => `<span class="chip">${link(k)}</span>`).join("") : '<span class="muted">nada</span>') + "</div>";

  const o = f.objects[name] || {}, po = prev.objects[name] || {};
  const keys = [...new Set([...Object.keys(o), ...Object.keys(po)])].sort();
  h += `<h3>Objetos (t=${t})</h3>`;
  h += keys.length ? "<table><tr><th>objeto</th><th>n</th><th>Δ paso</th></tr>" + keys.map(k => {
    const dl = (o[k] || 0) - (po[k] || 0);
    return `<tr><td>${esc(k)}</td><td class="num">${o[k] || 0}</td><td class="num ${dl > 0 ? "up" : dl < 0 ? "down" : ""}">${t === 0 || dl === 0 ? "" : (dl > 0 ? "+" : "") + dl}</td></tr>`;
  }).join("") + "</table>" : '<div class="muted">vacía</div>';

  const rules = info.rules.map(id => rec.rule_defs[id]);        // las reglas se comparten por tipo
  h += `<h3>Reglas (${rules.length})</h3>`;
  h += rules.length ? rules.map(r => {
    const arr = (fired[name] || {})[r.name] || [], now = arr[t] || 0;
    const total = arr.slice(0, t + 1).reduce((a, b) => a + b, 0);
    return `<div class="rule ${now ? "fired" : ""}"><span class="rn">${esc(r.name)}</span> <span class="muted">(en este paso: ${now} · hasta ahora: ${total})</span><br>${esc(r.text)}` +
      (r.cond ? `<br><span class="rc">si ${esc(r.cond)}</span>` : "") + "</div>";
  }).join("") : '<div class="muted">sin reglas</div>';

  h += "<h3>Evolución de sus objetos</h3>" + sparkline(name);

  return h + "<h3>Posición en el tiempo</h3>" + historyHtml(name);
}

function historyHtml(name) {                     // cuándo cambia de padre o se disuelve
  const hist = []; let last = "__none__";
  frames.forEach(fr => {
    const p = exists(fr, name) ? fr.parents[name] : undefined;
    if (p !== last && !(p === undefined && last === "__none__")) { hist.push([fr.t, p]); last = p; }
  });
  return hist.map(([ti, p], i) => `<div class="ev">t=${ti}: ` +
    (p === undefined ? "se disuelve (desaparece)" : p === null ? "es el medio" : (i ? "pasa a estar dentro de " : "dentro de ") + link(p)) + "</div>").join("");
}

function renderPanel() {
  const f = frames[t], prev = frames[Math.max(0, t - 1)];
  let h = `<h3>Paso ${t} de ${T}</h3>`;
  h += f.events.length ? f.events.map(e => `<div class="ev">${link(e.membrane)}.${esc(e.rule)}${e.times > 1 ? " ×" + e.times : ""}</div>`).join("")
    : `<div class="muted">${t === 0 ? "Estado inicial" : "Ninguna regla aplicada (esperando)"}</div>`;
  if (t > 0) Object.keys(prev.parents).forEach(n => {              // cambios de estructura
    if (!exists(f, n)) h += `<div class="ev">✖ ${link(n)} se disuelve</div>`;
    else if (f.parents[n] !== prev.parents[n]) h += `<div class="ev">↳ ${link(n)} se mueve: ${link(prev.parents[n])} → ${link(f.parents[n])}</div>`;
  });
  f.fates.forEach(x => (h += `<div class="ev">◆ ${esc(x.event)}: ${link(x.cell)}${x.other ? " (con " + link(x.other) + ")" : ""}</div>`));
  h += selected ? membranePanel(selected)
    : '<h3>Ayuda</h3><div class="muted">Clic en una membrana para ver sus objetos, reglas y evolución. ' +
      "Arrastra una célula para moverla, la rueda hace zoom y arrastrar el fondo desplaza el espacio. " +
      "Atajos: ←/→ paso, espacio reproducir.</div>";
  panel.innerHTML = h;
}

function select(name) { selected = name; render(false); renderPanel(); }

panel.addEventListener("click", ev => {
  const a = ev.target.closest("[data-sel]");
  if (a) { select(a.dataset.sel); centerOn(a.dataset.sel); }
});
document.getElementById("hud").addEventListener("click", () => { select(SKIN); });

// ================================================= 5. CONTROLES =====
const slider = document.getElementById("slider"), btnPlay = document.getElementById("btnPlay");
const speed = document.getElementById("speed"), search = document.getElementById("search");
let timer = null;

function setT(i, animate = true) {
  t = Math.max(0, Math.min(T, i));
  slider.value = t;
  document.getElementById("tLabel").textContent = `t = ${t} / ${T}`;
  render(animate); renderPanel(); renderHud(); renderOutcome();
}
function stop() { clearInterval(timer); timer = null; btnPlay.textContent = "▶"; }
function togglePlay() {
  if (timer) return stop();
  if (t >= T) setT(0, false);
  btnPlay.textContent = "⏸";
  timer = setInterval(() => { if (t >= T) stop(); else setT(t + 1); }, +speed.value);
}

slider.max = T;
slider.addEventListener("input", () => { stop(); setT(+slider.value); });
btnPlay.onclick = togglePlay;
document.getElementById("btnFirst").onclick = () => { stop(); setT(0); };
document.getElementById("btnPrev").onclick = () => { stop(); setT(t - 1); };
document.getElementById("btnNext").onclick = () => { stop(); setT(t + 1); };
document.getElementById("btnLast").onclick = () => { stop(); setT(T); };
document.getElementById("btnFit").onclick = () => fitView(true);
speed.onchange = () => { if (timer) { stop(); togglePlay(); } };

const colorSel = document.getElementById("colorBy");
colorSel.innerHTML = '<option value="total">Total de objetos</option><option value="depth">Profundidad</option>' +
  OBJECTS.map(o => `<option value="obj:${esc(o)}">Objeto ${esc(o)}</option>`).join("");
colorSel.onchange = () => { colorMode = colorSel.value; render(false); renderHud(); };

document.getElementById("names").innerHTML = NAMES.map(n => `<option value="${esc(n)}">`).join("");
search.addEventListener("input", () => { highlight = search.value.trim().toLowerCase(); render(false); });
search.addEventListener("keydown", ev => {
  if (ev.key !== "Enter") return;
  const q = search.value.trim().toLowerCase();
  const hit = NAMES.find(n => n.toLowerCase() === q) || NAMES.find(n => n.toLowerCase().includes(q));
  if (hit) { select(hit); centerOn(hit); }
});

document.addEventListener("keydown", ev => {
  if (["INPUT", "SELECT"].includes(ev.target.tagName)) return;
  if (ev.key === "ArrowRight") { stop(); setT(t + 1); }
  else if (ev.key === "ArrowLeft") { stop(); setT(t - 1); }
  else if (ev.key === " ") { ev.preventDefault(); togglePlay(); }
});

setT(0, false);
requestAnimationFrame(() => fitView(false));
window.addEventListener("resize", () => fitView(false));
})();
