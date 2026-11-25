"""analysis.py - Tablas y gráficos de análisis calculados a partir de una GRABACIÓN (dict).

No dependen del motor ni de Streamlit: funcionan igual con una grabación recién
simulada o con una cargada desde un .json. Las membranas pueden desaparecer (disolverse):
cada frame solo contiene las que existen en ese paso.
"""
from collections import defaultdict

import pandas as pd


def objects_text(objects: dict, limit: int = 8) -> str:
    items = sorted(objects.items(), key=lambda kv: (-kv[1], kv[0]))
    txt = "  ".join(f"{o}×{n}" for o, n in items[:limit])
    return txt + (f"  (+{len(items) - limit} más)" if len(items) > limit else "")


def depth_of(parents: dict, name: str) -> int:
    d = 0
    while parents[name] is not None:
        name, d = parents[name], d + 1
    return d


def path_of(parents: dict, name: str) -> list[str]:
    path = [name]
    while parents[path[-1]] is not None:
        path.append(parents[path[-1]])
    return path[::-1]                                   # del medio hacia la membrana


# ------------------------------------------------------ membranas ---
def membranes_table(rec: dict, t: int) -> pd.DataFrame:
    """Una fila por membrana que existe en el paso t."""
    frame = rec["frames"][t]
    parents, objects, charges = frame["parents"], frame["objects"], frame.get("charges", {})
    n_children = defaultdict(int)
    for p in parents.values():
        if p is not None:
            n_children[p] += 1
    applied = defaultdict(int)                          # reglas aplicadas hasta t, por membrana
    for f in rec["frames"][: t + 1]:
        for e in f["events"]:
            applied[e["membrane"]] += e["times"]
    rows = []
    for name, parent in parents.items():
        objs = objects.get(name, {})
        rows.append({
            "membrana": name,
            "tipo": rec["membranes"][name]["type"] or "—",
            "dentro_de": parent or "—",
            "profundidad": depth_of(parents, name),
            "carga": charges.get(name, 0),
            "hijos": n_children[name],
            "n_objetos": sum(objs.values()),
            "objetos": objects_text(objs),
            "reglas": len(rec["membranes"][name]["rules"]),
            "aplicaciones": applied[name],
        })
    return pd.DataFrame(rows)


def position_history(rec: dict, name: str) -> list[tuple[int, str]]:
    """[(paso, estado)] cada vez que cambia de padre; 'disuelta' cuando desaparece."""
    hist, last = [], "__none__"
    for f in rec["frames"]:
        p = f["parents"][name] if name in f["parents"] else "disuelta"
        p = p or "—"
        if p != last and not (p == "disuelta" and last == "__none__"):
            hist.append((f["t"], p))
        last = p
    return hist


# --------------------------------------------------------- eventos ---
def _items_text(items: list[dict], with_due: bool = False) -> str:
    return ", ".join(f"{i['obj']}×{i['n']}@{i['at']}" + (f" (llega t={i['due']})" if with_due else "") for i in items)


def events_table(rec: dict) -> pd.DataFrame:
    """Una fila por (paso, membrana, regla) con lo que consumió, produjo y el compañero elegido."""
    rows = [{"paso": f["t"], "membrana": e["membrane"], "regla": e["rule"], "veces": e["times"],
             "consumio": _items_text(e.get("consumed", [])),
             "produjo": _items_text(e.get("produced", []), with_due=True),
             "companeros": ", ".join(e.get("partners", [])),
             "acciones": "; ".join(e.get("actions", []))}
            for f in rec["frames"] for e in f["events"]]
    return pd.DataFrame(rows, columns=["paso", "membrana", "regla", "veces", "consumio", "produjo",
                                       "companeros", "acciones"])


def moves_table(rec: dict) -> pd.DataFrame:
    """Cambios de estructura: membranas que cambian de padre o se disuelven."""
    rows, frames = [], rec["frames"]
    for prev, cur in zip(frames, frames[1:]):
        for name, old in prev["parents"].items():
            new = cur["parents"].get(name, "(disuelta)")
            if new != old:
                rows.append({"paso": cur["t"], "membrana": name, "desde": old, "hacia": new})
    return pd.DataFrame(rows, columns=["paso", "membrana", "desde", "hacia"])


def rule_usage_table(rec: dict) -> pd.DataFrame:
    """Una fila por DEFINICIÓN de regla (se comparten entre todas las células de un tipo):
    cuántas veces se aplicó en total, primer/último paso y en cuántas membranas distintas."""
    by_rule = {rid: {"veces": 0, "pasos": [], "membranas": set()} for rid in rec["rule_defs"]}
    ids = {(m, rec["rule_defs"][rid]["name"]): rid
           for m, info in rec["membranes"].items() for rid in info["rules"]}
    for f in rec["frames"]:
        for e in f["events"]:
            u = by_rule[ids[(e["membrane"], e["rule"])]]
            u["veces"] += e["times"]
            u["pasos"].append(f["t"])
            u["membranas"].add(e["membrane"])
    rows = []
    for rid, d in rec["rule_defs"].items():
        u = by_rule[rid]
        rows.append({"tipo": d["owner"], "regla": d["name"], "peso": d.get("weight", 1), "retardo": d.get("delay", 0),
                     "veces": u["veces"], "membranas_distintas": len(u["membranas"]),
                     "primer_paso": min(u["pasos"]) if u["pasos"] else None,
                     "ultimo_paso": max(u["pasos"]) if u["pasos"] else None,
                     "condicion": d["cond"] or "—", "regla_texto": d["text"]})
    return pd.DataFrame(rows)


def membrane_rules_table(rec: dict, name: str) -> pd.DataFrame:
    """Reglas de UNA membrana y cuántas veces se aplicaron en ella."""
    ev = events_table(rec)
    rows = []
    for rid in rec["membranes"][name]["rules"]:
        d = rec["rule_defs"][rid]
        sub = ev[(ev.membrana == name) & (ev.regla == d["name"])]
        rows.append({"regla": d["name"], "peso": d.get("weight", 1), "retardo": d.get("delay", 0),
                     "veces": int(sub.veces.sum()), "primer_paso": int(sub.paso.min()) if len(sub) else None,
                     "condicion": d["cond"] or "—"})
    return pd.DataFrame(rows, columns=["regla", "peso", "retardo", "veces", "primer_paso", "condicion"])


# ------------------------------------------------------- resultados ---
def fates_table(rec: dict) -> pd.DataFrame:
    """Un suceso por fila: internalización, muerte, escape... y las células implicadas."""
    rows = [{"paso": f["t"], "suceso": x["event"], "celula": x["cell"], "con": x["other"] or "—"}
            for f in rec["frames"] for x in f["fates"]]
    return pd.DataFrame(rows, columns=["paso", "suceso", "celula", "con"])


def fates_by_cell(rec: dict) -> pd.DataFrame:
    """Por célula protagonista: su secuencia de sucesos, p. ej. 'internalization (t3) → escape (t4)'."""
    fa = fates_table(rec)
    rows = []
    for cell, sub in fa.groupby("celula", sort=False):
        rows.append({"celula": cell, "n_sucesos": len(sub),
                     "secuencia": " → ".join(f"{r.suceso} (t{r.paso})" for r in sub.itertuples())})
    return pd.DataFrame(rows, columns=["celula", "n_sucesos", "secuencia"])


# ------------------------------------------------ mapa de dependencias ---
def _q(text: str) -> str:
    return '"' + str(text).replace('"', "'") + '"'


def dependency_dot(rec: dict, owners: list[str] | None = None) -> str:
    """Grafo (DOT/Graphviz) de objetos ↔ reglas, por tipo de membrana.
    Cuadrados = reglas · elipses = objetos agrupados por dónde viven · flecha continua = se consume
    (objeto → regla) o se produce (regla → objeto) · discontinua = umbral que la regla exige sin gastarlo."""
    defs = {rid: d for rid, d in rec["rule_defs"].items() if owners is None or d["owner"] in owners}
    lines = ["digraph G {", "rankdir=LR; compound=true;",
             'node [fontname="Helvetica", fontsize=11]; edge [fontname="Helvetica", fontsize=9];']
    objs = {}                                            # (loc, obj) -> id de nodo
    for rid, d in defs.items():
        for key in ("inputs", "outputs", "gates"):
            for it in d["io"][key]:
                objs.setdefault((it["loc"], it["obj"]), f"o_{len(objs)}")
    for loc in sorted({k[0] for k in objs}):             # un recuadro por lugar (tipo o nombre de membrana)
        lines.append(f"subgraph {_q('cluster_' + loc)} {{ label={_q(loc)}; style=rounded; color=gray;")
        lines += [f"{nid} [label={_q(o)}, shape=ellipse, style=filled, fillcolor=\"#dbeafe\"];"
                  for (l, o), nid in objs.items() if l == loc]
        lines.append("}")
    for rid, d in defs.items():
        label = f"{d['owner']}.{d['name']}\\nw={d.get('weight', 1)} delay={d.get('delay', 0)}"
        label += "".join("\\n" + a for a in d["io"]["acts"])
        lines.append(f"{rid} [label={_q(label)}, shape=box, style=\"rounded,filled\", fillcolor=\"#fef3c7\"];")
        for it in d["io"]["inputs"]:
            lines.append(f"{objs[(it['loc'], it['obj'])]} -> {rid} [label={_q(it['n'] if it['n'] > 1 else '')}];")
        for it in d["io"]["outputs"]:
            lines.append(f"{rid} -> {objs[(it['loc'], it['obj'])]} [label={_q(it['n'] if it['n'] > 1 else '')}, color=\"#15803d\"];")
        for it in d["io"]["gates"]:
            rng = f"≥{it['min']}" + (f" ≤{it['max']}" if it["max"] is not None else "")
            lines.append(f"{objs[(it['loc'], it['obj'])]} -> {rid} [style=dashed, color=\"#6b7280\", label={_q(rng)}];")
    lines.append("}")
    return "\n".join(lines)


def rule_warnings(rec: dict) -> pd.DataFrame:
    """Avisos estáticos para revisar el modelo: objetos que se exigen pero nunca existen,
    objetos que se producen pero nada usa, y reglas que no llegaron a aplicarse."""
    frame0 = rec["frames"][0]
    initial = {((rec["membranes"][m]["type"] or m), o) for m, objs in frame0["objects"].items() for o in objs}
    produced = {(i["loc"], i["obj"]) for d in rec["rule_defs"].values() for i in d["io"]["outputs"]}
    used = {(i["loc"], i["obj"]) for d in rec["rule_defs"].values() for i in d["io"]["inputs"] + d["io"]["gates"]}
    rows = []
    for d in rec["rule_defs"].values():
        for it in d["io"]["inputs"] + [g for g in d["io"]["gates"] if g["min"] >= 1]:
            if (it["loc"], it["obj"]) not in initial | produced:
                rows.append({"aviso": "objeto inexistente", "regla": f"{d['owner']}.{d['name']}",
                             "detalle": f"exige {it['obj']} en {it['loc']}, pero nunca existe ni se produce"})
    for loc, obj in sorted(produced - used):
        rows.append({"aviso": "producto sin uso", "regla": "", "detalle": f"{obj} en {loc} se produce pero ninguna regla lo usa"})
    usage = rule_usage_table(rec)
    for r in usage[usage.veces == 0].itertuples():
        rows.append({"aviso": "regla nunca aplicada", "regla": f"{r.tipo}.{r.regla}",
                     "detalle": "no se aplicó en esta simulación (ver pestaña Explicar)"})
    return pd.DataFrame(rows, columns=["aviso", "regla", "detalle"])
