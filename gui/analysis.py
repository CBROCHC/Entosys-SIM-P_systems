"""analysis.py - Tablas de análisis (pandas) calculadas a partir de una GRABACIÓN (dict).

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
    parents, objects = frame["parents"], frame["objects"]
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
def events_table(rec: dict) -> pd.DataFrame:
    rows = [{"paso": f["t"], "membrana": e["membrane"], "regla": e["rule"], "veces": e["times"]}
            for f in rec["frames"] for e in f["events"]]
    return pd.DataFrame(rows, columns=["paso", "membrana", "regla", "veces"])


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
        rows.append({"tipo": d["owner"], "regla": d["name"], "veces": u["veces"],
                     "membranas_distintas": len(u["membranas"]),
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
        rows.append({"regla": d["name"], "veces": int(sub.veces.sum()),
                     "primer_paso": int(sub.paso.min()) if len(sub) else None, "condicion": d["cond"] or "—"})
    return pd.DataFrame(rows, columns=["regla", "veces", "primer_paso", "condicion"])


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
