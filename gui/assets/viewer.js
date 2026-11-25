/* viewer.js - Visor interactivo de membranas (D3 v7).
 *
 * Qué dibuja: el medio (SK) es el "espacio" (rectángulo grande). Cada hijo directo del medio
 * es una CÉLULA libre (círculo) que se puede arrastrar. Lo que hay dentro (vacuolas, otras
 * células internalizadas...) se dibuja anidado con d3.pack. Cada membrana con objetos propios
 * tiene un disco de "contenido" cuyo tamaño/color depende de sus objetos. Si la grabación trae
 * vecindad (rec.layout / rec.links) las células se colocan en su rejilla y se dibujan los enlaces.
 * Zoom: rueda.  Mover el espacio: arrastrar el fondo.  Mover una célula: arrastrarla.
 * Secciones: 1 datos | 2 layout | 3 dibujo | 4 panel | 5 línea de tiempo | 6 exportar | 7 controles
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
const typeOf = n => (rec.membranes[n] || {}).type || null;
const chargeOf = (f, n) => (f.charges && f.charges[n]) || 0;
const ruleDefs = name => rec.membranes[name].rules.map(id => rec.rule_defs[id]);

frames.forEach(f => {                            // hijos de cada membrana (solo las que existen en ese paso)
  f.children = {};
  Object.keys(f.parents).forEach(n => (f.children[n] = []));
  Object.entries(f.parents).forEach(([n, p]) => { if (p !== null) f.children[p].push(n); });
  Object.values(f.children).forEach(list => list.sort(natural));
  f.fates = f.fates || []; f.events = f.events || []; f.pending = f.pending || [];
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
  const byRule = (fired[e.membrane] = fired[e.membrane] || {});
  (byRule[e.rule] = byRule[e.rule] || new Array(T + 1).fill(0))[i] += e.times;
}));

// flujos de objetos: flows[paso][membrana][objeto] = [{sign, n, rule, by}]  (qué regla gastó o aportó cada objeto)
const flows = frames.map(() => ({}));
function addFlow(i, m, obj, x) {
  const byM = (flows[i][m] = flows[i][m] || {});
  (byM[obj] = byM[obj] || []).push(x);
}
frames.forEach((f, i) => f.events.forEach(e => {
  (e.consumed || []).forEach(c => addFlow(i, c.at, c.obj, { sign: -1, n: c.n, rule: e.rule, by: e.membrane }));
  (e.produced || []).forEach(p => { if (p.due <= T) addFlow(p.due, p.at, p.obj, { sign: 1, n: p.n, rule: e.rule, by: e.membrane }); });
}));

// último suceso de cada célula hasta cada paso (para colorear por "destino")
const lastFate = []; let acc = {};
frames.forEach(f => { acc = Object.assign({}, acc); f.fates.forEach(x => { acc[x.cell] = x.event; }); lastFate.push(acc); });
const FATE_EVENTS = [...new Set(frames.flatMap(f => f.fates.map(x => x.event)))].sort();
const FATE_COLORS = {}; FATE_EVENTS.forEach((e, i) => (FATE_COLORS[e] = d3.schemeTableau10[i % 10]));

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

// huecos fijos: cada célula vuelve siempre a su sitio aunque desaparezca un rato.
// Con vecindad (rec.layout) el hueco es su casilla de la rejilla; si no, una rejilla automática.
const slotNames = [...new Set(frames.flatMap(f => f.children[SKIN]))].sort(natural);
let maxR = 25;
for (let i = 0; i <= T; i++) topLayouts(i).forEach(l => (maxR = Math.max(maxR, l.root.r)));
const SLOT = 2 * maxR + 50;
const layout = rec.layout || {};
const hasLayout = Object.keys(layout).length > 0;
const slotPos = {};
let COLS, ROWS;
if (hasLayout) {
  COLS = Math.max(...Object.values(layout).map(p => p[0])) + 1;
  ROWS = Math.max(...Object.values(layout).map(p => p[1])) + 1;
  const extras = slotNames.filter(n => !layout[n]);       // (células sin casilla: filas extra debajo)
  slotNames.forEach(n => {
    const k = extras.indexOf(n);
    const p = layout[n] || [k % COLS, ROWS + Math.floor(k / COLS)];
    slotPos[n] = { x: (p[0] + 0.5) * SLOT, y: (p[1] + 0.5) * SLOT };
  });
  ROWS += Math.ceil(extras.length / COLS);
} else {
  COLS = Math.max(1, Math.ceil(Math.sqrt(slotNames.length)));
  ROWS = Math.max(1, Math.ceil(slotNames.length / COLS));
  slotNames.forEach((n, i) => (slotPos[n] = { x: (i % COLS + 0.5) * SLOT, y: (Math.floor(i / COLS) + 0.5) * SLOT }));
}
const WORLD_W = COLS * SLOT, WORLD_H = ROWS * SLOT;
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
const gLinks = gWorld.append("g");
const gNodes = gWorld.append("g");

let t = 0, K = 1, selected = null, colorMode = "total", highlight = "";

const zoom = d3.zoom().scaleExtent([0.03, 40]).on("zoom", ev => {
  gWorld.attr("transform", ev.transform); K = ev.transform.k; updateLOD();
});
svg.call(zoom).on("dblclick.zoom", null);

// --- colores -------------------------------------------------------------
const STATE_COLORS = { "libre": "#93c5fd", "huésped": "#fbbf24", "internalizada": "#c4b5fd", "—": "#e5e7eb" };
function descendantOfType(f, name, ty) {
  return f.children[name].some(c => typeOf(c) === ty || descendantOfType(f, c, ty));
}
function stateOf(name, f) {                      // libre / huésped / internalizada (según el tipo de la membrana)
  const ty = typeOf(name);
  if (!ty) return "—";
  for (let p = f.parents[name]; p != null; p = f.parents[p]) if (typeOf(p) === ty) return "internalizada";
  return descendantOfType(f, name, ty) ? "huésped" : "libre";
}
const colorModes = {
  state: { label: "Estado (libre / huésped / internalizada)", cats: STATE_COLORS,
    of: (d, f) => STATE_COLORS[stateOf(d.name, f)] },
  fate: { label: "Destino (último suceso de la célula)", cats: Object.assign({ "sin suceso": "#e5e7eb" }, FATE_COLORS),
    of: d => FATE_COLORS[lastFate[t][d.name]] || "#e5e7eb" },
  charge: { label: "Carga (0 / 1)", cats: { "0": "#dbeafe", "1": "#fdba74" },
    of: (d, f) => (chargeOf(f, d.name) ? "#fdba74" : "#dbeafe") },
};
function fillOf(d) {
  if (d.inner) return null;                                    // membrana contenedora: la pone el CSS
  const f = frames[t], objs = f.objects[d.name] || {};
  if (colorModes[colorMode]) return colorModes[colorMode].of(d, f);
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
  const tr = sel => (dur ? sel.transition().duration(dur) : sel);          // sin animación = cambio inmediato
  const sel = gNodes.selectAll("g.node").data(nodes, d => d.key);
  sel.exit().transition().duration(dur).style("opacity", 0).remove();

  const enter = sel.enter().append("g").attr("transform", d => `translate(${d.x},${d.y})`).style("opacity", dur ? 0 : 1);
  enter.append("title");
  enter.append("circle").attr("r", dur ? 0 : d => d.r);
  enter.append("text").attr("class", "label");
  enter.append("text").attr("class", "objs");
  enter.on("click", (ev, d) => select(d.name)).call(dragBehavior);

  const all = enter.merge(sel);
  all.attr("class", d => `node ${d.own ? "own" : "mem"}${d.inner ? " inner" : ""}`)
    .classed("selected", d => d.name === selected)
    .classed("ch1", d => !d.own && chargeOf(f, d.name) === 1)
    .classed("dim", d => highlight !== "" && !d.name.toLowerCase().includes(highlight));
  tr(all).attr("transform", d => `translate(${d.x},${d.y})`).style("opacity", 1);
  all.each(d => { d.fill = fillOf(d); });        // el color se calcula YA (una animación lo leería tarde, con otro t)
  tr(all.select("circle")).attr("r", d => d.r).style("fill", d => d.fill);
  all.select("title").text(d => `${d.name}${d.own ? " (contenido)" : ""}${chargeOf(f, d.name) ? " · carga 1" : ""}\n` +
    (objLines(f.objects[d.name]).join("\n") || "sin objetos"));

  all.each(function (d) {                        // textos: nombre y objetos
    const g = d3.select(this), lines = d.inner ? [] : objLines(f.objects[d.name]);
    const label = g.select("text.label"), objs = g.select("text.objs");
    const fit = (len, max) => Math.max(4, Math.min(max, 2 * d.r * 0.88 / (0.6 * Math.max(1, len))));   // letra que cabe
    const p = f.parents[d.name], short = p && d.name.startsWith(p + "_") ? d.name.slice(p.length + 1) : d.name;
    if (d.own) label.text("");
    else if (d.inner) label.text(d.name).attr("y", -d.r - 4).style("font-size", null);
    else label.text(short).attr("y", lines.length ? -lines.length * 6 + 2 : 4).style("font-size", fit(short.length, 11) + "px");
    objs.attr("y", d.own ? -(lines.length - 1) * 5.5 + 3 : -lines.length * 6 + 14)
      .style("font-size", fit(Math.max(0, ...lines.map(l => l.length)), 10) + "px");
    objs.selectAll("tspan").data(lines).join("tspan").attr("x", 0).attr("dy", (l, i) => (i ? "1.15em" : 0)).text(l => l);
  });
  all.sort((a, b) => a.depth - b.depth);         // los contenedores siempre debajo de lo que contienen
  renderLinks(nodes);
  updateLOD();
}

function renderLinks(nodes) {                    // enlaces de vecindad entre células libres
  const pos = {};
  nodes.forEach(d => { if (d.depth === 0 && !d.own) pos[d.name] = d; });
  const ls = (rec.links || []).filter(([a, b, t0]) => t0 <= t && pos[a] && pos[b]);
  gLinks.selectAll("line").data(ls, d => d[0] + "|" + d[1]).join("line")
    .attr("class", d => "link" + (d[2] > 0 ? " new" : ""))
    .attr("x1", d => pos[d[0]].x).attr("y1", d => pos[d[0]].y)
    .attr("x2", d => pos[d[1]].x).attr("y2", d => pos[d[1]].y);
}

function updateLOD() {                           // nivel de detalle: textos solo si hay sitio al hacer zoom
  gNodes.selectAll("text.label").attr("display", d => (!d.own && d.r * K > (d.inner ? 22 : 9)) ? null : "none");
  gNodes.selectAll("text.objs").attr("display", d => (!d.inner && d.r * K > 20) ? null : "none");
}

function fitView(animate) {
  const w = svg.node().clientWidth, h = svg.node().clientHeight;
  if (!w || !h) return;
  const k = Math.min(w / (WORLD_W + 40), h / (WORLD_H + 40));
  const tf = d3.zoomIdentity.translate((w - WORLD_W * k) / 2, (h - WORLD_H * k) / 2).scale(k);
  (animate ? svg.transition().duration(500) : svg).call(zoom.transform, tf);
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
  const leg = document.getElementById("legend"), cm = colorModes[colorMode];
  if (cm) leg.innerHTML = esc(cm.label) + ":" + Object.entries(cm.cats).map(([k, c]) => `<span class="sw" style="background:${c}"></span>${esc(k)}`).join("");
  else if (colorMode === "total") leg.textContent = `Color = nº total de objetos (0–${maxTotal})`;
  else if (colorMode === "depth") leg.textContent = "Color = profundidad de anidamiento";
  else leg.textContent = `Color = nº de objeto ${colorMode.slice(4)} (0–${maxByObj[colorMode.slice(4)] || 0})`;
}

function sparkline(name) {
  const W = 340, H = 92, m = { l: 26, r: 6, t: 6, b: 16 };
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

const itemsHtml = (items, name, t_) => items.map(i =>
  `${esc(i.obj)}×${i.n}` + (i.at !== name ? ` en ${link(i.at)}` : "") +
  (i.due !== undefined ? (i.due > t_ ? ` <span class="small">(llega en t=${i.due})</span>` : ` <span class="small">(al final del paso)</span>`) : "")).join(", ");

function eventCard(e, name) {                    // una regla aplicada en esta membrana en el paso t
  const d = ruleDefs(name).find(r => r.name === e.rule) || { weight: 1, delay: 0 };
  let h = `<div class="card"><div><b>${esc(e.rule)}</b> ×${e.times} <span class="small">peso ${d.weight} · retardo ${d.delay}</span></div>`;
  if (e.partners.length) h += `<div>Compañero: ${[...new Set(e.partners)].map(link).join(", ")}</div>`;
  if (e.checks.length) h += `<details><summary>Condiciones cumplidas (${e.checks.length})</summary>${e.checks.map(c => `<div class="ok">✔ ${esc(c)}</div>`).join("")}</details>`;
  if (e.consumed.length) h += `<div class="cons">Consumió: ${itemsHtml(e.consumed, name, t)}</div>`;
  if (e.produced.length) h += `<div class="prod">Produjo: ${itemsHtml(e.produced, name, t)}</div>`;
  if (e.actions.length) h += `<div>Acciones: ${e.actions.map(esc).join("; ")}</div>`;
  return h + "</div>";
}

function originText(arr) {                       // "−2 invade (C1), +4 make_R (C1)" agrupado
  const g = {};
  (arr || []).forEach(x => { const k = `${x.sign}|${x.rule}|${x.by}`; g[k] = (g[k] || 0) + x.n; });
  return Object.entries(g).map(([k, n]) => { const [s, r, by] = k.split("|");
    return `<span class="${s === "1" ? "up" : "down"}">${s === "1" ? "+" : "−"}${n} ${esc(r)}</span> <span class="small">(${link(by)})</span>`; }).join(", ");
}

function membranePanel(name) {
  const f = frames[t], prev = frames[Math.max(0, t - 1)], parents = f.parents, info = rec.membranes[name];
  let h = `<h3>Membrana seleccionada</h3><div class="title">${esc(name)}` +
    (info.type ? ` <span class="muted">(${esc(info.type)})</span>` : "") + "</div>";
  if (!exists(f, name)) {                         // se ha disuelto: solo queda su historia
    const alive = frames.filter(fr => exists(fr, name)).map(fr => fr.t);
    h += `<div class="muted">No existe en t=${t} (existió de t=${alive[0]} a t=${alive[alive.length - 1]}: se disolvió).</div>`;
    return h + activityHtml(name) + "<h3>Evolución de sus objetos</h3>" + sparkline(name) + "<h3>Posición en el tiempo</h3>" + historyHtml(name);
  }
  const path = []; for (let p = name; p !== null; p = parents[p]) path.unshift(p);
  const kids = f.children[name];
  h += `<div>Carga: <span class="chg">${chargeOf(f, name)}</span> &nbsp; Ruta: ${path.map(link).join(" › ")}</div>`;
  h += `<div>Contiene (${kids.length}): ` + (kids.length ? kids.map(k => `<span class="chip">${link(k)}</span>`).join("") : '<span class="muted">nada</span>') + "</div>";

  // reglas aplicadas en ESTA membrana en este paso: qué consumieron, produjeron y qué condiciones cumplían
  const mine = f.events.filter(e => e.membrane === name);
  h += `<h3>Reglas aplicadas en el paso ${t}</h3>` + (mine.length ? mine.map(e => eventCard(e, name)).join("")
    : '<div class="muted">Ninguna regla se aplicó en esta membrana en este paso.</div>');

  // objetos: cantidad, variación y de qué regla viene cada cambio (también las de otras membranas)
  const o = f.objects[name] || {}, po = prev.objects[name] || {}, fl = (flows[t] || {})[name] || {};
  const keys = [...new Set([...Object.keys(o), ...Object.keys(po), ...Object.keys(fl)])].sort();
  h += `<h3>Objetos (t=${t})</h3>`;
  h += keys.length ? "<table><tr><th>objeto</th><th>n</th><th>Δ</th><th>origen del cambio</th></tr>" + keys.map(k => {
    const dl = (o[k] || 0) - (po[k] || 0);
    return `<tr><td>${esc(k)}</td><td class="num">${o[k] || 0}</td><td class="num ${dl > 0 ? "up" : dl < 0 ? "down" : ""}">${t === 0 || dl === 0 ? "" : (dl > 0 ? "+" : "") + dl}</td><td>${t === 0 ? "" : originText(fl[k])}</td></tr>`;
  }).join("") + "</table>" : '<div class="muted">vacía</div>';
  const pend = f.pending.filter(p => p.at === name);
  if (pend.length) h += `<div class="small">En curso (retardo): ${pend.map(p => `${esc(p.obj)}×${p.n} llega en t=${p.due}`).join(", ")}</div>`;

  const rules = ruleDefs(name);
  h += `<h3>Todas sus reglas (${rules.length})</h3>`;
  h += rules.length ? rules.map(r => {
    const arr = (fired[name] || {})[r.name] || [], now = arr[t] || 0;
    const total = arr.slice(0, t + 1).reduce((a, b) => a + b, 0);
    return `<div class="rule ${now ? "fired" : ""}"><span class="rn">${esc(r.name)}</span> <span class="muted">(peso ${r.weight} · retardo ${r.delay} · en este paso: ${now} · hasta ahora: ${total})</span><br>${esc(r.text)}` +
      (r.cond ? `<br><span class="rc">si ${esc(r.cond)}</span>` : "") + "</div>";
  }).join("") : '<div class="muted">sin reglas</div>';

  return h + activityHtml(name) + "<h3>Evolución de sus objetos</h3>" + sparkline(name) + "<h3>Posición en el tiempo</h3>" + historyHtml(name);
}

function activityHtml(name) {                    // historial: en qué pasos aplicó reglas (clic = ir a ese paso)
  const rows = [];
  frames.forEach((fr, i) => {
    const es = fr.events.filter(e => e.membrane === name);
    if (es.length) rows.push(`<div class="ev"><a class="lnk" data-step="${i}">t=${i}</a>: ${es.map(e => `${esc(e.rule)}${e.times > 1 ? " ×" + e.times : ""}`).join(", ")}</div>`);
  });
  return "<h3>Actividad a lo largo del tiempo</h3>" + (rows.join("") || '<div class="muted">Nunca aplicó reglas.</div>');
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
  const byRule = {};                              // resumen por regla (agrupado: sirve con miles de membranas)
  f.events.forEach(e => { const r = (byRule[e.rule] = byRule[e.rule] || { times: 0, ms: [] }); r.times += e.times; r.ms.push(e.membrane); });
  h += Object.keys(byRule).length ? Object.entries(byRule).map(([r, x]) =>
    `<div class="ev"><b>${esc(r)}</b> ×${x.times} en ${x.ms.length} membrana(s): ${x.ms.slice(0, 5).map(link).join(", ")}${x.ms.length > 5 ? " …" : ""}</div>`).join("")
    : `<div class="muted">${t === 0 ? "Estado inicial" : "Ninguna regla aplicada (esperando)"}</div>`;
  if (t > 0) {                                    // cambios de estructura
    const moved = [], gone = [];
    Object.keys(prev.parents).forEach(n => {
      if (!exists(f, n)) gone.push(n);
      else if (f.parents[n] !== prev.parents[n]) moved.push(n);
    });
    moved.slice(0, 8).forEach(n => (h += `<div class="ev">↳ ${link(n)} se mueve: ${link(prev.parents[n])} → ${link(f.parents[n])}</div>`));
    if (moved.length > 8) h += `<div class="small">… y ${moved.length - 8} movimientos más</div>`;
    gone.slice(0, 8).forEach(n => (h += `<div class="ev">✖ ${link(n)} se disuelve</div>`));
    if (gone.length > 8) h += `<div class="small">… y ${gone.length - 8} disoluciones más</div>`;
  }
  f.fates.slice(0, 10).forEach(x => (h += `<div class="ev">◆ ${esc(x.event)}: ${link(x.cell)}${x.other ? " (con " + link(x.other) + ")" : ""}</div>`));
  if (f.fates.length > 10) h += `<div class="small">… y ${f.fates.length - 10} sucesos más</div>`;
  if (f.pending.length) h += `<div class="small">Productos en curso (retardos): ${f.pending.reduce((a, p) => a + p.n, 0)}</div>`;
  h += selected ? membranePanel(selected)
    : '<h3>Ayuda</h3><div class="muted">Clic en una membrana para estudiar sus reglas aplicadas, lo que consumieron y produjeron y las condiciones cumplidas. ' +
      "Arrastra una célula para moverla, la rueda hace zoom y arrastrar el fondo desplaza el espacio. " +
      "Atajos: ←/→ paso, espacio reproducir.</div>";
  panel.innerHTML = h;
}

function select(name) { selected = name; render(false); renderPanel(); }

panel.addEventListener("click", ev => {
  const a = ev.target.closest("[data-sel]"), s = ev.target.closest("[data-step]");
  if (a) { select(a.dataset.sel); centerOn(a.dataset.sel); }
  else if (s) { stop(); setT(+s.dataset.step); }
});
document.getElementById("hud").addEventListener("click", () => { select(SKIN); });

// ============================================ 5. LÍNEA DE TIEMPO =====
const tl = d3.select("#timeline").append("svg").attr("viewBox", "0 0 1000 38").attr("preserveAspectRatio", "none");
const EVENT_STEPS = frames.map((f, i) => (f.fates.length ? i : -1)).filter(i => i >= 0);
(function buildTimeline() {
  const n = T + 1, W = 1000, w = W / n;
  const counts = frames.map(f => f.events.reduce((a, e) => a + e.times, 0)), maxC = Math.max(1, ...counts);
  tl.selectAll("rect.bar").data(counts).join("rect").attr("class", "bar").attr("fill", "#cbd5e1")
    .attr("x", (d, i) => i * w + 0.5).attr("width", Math.max(0.5, w - 1))
    .attr("y", d => 38 - 4 - d / maxC * 24).attr("height", d => d / maxC * 24);
  frames.forEach((f, i) => f.fates.slice(0, 6).forEach((x, k) =>      // un punto de color por suceso
    tl.append("circle").attr("cx", (i + 0.5) * w).attr("cy", 5 + k * 3.5).attr("r", 2.6)
      .attr("fill", FATE_COLORS[x.event]).append("title").text(`t=${i}: ${x.event} ${x.cell}`)));
  tl.append("line").attr("id", "tlCursor").attr("y1", 0).attr("y2", 38).attr("stroke", "#e11d48").attr("stroke-width", 2);
  document.getElementById("timeline").addEventListener("click", ev => {
    const box = ev.currentTarget.getBoundingClientRect();
    if (!box.width) return;
    stop(); setT(Math.min(T, Math.max(0, Math.floor((ev.clientX - box.left) / box.width * n))));
  });
})();
function updateTimeline() {
  const x = (t + 0.5) / (T + 1) * 1000;
  tl.select("#tlCursor").attr("x1", x).attr("x2", x);
}

// ================================================= 6. EXPORTAR =====
function svgMarkup() {                           // la vista actual como SVG autocontenido (con sus estilos)
  const node = svg.node().cloneNode(true), w = svg.node().clientWidth || 1000, h = svg.node().clientHeight || 700;
  node.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  node.setAttribute("width", w); node.setAttribute("height", h); node.setAttribute("viewBox", `0 0 ${w} ${h}`);
  const style = document.createElementNS("http://www.w3.org/2000/svg", "style");
  style.textContent = document.querySelector("style").textContent;
  const bg = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  bg.setAttribute("width", w); bg.setAttribute("height", h); bg.setAttribute("fill", "#eef1f5");
  node.insertBefore(bg, node.firstChild); node.insertBefore(style, node.firstChild);
  return new XMLSerializer().serializeToString(node);
}
function download(blob, name) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = name; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
function svgToCanvas(scale) {                    // SVG -> <canvas> (para PNG y vídeo)
  return new Promise((resolve, reject) => {
    const w = svg.node().clientWidth || 1000, h = svg.node().clientHeight || 700, img = new Image();
    img.onload = () => {
      const c = document.createElement("canvas"); c.width = w * scale; c.height = h * scale;
      const ctx = c.getContext("2d"); ctx.scale(scale, scale); ctx.drawImage(img, 0, 0, w, h); resolve(c);
    };
    img.onerror = reject;
    img.src = URL.createObjectURL(new Blob([svgMarkup()], { type: "image/svg+xml;charset=utf-8" }));
  });
}
const fname = ext => `${rec.name}_t${t}.${ext}`;
document.getElementById("btnSvg").onclick = () => download(new Blob([svgMarkup()], { type: "image/svg+xml" }), fname("svg"));
document.getElementById("btnPng").onclick = () => svgToCanvas(2).then(c => c.toBlob(b => download(b, fname("png"))));
document.getElementById("btnVideo").onclick = async () => {   // graba t=0..T en un WebM (necesita un navegador con MediaRecorder)
  if (!window.MediaRecorder) { alert("Este navegador no permite grabar vídeo (MediaRecorder)."); return; }
  stop();
  const keep = t, btn = document.getElementById("btnVideo"); btn.disabled = true; btn.textContent = "Grabando…";
  try {
    const first = await svgToCanvas(1), canvas = document.createElement("canvas");
    canvas.width = first.width; canvas.height = first.height;
    const ctx = canvas.getContext("2d"), chunks = [];
    const recorder = new MediaRecorder(canvas.captureStream(10), { mimeType: "video/webm" });
    recorder.ondataavailable = e => chunks.push(e.data);
    const stopped = new Promise(r => (recorder.onstop = r));
    recorder.start();
    for (let i = 0; i <= T; i++) {
      setT(i, false); ctx.drawImage(await svgToCanvas(1), 0, 0);
      await new Promise(r => setTimeout(r, +speed.value));
    }
    recorder.stop(); await stopped;
    download(new Blob(chunks, { type: "video/webm" }), `${rec.name}.webm`);
  } catch (err) { alert("No se pudo grabar el vídeo: " + err); }
  btn.disabled = false; btn.textContent = "Vídeo"; setT(keep, false);
};

// ================================================= 7. CONTROLES =====
const slider = document.getElementById("slider"), btnPlay = document.getElementById("btnPlay");
const speed = document.getElementById("speed"), search = document.getElementById("search");
let timer = null;

function setT(i, animate = true) {
  if (!Number.isFinite(i)) return;
  t = Math.max(0, Math.min(T, i));
  slider.value = t;
  document.getElementById("tLabel").textContent = `t = ${t} / ${T}`;
  render(animate); renderPanel(); renderHud(); renderOutcome(); updateTimeline();
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
document.getElementById("btnNextEvt").onclick = () => { const n = EVENT_STEPS.find(i => i > t); if (n !== undefined) { stop(); setT(n); } };
document.getElementById("btnPrevEvt").onclick = () => { const p = [...EVENT_STEPS].reverse().find(i => i < t); if (p !== undefined) { stop(); setT(p); } };
speed.onchange = () => { if (timer) { stop(); togglePlay(); } };

const colorSel = document.getElementById("colorBy");
colorSel.innerHTML = '<option value="total">Total de objetos</option><option value="depth">Profundidad</option>' +
  Object.entries(colorModes).map(([k, m]) => `<option value="${k}">${esc(m.label.split(" (")[0])}</option>`).join("") +
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
