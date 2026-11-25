"""recorder.py - Graba la simulación paso a paso, SIN tocar el motor.

El motor solo conoce el estado actual. Para poder repetir la "película" (qué membrana
está dentro de cuál, en cada paso) el Recorder envuelve al Simulator y, tras cada paso,
hace una "foto" (frame):
    t        paso
    parents  {membrana: padre}   solo las membranas que EXISTEN en ese paso
    objects  {membrana: {objeto: cantidad}}
    charges  {membrana: carga}   solo las de carga 1 (el resto es 0)
    pending  productos en curso (retardos): [{at, obj, n, due}]
    events   reglas aplicadas en ese paso, con todo su detalle (qué consumieron, produjeron,
             compañero, acciones y condiciones cumplidas)
    fates    sucesos registrados en ese paso: [{event, cell, other}]
La grabación completa es un dict JSON-able y AUTOCONTENIDO (incluye el YAML, los parámetros y
la semilla): alimenta el visor, las tablas y la reconstrucción de estados para "explicar".
"""
from psystem import Simulator
from psystem.model import Item, Rule


class Recorder:
    def __init__(self, sim: Simulator, yaml_text: str | None = None, params: dict | None = None):
        self.sim = sim
        self.yaml_text, self.params = yaml_text, params or {}
        self.frames = []
        self.membranes = {}          # todas las membranas que han existido: nombre -> {"type", "rules"}
        self.rule_defs = {}          # id de regla -> descripción (las reglas se comparten entre instancias)
        self.links = {}              # (a, b) -> primer paso en el que son vecinas
        self._rule_ids = {}          # id() del objeto Rule -> id de regla
        self._rules_keep = []        # (para que los id() no se reutilicen)
        self._n_fates = 0            # cuántos sucesos del motor ya hemos copiado
        s = sim.system
        self.layout = {m.name: list(m.pos) for m in s.membranes.values() if m.pos is not None}
        self.type_parents = {}       # tipo (o nombre) -> tipo (o nombre) de su padre; para el mapa de reglas
        for m in s.membranes.values():
            self.type_parents.setdefault(m.type or m.name, (m.parent.type or m.parent.name) if m.parent else None)
        self.names = set(s.membranes)
        self._snapshot([])           # frame t = 0 (estado inicial)

    def step(self) -> None:
        t_before = self.sim.system.t
        events = self.sim.step()
        if self.sim.system.t > t_before:        # si el motor se detuvo, no hay frame nuevo
            self._snapshot(events)

    def run(self, n_steps: int | None = None) -> None:
        done = 0
        while not self.sim.finished and (n_steps is None or done < n_steps):
            self.step()
            done += 1

    def to_dict(self) -> dict:
        s = self.sim.system
        return {
            "name": s.name, "max_steps": s.max_steps, "seed": s.seed,
            "yaml": self.yaml_text, "params": self.params,
            "status": self.sim.status(), "fate_counts": self.sim.fate_counts(),
            "rule_defs": self.rule_defs, "membranes": self.membranes,
            "layout": self.layout, "links": [[a, b, t] for (a, b), t in self.links.items()],
            "frames": self.frames,
        }

    # ------------------------------------------------------ privado ---
    def _snapshot(self, events: list[dict]) -> None:
        s = self.sim.system
        for m in s.membranes.values():                       # registrar membranas nuevas
            if m.name not in self.membranes:
                self.membranes[m.name] = {"type": m.type, "rules": [self._rule_id(r, m) for r in m.rules]}
            if s.neighborhood:                               # registrar enlaces nuevos
                for c in m.contacts:
                    self.links.setdefault(tuple(sorted((m.name, c.name))), s.t)
        new_fates = self.sim.fates[self._n_fates:]
        self._n_fates = len(self.sim.fates)
        self.frames.append({
            "t": s.t,
            "parents": {m.name: (m.parent.name if m.parent else None) for m in s.membranes.values()},
            "objects": {m.name: dict(m.objects) for m in s.membranes.values() if m.objects},
            "charges": {m.name: m.charge for m in s.membranes.values() if m.charge},
            "pending": self.sim.pending_summary(),
            "events": events,
            "fates": [{k: f[k] for k in ("event", "cell", "other")} for f in new_fates],
        })

    def _rule_id(self, rule: Rule, owner) -> str:
        key = id(rule)
        if key not in self._rule_ids:
            self._rule_ids[key] = f"r{len(self._rule_ids)}"
            self._rules_keep.append(rule)
            owner_key = owner.type or owner.name
            self.rule_defs[self._rule_ids[key]] = {
                **describe_rule(rule), "owner": owner_key,
                "io": rule_io(rule, owner_key, self.type_parents, self.names)}
        return self._rule_ids[key]


# ------------------------------------------------- descripción de reglas ---
def _item(i: Item) -> str:
    return f"{i.number} {i.obj}" + (f" @{i.at}" if i.at != "self" else "")


def describe_rule(rule: Rule) -> dict:
    """Texto legible de una regla: {name, text, cond, weight, delay}."""
    text = (" + ".join(_item(i) for i in rule.inputs) or "∅") + "  ⟶  " + (" + ".join(_item(o) for o in rule.outputs) or "∅")
    if rule.engulf:
        text += f"   | engulf: {rule.engulf.cell} → {rule.engulf.into}"
    if rule.dissolve:
        text += "   | disuelve: " + ", ".join(rule.dissolve)
    if rule.set_charge:
        text += "   | carga: " + ", ".join(f"{c.at}→{c.to}" for c in rule.set_charge)
    if rule.record:
        text += f"   | registra: {rule.record.event}"
    c, cond = rule.condition, []
    if rule.partner:
        p = rule.partner
        cond.append(f"hay un compañero ({p.type}, {'vecino' if p.via == 'neighbors' else 'cualquiera'}"
                    + (f", pesos por carga {p.charge_weight}" if p.charge_weight else ", al azar") + ")")
    if c.from_step > 1:
        cond.append(f"t ≥ {c.from_step}")
    if c.until_step is not None:
        cond.append(f"t ≤ {c.until_step}")
    if c.free:
        cond.append("self es célula libre")
    cond += [f"{n.at}.{n.obj} ≥ {n.min}" + (f" y ≤ {n.max}" if n.max is not None else "") for n in c.needs]
    cond += [f"carga de {k.at} ∈ {k.values}" for k in c.charge]
    cond += [f"{e} sin células dentro" for e in c.empty]
    return {"name": rule.name, "text": text, "cond": " · ".join(cond), "weight": rule.weight, "delay": rule.delay}


def symbolic(ref: str, owner: str, partner_type: str | None, type_parents: dict, names: set) -> str:
    """Resuelve una referencia a un TIPO (o nombre de membrana) sin simular: 'parent' de Vacuole -> 'Cell'."""
    steps = ref.split(".")
    first = steps[0]
    if first == "self":
        cur, steps = owner, steps[1:]
    elif first == "partner":
        cur, steps = partner_type or "partner", steps[1:]
    elif first in names:
        cur, steps = first, steps[1:]
    else:
        cur = owner
    for step in steps:
        if step == "parent":
            cur = type_parents.get(cur) or "?"
        elif step.startswith("child:"):
            cur = step[len("child:"):]
    return cur


def rule_io(rule: Rule, owner: str, type_parents: dict, names: set) -> dict:
    """Estructura de una regla para el mapa de dependencias: dónde (tipo) y qué objetos lee/escribe."""
    pt = rule.partner.type if rule.partner else None
    loc = lambda ref: symbolic(ref, owner, pt, type_parents, names)
    return {
        "inputs": [{"loc": loc(i.at), "obj": i.obj, "n": i.number} for i in rule.inputs],
        "outputs": [{"loc": loc(o.at), "obj": o.obj, "n": o.number} for o in rule.outputs],
        "gates": [{"loc": loc(n.at), "obj": n.obj, "min": n.min, "max": n.max} for n in rule.condition.needs],
        "acts": ([f"engulf → {loc(rule.engulf.into)}"] if rule.engulf else [])
                + [f"disuelve {loc(r)}" for r in rule.dissolve]
                + [f"carga {loc(c.at)}→{c.to}" for c in rule.set_charge]
                + ([f"registra {rule.record.event}"] if rule.record else []),
    }
