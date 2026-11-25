"""engine.py - Ejecuta el P-sistema paso a paso con MÁXIMO PARALELISMO y RULETA.

Un paso funciona así:
  1. Las membranas se recorren en orden aleatorio.
  2. En cada membrana se repite, hasta que ya no se pueda: mirar qué reglas son aplicables,
     elegir UNA con una ruleta según su `weight`, y aplicarla (= máximo paralelismo: se aplica
     todo lo que se pueda, pero las reglas rivales se reparten los objetos según sus pesos).
     Una regla sin `input` (de "síntesis") se aplica como mucho una vez por paso y membrana.
  3. Los productos (output) aparecen al FINAL del paso `t + delay`. Hasta entonces están
     "en curso" (los objetos consumidos ya no están, los productos aún no han llegado).

Cada aplicación de regla tiene tres piezas, para que sea fácil de leer y depurar:
  _conditions()  generador con TODAS las comprobaciones de una regla (cada una: ok, texto).
                 Es la única fuente de verdad: _plan() para en la primera que falla y explain()
                 las enseña todas.
  _build()       resuelve las referencias y construye el Plan (qué se consume, produce, mueve...).
  _apply()       ejecuta el Plan de forma atómica y anota el evento.
"""
import heapq
import random
from collections import Counter
from dataclasses import dataclass, field

from .model import Membrane, PSystem, Rule
from .refs import resolve

MAX_PARTNER_TRIES = 25       # compañeros que se prueban como máximo por aplicación (ver candidates)
MAX_APPLICATIONS = 100_000   # salvaguarda contra bucles infinitos dentro de un paso


@dataclass
class Plan:
    """Lo que hará una aplicación de regla (todas las referencias ya resueltas)."""
    rule: Rule
    me: Membrane
    partner: Membrane | None = None
    consume: Counter = field(default_factory=Counter)    # (membrana, objeto) -> cantidad
    produce: list = field(default_factory=list)          # (membrana, objeto, cantidad)
    engulf: tuple | None = None                          # (célula, destino)
    dissolve: list = field(default_factory=list)         # membranas a disolver, en orden
    set_charge: list = field(default_factory=list)       # (membrana, 0 | 1 | "flip")
    fate: dict | None = None                             # suceso a registrar


class Simulator:
    def __init__(self, system: PSystem, trace: bool = True):
        self.system = system
        self.rng = random.Random(system.seed)    # seed fija = resultados repetibles
        self.trace = trace                       # guardar en cada evento las condiciones cumplidas
        self.log = []                            # [(paso, [evento, ...])]
        self.fates = []                          # sucesos registrados: [{"t","event","cell","other"}]
        self.pending = []                        # productos en curso: [(paso_de_llegada, membrana, objeto, n)]
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

    def pending_summary(self) -> list[dict]:
        """Productos en curso agrupados: [{"at","obj","n","due"}]."""
        c = Counter()
        for due, m, obj, n in self.pending:
            c[(m.name, obj, due)] += n
        return [{"at": a, "obj": o, "n": n, "due": d} for (a, o, d), n in sorted(c.items())]

    # -------------------------------------------------------- ejecución ---
    def run(self, n_steps: int | None = None) -> None:
        """Ejecuta n pasos (o hasta terminar si n_steps es None)."""
        done = 0
        while not self.finished and (n_steps is None or done < n_steps):
            self.step()
            done += 1

    def step(self) -> list[dict]:
        """Ejecuta un paso y devuelve los eventos (reglas aplicadas, con todo su detalle)."""
        if self.finished:
            return []
        s = self.system
        s.t += 1
        events = {}                                      # (membrana, regla) -> evento
        alive = list(s.membranes.values())
        for m in self.rng.sample(alive, len(alive)):     # orden aleatorio de membranas
            self._run_membrane(m, events)

        arrived = [p for p in self.pending if p[0] <= s.t]          # productos que llegan ahora
        self.pending = [p for p in self.pending if p[0] > s.t]
        for _, m, obj, n in arrived:
            if m.alive:                                  # (si la membrana se disolvió, se pierden)
                m.objects[obj] += n

        # Si no pasó nada, nada está en curso y ninguna regla espera a su 'from_step', se acabó.
        waiting = any(r.condition.from_step > s.t for m in s.membranes.values() for r in m.rules)
        if not events and not waiting and not self.pending:
            s.t -= 1
            self.halted = True
            return []

        result = [self._finish(ev) for ev in events.values()]
        self.log.append((s.t, result))
        return result

    # ------------------------------------------- compañeros (vecindad) ---
    def candidates(self, me: Membrane, rule: Rule) -> list[Membrane]:
        """Posibles compañeros de `me` para una regla con `partner`, en orden de prueba.

        via 'siblings' (por defecto): cualquier hermana del tipo pedido.
        via 'neighbors': solo las vecinas en contacto que siguen vivas y libres como `me`.
        Se prueban como mucho MAX_PARTNER_TRIES, elegidas al azar (uniforme) o con una ruleta
        según la carga del candidato (`charge_weight`; peso 0 = nunca). Con pocas células se
        prueban todas. Para cambiar cómo se define la vecindad basta tocar _pool().
        """
        p = rule.partner
        pool = self._pool(me, rule)
        k = min(len(pool), MAX_PARTNER_TRIES)
        if p.charge_weight is None:
            return self.rng.sample(pool, k)
        # ruleta sin reemplazo: cada candidato recibe la clave u^(1/peso); se toman las k mayores
        keyed = [(self.rng.random() ** (1.0 / w), i, c) for i, c in enumerate(pool)
                 for w in [p.charge_weight.get(c.charge, 1.0)] if w > 0]
        return [c for _, _, c in heapq.nlargest(k, keyed)]

    def _pool(self, me: Membrane, rule: Rule) -> list[Membrane]:
        p = rule.partner
        if p.via == "neighbors":
            return [c for c in me.contacts if c.alive and c.parent is me.parent and c.type == p.type]
        siblings = me.parent.children if me.parent else []
        return [c for c in siblings if c is not me and c.type == p.type]

    # ------------------------------------------------ reglas (privado) ---
    def _run_membrane(self, me: Membrane, events: dict) -> None:
        """Aplica reglas en `me` mientras se pueda, eligiendo con ruleta entre las aplicables."""
        once = set()                                     # reglas de síntesis ya aplicadas en este paso
        for _ in range(MAX_APPLICATIONS):
            if not me.alive:
                return
            options = []
            for rule in me.rules:
                if rule.weight > 0 and rule.name not in once:
                    plan = self._find_plan(me, rule)
                    if plan:
                        options.append(plan)
            if not options:
                return
            plan = self.rng.choices(options, weights=[p.rule.weight for p in options])[0]
            self._apply(plan, events)
            if plan.rule.is_source:
                once.add(plan.rule.name)
        raise RuntimeError(f"Posible bucle infinito en '{me.name}' (más de {MAX_APPLICATIONS} "
                           f"aplicaciones de reglas en un paso)")

    def _find_plan(self, me: Membrane, rule: Rule) -> Plan | None:
        """Busca una forma de aplicar la regla en `me` (probando compañeros si hace falta)."""
        if rule.partner is None:
            return self._plan(me, rule, None)
        for partner in self.candidates(me, rule):
            plan = self._plan(me, rule, partner)
            if plan:
                return plan
        return None

    def _plan(self, me, rule, partner) -> Plan | None:
        for ok, _, _ in self._conditions(me, rule, partner):       # se detiene en la primera que falla
            if not ok:
                return None
        return self._build(me, rule, partner)

    def _conditions(self, me: Membrane, rule: Rule, partner: Membrane | None):
        """Genera (ok, plantilla_de_texto, argumentos) por cada comprobación de la regla."""
        s, c = self.system, rule.condition
        res = lambda ref: resolve(s, ref, me, partner)    # referencia -> membrana (o None)

        # tiempo
        yield s.t >= c.from_step, "t ≥ {} (ahora t={})", (c.from_step, s.t)
        if c.until_step is not None:
            yield s.t <= c.until_step, "t ≤ {} (ahora t={})", (c.until_step, s.t)
        # estructura
        if c.free:
            yield me.parent is s.skin, "{} es una célula libre (hija directa del medio)", (me.name,)
        for ref in c.empty:
            m = res(ref)
            yield m is not None and not m.children, "{} no contiene células", (ref,)
        # umbrales de objetos
        for need in c.needs:
            m = res(need.at)
            n = m.objects[need.obj] if m else None
            ok = m is not None and n >= need.min and (need.max is None or n <= need.max)
            rango = f"≥ {need.min}" + (f" y ≤ {need.max}" if need.max is not None else "")
            yield ok, "{}.{} {} (hay {})", (need.at, need.obj, rango, n)
        # carga
        for chk in c.charge:
            m = res(chk.at)
            yield (m is not None and m.charge in chk.values), "carga de {} ∈ {} (es {})", \
                (chk.at, chk.values, m.charge if m else None)
        # objetos a consumir: deben existir TODOS
        need_counts = Counter()
        for item in rule.inputs:
            m = res(item.at)
            if m is None:
                yield False, "existe la membrana {} (input {})", (item.at, item.obj)
            else:
                need_counts[(m, item.obj)] += item.number
        for (m, obj), n in need_counts.items():
            yield m.objects[obj] >= n, "input: {} × {} en {} (hay {})", (n, obj, m.name, m.objects[obj])
        # destinos de los productos
        for item in rule.outputs:
            yield res(item.at) is not None, "existe la membrana destino {} (output {})", (item.at, item.obj)
        # engulf: sin ciclos y sin mover a donde ya está
        if rule.engulf:
            cell, dest = res(rule.engulf.cell), res(rule.engulf.into)
            yield cell is not None and dest is not None, "existen {} y {} (engulf)", (rule.engulf.cell, rule.engulf.into)
            if cell is not None and dest is not None:
                yield dest is not cell.parent and not s.is_inside(dest, cell), \
                    "{} puede entrar en {} (no está ya ahí ni habría ciclo)", (cell.name, dest.name)
        # disolución y carga
        for ref in rule.dissolve:
            m = res(ref)
            yield m is not None and m is not s.skin, "{} existe y se puede disolver", (ref,)
        for sc in rule.set_charge:
            yield res(sc.at) is not None, "existe la membrana {} (set_charge)", (sc.at,)

    def _build(self, me: Membrane, rule: Rule, partner: Membrane | None) -> Plan:
        """Construye el Plan (las condiciones ya se han comprobado, así que todo se resuelve)."""
        res = lambda ref: resolve(self.system, ref, me, partner)
        plan = Plan(rule, me, partner)
        for item in rule.inputs:
            plan.consume[(res(item.at), item.obj)] += item.number
        plan.produce = [(res(i.at), i.obj, i.number) for i in rule.outputs]
        if rule.engulf:
            plan.engulf = (res(rule.engulf.cell), res(rule.engulf.into))
        plan.dissolve = [res(r) for r in rule.dissolve]
        plan.set_charge = [(res(sc.at), sc.to) for sc in rule.set_charge]
        if rule.record:                                   # nombres fijados ahora, antes de que algo desaparezca
            cell = res(rule.record.cell)
            other = res(rule.record.other) if rule.record.other else None
            plan.fate = {"event": rule.record.event,
                         "cell": cell.name if cell else None, "other": other.name if other else None}
        return plan

    def _apply(self, plan: Plan, events: dict) -> None:
        s, rule = self.system, plan.rule
        ev = events.setdefault((plan.me.name, rule.name), {
            "membrane": plan.me.name, "rule": rule.name, "times": 0, "consumed": Counter(),
            "produced": Counter(), "actions": [], "partners": [], "checks": None})
        ev["times"] += 1
        if self.trace and ev["checks"] is None:           # condiciones cumplidas (de la 1ª aplicación)
            ev["checks"] = [fmt.format(*args) for _, fmt, args in self._conditions(plan.me, rule, plan.partner)]
        if plan.partner:
            ev["partners"].append(plan.partner.name)

        for (m, obj), n in plan.consume.items():          # 1) consumir
            m.objects[obj] -= n
            if m.objects[obj] == 0:
                del m.objects[obj]
            ev["consumed"][(m.name, obj)] += n
        due = s.t + rule.delay                            # 2) producir (llegan al final del paso `due`)
        for m, obj, n in plan.produce:
            self.pending.append((due, m, obj, n))
            ev["produced"][(m.name, obj, due)] += n
        if plan.engulf:                                   # 3) estructura
            cell, dest = plan.engulf
            s.move_membrane(cell, dest)
            ev["actions"].append(f"engulf {cell.name} → {dest.name}")
        for m in plan.dissolve:
            if m.alive:
                s.dissolve_membrane(m)
                ev["actions"].append(f"disuelve {m.name}")
        for m, to in plan.set_charge:                     # 4) carga
            old, m.charge = m.charge, (1 - m.charge if to == "flip" else to)
            ev["actions"].append(f"carga de {m.name}: {old} → {m.charge}")
        if plan.fate:                                     # 5) registro
            self.fates.append({"t": s.t, **plan.fate})

    @staticmethod
    def _finish(ev: dict) -> dict:
        """Convierte un evento acumulado en un dict serializable."""
        return {"membrane": ev["membrane"], "rule": ev["rule"], "times": ev["times"],
                "consumed": [{"at": a, "obj": o, "n": n} for (a, o), n in sorted(ev["consumed"].items())],
                "produced": [{"at": a, "obj": o, "n": n, "due": d} for (a, o, d), n in sorted(ev["produced"].items())],
                "actions": ev["actions"], "partners": ev["partners"], "checks": ev["checks"] or []}

    # ---------------------------------------------------- depuración ---
    def explain(self, me: Membrane, rule: Rule) -> list[tuple[str, list]]:
        """¿Por qué (no) se aplicaría `rule` en `me` AHORA? Devuelve escenarios:
        [(etiqueta, [(ok, texto), ...])]. Con compañero: un escenario por candidato (hasta 8)."""
        def run(partner):
            return [(ok, fmt.format(*args)) for ok, fmt, args in self._conditions(me, rule, partner)]
        if rule.partner is None:
            return [("", run(None))]
        pool = self._pool(me, rule)
        if not pool:
            return [("sin compañeros posibles (ningún candidato del tipo pedido)", [])]
        return [(f"compañero {c.name}", run(c)) for c in pool[:8]]

    def options(self, me: Membrane) -> list[tuple[str, float]]:
        """Reglas aplicables ahora en `me` con su peso: lo que competiría en la ruleta."""
        return [(r.name, r.weight) for r in me.rules if r.weight > 0 and self._find_plan(me, r)]
