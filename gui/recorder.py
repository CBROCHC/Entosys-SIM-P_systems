"""recorder.py - Graba la simulación paso a paso, SIN tocar el motor.

El motor solo conoce el estado actual. Para poder repetir la "película" (qué membrana
está dentro de cuál, en cada paso) el Recorder envuelve al Simulator y, tras cada paso,
hace una "foto" (frame):
    t        paso
    parents  {membrana: padre}   solo las membranas que EXISTEN en ese paso
    objects  {membrana: {objeto: cantidad}}
    events   reglas aplicadas en ese paso: [{membrane, rule, times}]
    fates    sucesos registrados en ese paso: [{event, cell, other}]
La grabación completa es un dict JSON-able: alimenta el visor, las tablas y se puede guardar.
"""
from psystem import Simulator
from psystem.model import Item, Rule


class Recorder:
    def __init__(self, sim: Simulator):
        self.sim = sim
        self.frames = []
        self.membranes = {}          # todas las membranas que han existido: nombre -> {"type", "rules"}
        self.rule_defs = {}          # id de regla -> descripción (las reglas se comparten entre instancias)
        self._rule_ids = {}          # id() del objeto Rule -> id de regla
        self._rules_keep = []        # (para que los id() no se reutilicen)
        self._n_fates = 0            # cuántos sucesos del motor ya hemos copiado
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
            "name": s.name,
            "max_steps": s.max_steps,
            "seed": s.seed,
            "status": self.sim.status(),
            "fate_counts": self.sim.fate_counts(),
            "rule_defs": self.rule_defs,
            "membranes": self.membranes,
            "frames": self.frames,
        }

    # ------------------------------------------------------ privado ---
    def _snapshot(self, events: list[dict]) -> None:
        s = self.sim.system
        for m in s.membranes.values():                       # registrar membranas nuevas
            if m.name not in self.membranes:
                self.membranes[m.name] = {"type": m.type, "rules": [self._rule_id(r, m) for r in m.rules]}
        new_fates = self.sim.fates[self._n_fates:]
        self._n_fates = len(self.sim.fates)
        self.frames.append({
            "t": s.t,
            "parents": {m.name: (m.parent.name if m.parent else None) for m in s.membranes.values()},
            "objects": {m.name: dict(m.objects) for m in s.membranes.values() if m.objects},
            "events": events,
            "fates": [{k: f[k] for k in ("event", "cell", "other")} for f in new_fates],
        })

    def _rule_id(self, rule: Rule, owner) -> str:
        key = id(rule)
        if key not in self._rule_ids:
            self._rule_ids[key] = f"r{len(self._rule_ids)}"
            self._rules_keep.append(rule)
            self.rule_defs[self._rule_ids[key]] = {**describe_rule(rule), "owner": owner.type or owner.name}
        return self._rule_ids[key]


def _item(i: Item) -> str:
    return f"{i.number} {i.obj}" + (f" @{i.at}" if i.at != "self" else "")


def describe_rule(rule: Rule) -> dict:
    """Texto legible de una regla: {name, text, cond}."""
    text = (" + ".join(_item(i) for i in rule.inputs) or "∅") + "  ⟶  " + (" + ".join(_item(o) for o in rule.outputs) or "∅")
    if rule.engulf:
        text += f"   | engulf: {rule.engulf.cell} → {rule.engulf.into}"
    if rule.dissolve:
        text += "   | disuelve: " + ", ".join(rule.dissolve)
    if rule.record:
        text += f"   | registra: {rule.record.event}"
    c, cond = rule.condition, []
    if rule.partner:
        cond.append(f"hay un compañero ({rule.partner}, al azar)")
    if c.from_step > 1:
        cond.append(f"t ≥ {c.from_step}")
    if c.until_step is not None:
        cond.append(f"t ≤ {c.until_step}")
    if c.free:
        cond.append("self es célula libre")
    cond += [f"{n.at}.{n.obj} ≥ {n.min}" + (f" y ≤ {n.max}" if n.max is not None else "") for n in c.needs]
    cond += [f"{e} sin células dentro" for e in c.empty]
    return {"name": rule.name, "text": text, "cond": " · ".join(cond)}
