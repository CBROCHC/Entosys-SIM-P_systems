"""transducer.py - Traduce el YAML a objetos de model.py.

Pasos de parse_text():
  1. Leer los TIPOS de membrana (plantillas: objetos, hijos, reglas).
  2. Crear las membranas: las sueltas de `membranes:` y las de `population:` (se expanden
     N copias de un tipo, cada una con sus hijos; p. ej. una célula con su vacuola).
  3. Enlazar padres e hijos y comprobar la estructura.
  4. Crear las reglas (una vez por tipo; las comparten todas sus instancias).
Si el YAML tiene algún error se lanza ValueError con un mensaje claro.
"""
import random
from collections import Counter
from dataclasses import dataclass, field

import yaml

from .model import (Condition, Engulf, Item, Membrane, Need, PSystem, Record, Rule)
from .refs import check_ref


def load_system(path: str) -> PSystem:
    with open(path, encoding="utf-8") as f:
        return parse_text(f.read())


@dataclass
class _TypeDef:                       # una plantilla de membrana (solo se usa aquí dentro)
    name: str
    objects: Counter = field(default_factory=Counter)
    children: list = field(default_factory=list)      # nombres de tipos hijos
    raw_rules: dict = field(default_factory=dict)
    rules: list = field(default_factory=list)         # se rellena en el paso 4


def parse_text(text: str) -> PSystem:
    data = yaml.safe_load(text)
    if not data or "system" not in data:
        raise ValueError("El YAML debe empezar con la clave 'system:'")
    sd = data["system"]

    # 1) tipos ---------------------------------------------------------
    types = {}
    for tname, td in (sd.get("types") or {}).items():
        types[_name(tname)] = _TypeDef(_name(tname), _objects(td.get("objects")),
                                       [_name(c) for c in td.get("children") or []],
                                       td.get("rules") or {})
    for t in types.values():
        for c in t.children:
            if c not in types:
                raise ValueError(f"El tipo '{t.name}' tiene un hijo de tipo desconocido: '{c}'")

    # 2) membranas -----------------------------------------------------
    membranes, parent_of, own_rules = {}, {}, {}
    for md in sd.get("membranes") or []:                       # membranas sueltas (p. ej. el medio)
        name = _name(md["name"])
        _add(membranes, Membrane(name, None, _objects(md.get("objects"))))
        parent_of[name] = md.get("parent")
        own_rules[name] = md.get("rules") or {}

    rng = random.Random(sd.get("seed"))                        # para la variabilidad inicial
    vary_on = bool(sd.get("variability", False))               # desactivada por defecto
    for pd in sd.get("population") or []:
        ttype = _name(pd["type"])
        if ttype not in types:
            raise ValueError(f"population: tipo desconocido '{ttype}'")
        prefix = pd.get("prefix", ttype + "_")
        for i in range(1, pd.get("count", 1) + 1):
            _instantiate(types, ttype, f"{prefix}{i}", pd["parent"], membranes, parent_of,
                         pd.get("variability") if vary_on else None, rng)

    # 3) estructura ----------------------------------------------------
    for name, parent_name in parent_of.items():
        if parent_name is not None:
            parent = _get(membranes, parent_name, f"padre de '{name}'")
            membranes[name].parent = parent
            parent.children.append(membranes[name])
    skins = [m for m in membranes.values() if m.parent is None]
    if len(skins) != 1:
        raise ValueError(f"Debe haber exactamente 1 membrana sin 'parent' (el medio); hay {len(skins)}")
    for m in membranes.values():
        _check_reaches_skin(m, len(membranes))

    # 4) reglas --------------------------------------------------------
    names = set(membranes)
    for t in types.values():
        t.rules = [_parse_rule(rn, rd, set(types), names) for rn, rd in t.raw_rules.items()]
    for m in membranes.values():
        if m.type is not None:
            m.rules = types[m.type].rules                      # compartidas por todas las instancias
        else:
            m.rules = [_parse_rule(rn, rd, set(types), names) for rn, rd in own_rules[m.name].items()]

    return PSystem(sd.get("name", "sin_nombre"), membranes,
                   max_steps=sd.get("max_steps", 50), seed=sd.get("seed"))


# ------------------------------------------------------ población ---
def _instantiate(types, tname, name, parent_name, membranes, parent_of, vary, rng):
    """Crea una membrana de tipo `tname` y, recursivamente, sus hijos (p. ej. su vacuola)."""
    t = types[tname]
    objects = Counter(t.objects)
    for obj, rng_ in (vary or {}).items():                     # variabilidad: objeto -> [mín, máx]
        lo, hi = rng_
        objects[_name(obj)] = rng.randint(lo, hi)
    _add(membranes, Membrane(name, tname, +objects))           # +objects quita los ceros
    parent_of[name] = parent_name
    for child_type in t.children:
        _instantiate(types, child_type, f"{name}_{child_type}", name, membranes, parent_of, None, rng)


# --------------------------------------------------------- reglas ---
def _parse_rule(name, rd, type_names, membrane_names) -> Rule:
    partner = rd.get("partner")
    if partner is not None and partner not in type_names:
        raise ValueError(f"Regla '{name}': partner de tipo desconocido '{partner}'")
    ok = lambda ref: _checked(ref, name, type_names, membrane_names, partner is not None)

    inputs = [Item(_name(i["object"]), i.get("number", 1), ok(i.get("at", "self")))
              for i in rd.get("input") or []]
    outputs = [Item(_name(i["object"]), i.get("number", 1), ok(i.get("at", i.get("target", "self"))))
               for i in rd.get("output") or []]
    engulf = Engulf(ok(rd["engulf"]["cell"]), ok(rd["engulf"]["into"])) if "engulf" in rd else None
    dissolve = [ok(r) for r in _as_list(rd.get("dissolve"))]
    record = None
    if "record" in rd:
        rec = rd["record"]
        record = Record(str(rec["event"]), ok(rec["cell"]), ok(rec["other"]) if "other" in rec else None)
    if not (inputs or engulf or dissolve):
        raise ValueError(f"La regla '{name}' no tiene 'input', 'engulf' ni 'dissolve'")

    cd = rd.get("condition") or {}
    needs = []
    for nd in _as_list(cd.get("needs")):
        at = nd.get("at", nd.get("membrane"))                  # 'membrane' = nombre antiguo de 'at'
        needs.append(Need(ok(at), _name(nd["object"]), nd.get("min", nd.get("number", 1)), nd.get("max")))
    condition = Condition(cd.get("from_step", 1), cd.get("until_step"), needs,
                          bool(cd.get("free", False)), [ok(r) for r in _as_list(cd.get("empty"))])
    return Rule(name, inputs, outputs, engulf, dissolve, record, partner, condition)


def _checked(ref, rule_name, type_names, membrane_names, has_partner):
    try:
        check_ref(ref, type_names, membrane_names, has_partner)
    except ValueError as e:
        raise ValueError(f"Regla '{rule_name}': {e}") from None
    return ref


# ------------------------------------------------------ utilidades ---
def _objects(d) -> Counter:
    return Counter({_name(o): n for o, n in (d or {}).items() if n})


def _as_list(x) -> list:
    return [] if x is None else (x if isinstance(x, list) else [x])


def _name(x) -> str:
    # PyYAML convierte y/n/yes/no/on/off en True/False: lo avisamos.
    if isinstance(x, bool):
        raise ValueError("Un nombre se leyó como True/False (¿usaste y, n, yes, no, on u off?). "
                         "Ponlo entre comillas, por ejemplo: 'n'")
    return str(x)


def _add(membranes, m):
    if m.name in membranes:
        raise ValueError(f"Membrana repetida: '{m.name}'")
    membranes[m.name] = m


def _get(membranes, name, where):
    if name not in membranes:
        raise ValueError(f"Membrana desconocida '{name}' en {where}")
    return membranes[name]


def _check_reaches_skin(membrane, total):
    for _ in range(total):
        if membrane.parent is None:
            return
        membrane = membrane.parent
    raise ValueError("Hay un ciclo en los 'parent' de las membranas")
