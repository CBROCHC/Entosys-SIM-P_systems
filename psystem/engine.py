"""engine.py - Ejecuta el P-sistema paso a paso con MÁXIMO PARALELISMO.

Un paso funciona así:
  1. Se barajan todos los pares (membrana, regla). El orden aleatorio decide quién gana
     cuando varias reglas compiten por los mismos objetos o por el mismo compañero.
  2. Cada regla se aplica TODAS las veces que pueda (= máximo paralelismo).
     Consumir objetos, mover membranas y disolver ocurren en el momento.
  3. Los productos (output) se añaden al FINAL del paso: no se pueden usar hasta el siguiente.

Cada aplicación de regla tiene dos fases, para que sea fácil de leer y depurar:
  _plan()   comprueba TODO sin cambiar nada (condiciones, objetos, referencias) y devuelve
            un Plan con lo que habría que hacer, o None si la regla no se puede aplicar.
  _apply()  ejecuta el Plan: es atómico (o se hace todo, o nada).
"""
import random
from collections import Counter
from dataclasses import dataclass, field

from .model import Membrane, PSystem, Rule
from .refs import resolve


MAX_PARTNER_TRIES = 25       # compañeros que se prueban como máximo por aplicación (ver candidates)


@dataclass
class Plan:
    """Lo que hará una aplicación de regla (todas las referencias ya resueltas)."""
    consume: Counter = field(default_factory=Counter)    # (membrana, objeto) -> cantidad
    produce: list = field(default_factory=list)          # (membrana, objeto, cantidad)
    engulf: tuple | None = None                          # (célula, destino)
    dissolve: list = field(default_factory=list)         # membranas a disolver, en orden
    fate: dict | None = None                             # suceso a registrar


class Simulator:
    def __init__(self, system: PSystem):
        self.system = system
        self.rng = random.Random(system.seed)    # seed fija = resultados repetibles
        self.log = []                            # [(paso, [{"membrane","rule","times"}])]
        self.fates = []                          # sucesos registrados: [{"t","event","cell","other"}]
        self.halted = False

    # --------------------------------------------------------- estado ---
    @property
    def finished(self) -> bool:
        return self.halted or self.system.t >= self.system.max_steps

    def status(self) -> str:
        if self.halted:
            return "detenida (ninguna regla aplicable)"
        if self.finished:
            return "máximo de pasos alcanzado"
        return "en curso"

    def fate_counts(self) -> dict:
        """Cuántas veces ocurrió cada suceso registrado (internalization, escape...)."""
        return dict(Counter(f["event"] for f in self.fates))

    # -------------------------------------------------------- ejecución ---
    def run(self, n_steps: int | None = None) -> None:
        """Ejecuta n pasos (o hasta terminar si n_steps es None)."""
        done = 0
        while not self.finished and (n_steps is None or done < n_steps):
            self.step()
            done += 1

    def step(self) -> list[dict]:
        """Ejecuta un paso y devuelve las reglas aplicadas: [{"membrane","rule","times"}]."""
        if self.finished:
            return []
        s = self.system
        s.t += 1
        applied = Counter()      # (membrana, regla) -> nº de veces aplicada
        produced = []            # productos pendientes hasta el final del paso

        pairs = [(m, r) for m in list(s.membranes.values()) for r in m.rules]
        self.rng.shuffle(pairs)
        for membrane, rule in pairs:
            while membrane.alive:                         # máximo paralelismo: repetir mientras se pueda
                plan = self._find_plan(membrane, rule)
                if plan is None:
                    break
                self._apply(plan, produced)
                applied[(membrane.name, rule.name)] += 1

        for m, obj, n in produced:                        # productos: al final del paso
            if m.alive:                                   # (si la membrana se disolvió, se pierden)
                m.objects[obj] += n

        # Si no pasó nada y ninguna regla está esperando a su 'from_step', se acabó.
        waiting = any(r.condition.from_step > s.t for m in s.membranes.values() for r in m.rules)
        if not applied and not waiting:
            s.t -= 1
            self.halted = True
            return []

        events = [{"membrane": m, "rule": r, "times": n} for (m, r), n in applied.items()]
        self.log.append((s.t, events))
        return events

    # ------------------------------------------- compañeros (vecindad) ---
    def candidates(self, me: Membrane, rule: Rule) -> list[Membrane]:
        """Posibles compañeros de `me` para una regla con `partner: <Tipo>`.

        AHORA: cualquier hermano del tipo pedido (todas las células del medio son vecinas).
        MÁS ADELANTE (vecindad, como en los sistemas P tisulares): sustituir solo esta
        función para devolver únicamente las células en contacto con `me`.
        """
        if me.parent is None:
            return []
        found = [c for c in me.parent.children if c is not me and c.type == rule.partner]
        # Se prueban como mucho MAX_PARTNER_TRIES al azar: con poblaciones grandes evita revisar
        # a todas las células por cada invasor (con pocas células se prueban todas, sin pérdida).
        return self.rng.sample(found, min(len(found), MAX_PARTNER_TRIES))

    # ------------------------------------------------ reglas (privado) ---
    def _find_plan(self, me: Membrane, rule: Rule) -> Plan | None:
        """Busca una forma de aplicar la regla en `me` (probando compañeros si hace falta)."""
        if rule.partner is None:
            return self._plan(me, rule, None)
        for partner in self.candidates(me, rule):
            plan = self._plan(me, rule, partner)
            if plan:
                return plan
        return None

    def _plan(self, me: Membrane, rule: Rule, partner: Membrane | None) -> Plan | None:
        s, c = self.system, rule.condition
        res = lambda ref: resolve(s, ref, me, partner)    # referencia -> membrana (o None)

        # 1) tiempo
        if s.t < c.from_step or (c.until_step is not None and s.t > c.until_step):
            return None
        # 2) estructura: célula libre y membranas sin células dentro
        if c.free and me.parent is not s.skin:
            return None
        for ref in c.empty:
            m = res(ref)
            if m is None or m.children:
                return None
        # 3) umbrales de objetos
        for need in c.needs:
            m = res(need.at)
            if m is None:
                return None
            n = m.objects[need.obj]
            if n < need.min or (need.max is not None and n > need.max):
                return None

        plan = Plan()
        # 4) objetos que hay que consumir: deben existir TODOS
        for item in rule.inputs:
            m = res(item.at)
            if m is None:
                return None
            plan.consume[(m, item.obj)] += item.number
        if any(m.objects[o] < n for (m, o), n in plan.consume.items()):
            return None
        # 5) productos
        for item in rule.outputs:
            m = res(item.at)
            if m is None:
                return None
            plan.produce.append((m, item.obj, item.number))
        # 6) engulf: mover una membrana dentro de otra (sin ciclos y sin mover a donde ya está)
        if rule.engulf:
            cell, dest = res(rule.engulf.cell), res(rule.engulf.into)
            if cell is None or dest is None or dest is cell.parent or s.is_inside(dest, cell):
                return None
            plan.engulf = (cell, dest)
        # 7) disolución
        for ref in rule.dissolve:
            m = res(ref)
            if m is None or m is s.skin:
                return None
            plan.dissolve.append(m)
        # 8) registro del suceso (los nombres se fijan ahora, antes de que algo desaparezca)
        if rule.record:
            cell = res(rule.record.cell)
            other = res(rule.record.other) if rule.record.other else None
            plan.fate = {"event": rule.record.event,
                         "cell": cell.name if cell else None, "other": other.name if other else None}
        return plan

    def _apply(self, plan: Plan, produced: list) -> None:
        s = self.system
        for (m, obj), n in plan.consume.items():          # consumir
            m.objects[obj] -= n
            if m.objects[obj] == 0:
                del m.objects[obj]
        produced.extend(plan.produce)                     # producir (al final del paso)
        if plan.engulf:
            s.move_membrane(*plan.engulf)
        for m in plan.dissolve:
            if m.alive:
                s.dissolve_membrane(m)
        if plan.fate:
            self.fates.append({"t": s.t, **plan.fate})
