"""explain.py - "¿Por qué se aplicó (o no) esta regla en este paso?"

Reconstruye el estado del sistema al INICIO de un paso a partir de la grabación (que incluye el
YAML, los parámetros y la semilla) y vuelve a evaluar las condiciones de la regla con el
mismo código del motor (Simulator.explain). Así la explicación nunca puede contradecir al motor.
"""
from collections import Counter

from psystem import Simulator, parse_text
from psystem.model import link


def restore(rec: dict, frame_index: int) -> Simulator:
    """Devuelve un Simulator cuyo estado es el del frame `frame_index` (final de ese paso)."""
    if not rec.get("yaml"):
        raise ValueError("Esta grabación no incluye el YAML: no se puede reconstruir el estado.")
    sim = Simulator(parse_text(rec["yaml"], rec.get("params") or {}, rec["seed"]))
    s, frame = sim.system, rec["frames"][frame_index]
    for name in [n for n in s.membranes if n not in frame["parents"]]:     # las ya disueltas
        s.membranes.pop(name).alive = False
    for m in s.membranes.values():
        m.children, m.contacts = [], []
    for name, parent in frame["parents"].items():                         # estructura
        m = s.membranes[name]
        m.parent = s.membranes[parent] if parent else None
        if parent:
            m.parent.children.append(m)
    for name, m in s.membranes.items():                                   # contenido y carga
        m.objects = Counter(frame["objects"].get(name, {}))
        m.charge = frame.get("charges", {}).get(name, 0)
    for a, b, t0 in rec.get("links", []):                                 # vecindad en ese momento
        if t0 <= frame_index and a in s.membranes and b in s.membranes:
            link(s.membranes[a], s.membranes[b])
    s.t = frame["t"]
    return sim


def explain_at(rec: dict, step: int, membrane: str, rule_name: str) -> dict:
    """Evalúa la regla en `membrane` al inicio del paso `step` (1 = primer paso)."""
    sim = restore(rec, step - 1)
    sim.system.t = step                                                   # las condiciones usan el t del paso
    me = sim.system.membranes[membrane]
    rule = next(r for r in me.rules if r.name == rule_name)
    applied = 0
    if step < len(rec["frames"]):
        applied = sum(e["times"] for e in rec["frames"][step]["events"]
                      if e["membrane"] == membrane and e["rule"] == rule_name)
    return {"scenarios": sim.explain(me, rule), "options": sim.options(me), "weight": rule.weight,
            "delay": rule.delay, "applied_times": applied, "rule_has_partner": rule.partner is not None,
            "rules": [r.name for r in me.rules]}
