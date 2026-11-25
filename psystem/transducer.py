"""transducer.py - Traduce el YAML a objetos de model.py.

Pasos de parse_text():
  0. Parámetros: se sustituyen los ${nombre} del texto por su valor (bloque `params:`).
  1. Leer los TIPOS de membrana (plantillas: objetos, carga, hijos, reglas).
  2. Crear las membranas: las sueltas de `membranes:` y las de `population:` (se expanden
     N copias de un tipo, cada una con sus hijos; p. ej. una célula con su vacuola).
  3. Enlazar padres e hijos, comprobar la estructura y construir la vecindad.
  4. Crear las reglas (una vez por tipo; las comparten todas sus instancias).
Si el YAML tiene algún error se lanza ValueError con un mensaje claro.
"""
import random
import re
from collections import Counter
from dataclasses import dataclass, field

import yaml

from .model import (ChargeCheck, Condition, Engulf, Item, Membrane, Need, Partner, PSystem,
                    Record, Rule, SetCharge, link)
from .refs import check_ref

_PARAM = re.compile(r"\$\{(\w+)\}")


def load_system(path: str, params: dict | None = None, seed: int | None = None) -> PSystem:
    with open(path, encoding="utf-8") as f:
        return parse_text(f.read(), params, seed)


@dataclass
class _TypeDef:                       # una plantilla de membrana (solo se usa aquí dentro)
    name: str
    objects: Counter = field(default_factory=Counter)
    charge: int = 0
    children: list = field(default_factory=list)      # nombres de tipos hijos
    raw_rules: dict = field(default_factory=dict)
    rules: list = field(default_factory=list)         # se rellena en el paso 4


# ------------------------------------------------------- parámetros ---
def read_params(text: str) -> dict:
    """Lee el bloque `params:` (si lo hay): {nombre: {value, min, max, step, label}}.
    Sirve para que la interfaz ofrezca un deslizador por parámetro."""
    data = yaml.safe_load(_PARAM.sub("0", text)) or {}      # (los ${..} se ignoran en esta primera lectura)
    out = {}
    for name, p in (data.get("params") or {}).items():
        p = p if isinstance(p, dict) else {"value": p}
        value = p["value"]
        out[name] = {"value": value, "min": p.get("min", 0), "max": p.get("max", max(10, 2 * value)),
                     "step": p.get("step", 1), "label": p.get("label", name)}
    return out


def _substitute(text: str, values: dict) -> str:
    def repl(m):
        if m.group(1) not in values:
            raise ValueError(f"Parámetro desconocido: ${{{m.group(1)}}} (defínelo en 'params:')")
        return str(values[m.group(1)])
    return _PARAM.sub(repl, text)


# ----------------------------------------------------------- parse ---
def parse_text(text: str, params: dict | None = None, seed: int | None = None) -> PSystem:
    """`params` sobrescribe los valores por defecto del bloque params; `seed` sobrescribe la del YAML."""
    declared = read_params(text)
    values = {n: p["value"] for n, p in declared.items()}
    for n, v in (params or {}).items():
        if n not in declared:
            raise ValueError(f"Parámetro desconocido: '{n}'")
        values[n] = v
    data = yaml.safe_load(_substitute(text, values))
    if not data or "system" not in data:
        raise ValueError("El YAML debe empezar con la clave 'system:'")
    sd = data["system"]

    seed = seed if seed is not None else sd.get("seed")
    if seed is None:                                           # sin semilla: se elige una y se guarda
        seed = random.SystemRandom().randrange(2 ** 31)        # (así cualquier resultado se puede repetir)

    # 1) tipos ---------------------------------------------------------
    types = {}
    for tname, td in (sd.get("types") or {}).items():
        td = td or {}
        types[_name(tname)] = _TypeDef(_name(tname), _objects(td.get("objects")), _charge(td.get("charge", 0)),
                                       [_name(c) for c in td.get("children") or []], td.get("rules") or {})
    for t in types.values():
        for c in t.children:
            if c not in types:
                raise ValueError(f"El tipo '{t.name}' tiene un hijo de tipo desconocido: '{c}'")

    # 2) membranas -----------------------------------------------------
    membranes, parent_of, own_rules = {}, {}, {}
    for md in sd.get("membranes") or []:                       # membranas sueltas (p. ej. el medio)
        name = _name(md["name"])
        _add(membranes, Membrane(name, None, _objects(md.get("objects")), charge=_charge(md.get("charge", 0))))
        parent_of[name] = md.get("parent")
        own_rules[name] = md.get("rules") or {}

    rng = random.Random(seed)                                  # para la variabilidad inicial
    vary_on = bool(sd.get("variability", False))               # desactivada por defecto
    for pd in sd.get("population") or []:
        ttype = _name(pd["type"])
        if ttype not in types:
            raise ValueError(f"population: tipo desconocido '{ttype}'")
        prefix = pd.get("prefix", ttype + "_")
        for i in range(1, pd.get("count", 1) + 1):
            _instantiate(types, ttype, f"{prefix}{i}", pd["parent"], membranes, parent_of,
                         pd.get("variability") if vary_on else None, rng)

    # 3) estructura y vecindad -------------------------------------------
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
    nb = sd.get("neighborhood")
    if nb:
        _build_neighborhood(nb, membranes, set(types))

    # 4) reglas --------------------------------------------------------
    names = set(membranes)
    for t in types.values():
        t.rules = [_parse_rule(rn, rd, set(types), names) for rn, rd in t.raw_rules.items()]
    for m in membranes.values():
        if m.type is not None:
            m.rules = types[m.type].rules                      # compartidas por todas las instancias
        else:
            m.rules = [_parse_rule(rn, rd, set(types), names) for rn, rd in own_rules[m.name].items()]

    return PSystem(sd.get("name", "sin_nombre"), membranes, max_steps=sd.get("max_steps", 50),
                   seed=seed, neighborhood=bool(nb))


# ------------------------------------------------------ población ---
def _instantiate(types, tname, name, parent_name, membranes, parent_of, vary, rng):
    """Crea una membrana de tipo `tname` y, recursivamente, sus hijos (p. ej. su vacuola)."""
    t = types[tname]
    objects, charge = Counter(t.objects), t.charge
    vary = vary or {}
    for obj, (lo, hi) in (vary.get("objects") or {}).items():  # objeto -> [mín, máx]
        objects[_name(obj)] = rng.randint(lo, hi)
    if "charge" in vary:                                       # carga -> [mín, máx] (0 y/o 1)
        charge = _charge(rng.randint(*vary["charge"]))
    _add(membranes, Membrane(name, tname, +objects, charge=charge))   # +objects quita los ceros
    parent_of[name] = parent_name
    for child_type in t.children:
        _instantiate(types, child_type, f"{name}_{child_type}", name, membranes, parent_of, None, rng)


# ------------------------------------------------------- vecindad ---
def _build_neighborhood(nb, membranes, type_names):
    """Crea los contactos entre las células de un tipo: rejilla y/o enlaces explícitos."""
    tname, parent_name = nb["type"], nb.get("parent")
    if tname not in type_names:
        raise ValueError(f"neighborhood: tipo desconocido '{tname}'")
    cells = [m for m in membranes.values()
             if m.type == tname and (parent_name is None or (m.parent and m.parent.name == parent_name))]
    grid = nb.get("grid")
    if grid:                                                   # las células, en orden, rellenan la rejilla por filas
        cols, diagonals = grid["cols"], bool(grid.get("diagonals", False))
        at = {}
        for i, m in enumerate(cells):
            m.pos = (i % cols, i // cols)
            at[m.pos] = m
        steps = [(1, 0), (0, 1)] + ([(1, 1), (-1, 1)] if diagonals else [])
        for (c, r), m in at.items():
            for dc, dr in steps:
                if (c + dc, r + dr) in at:
                    link(m, at[(c + dc, r + dr)])
    for a, b in nb.get("links") or []:                         # enlaces explícitos
        link(_get(membranes, a, "neighborhood.links"), _get(membranes, b, "neighborhood.links"))


# --------------------------------------------------------- reglas ---
def _parse_rule(name, rd, type_names, membrane_names) -> Rule:
    partner = _parse_partner(rd.get("partner"), type_names, name)
    ok = lambda ref: _checked(ref, name, type_names, membrane_names, partner is not None)

    inputs = [Item(_name(i["object"]), i.get("number", 1), ok(i.get("at", "self")))
              for i in rd.get("input") or []]
    outputs = [Item(_name(i["object"]), i.get("number", 1), ok(i.get("at", i.get("target", "self"))))
               for i in rd.get("output") or []]
    engulf = Engulf(ok(rd["engulf"]["cell"]), ok(rd["engulf"]["into"])) if "engulf" in rd else None
    dissolve = [ok(r) for r in _as_list(rd.get("dissolve"))]
    set_charge = []
    for sc in _as_list(rd.get("set_charge")):
        to = sc["to"]
        if to not in (0, 1, "flip"):
            raise ValueError(f"Regla '{name}': set_charge.to debe ser 0, 1 o flip (no '{to}')")
        set_charge.append(SetCharge(ok(sc["at"]), to))
    record = None
    if "record" in rd:
        rec = rd["record"]
        record = Record(str(rec["event"]), ok(rec["cell"]), ok(rec["other"]) if "other" in rec else None)
    if not (inputs or outputs or engulf or dissolve or set_charge or record):
        raise ValueError(f"La regla '{name}' no hace nada (necesita input, output, engulf, dissolve, "
                         f"set_charge o record)")

    weight, delay = rd.get("weight", 1), rd.get("delay", 0)
    if weight < 0:
        raise ValueError(f"Regla '{name}': weight no puede ser negativo")
    if not isinstance(delay, int) or delay < 0:
        raise ValueError(f"Regla '{name}': delay debe ser un entero ≥ 0")

    cd = rd.get("condition") or {}
    needs = []
    for nd in _as_list(cd.get("needs")):
        at = nd.get("at", nd.get("membrane"))                  # 'membrane' = nombre antiguo de 'at'
        # min por defecto: 1 ("tiene que haber"), pero 0 si solo se da `max` ("como mucho"; incluye el 0)
        default_min = 0 if "max" in nd else 1
        needs.append(Need(ok(at), _name(nd["object"]), nd.get("min", nd.get("number", default_min)), nd.get("max")))
    charge = [ChargeCheck(ok(c["at"]), [_charge(v) for v in _as_list(c["is"])]) for c in _as_list(cd.get("charge"))]
    condition = Condition(cd.get("from_step", 1), cd.get("until_step"), needs, charge,
                          bool(cd.get("free", False)), [ok(r) for r in _as_list(cd.get("empty"))])
    return Rule(name, inputs, outputs, engulf, dissolve, set_charge, record, partner, condition, float(weight), delay)


def _parse_partner(p, type_names, rule_name):
    if p is None:
        return None
    spec = {"type": p} if isinstance(p, str) else dict(p)
    if spec.get("type") not in type_names:
        raise ValueError(f"Regla '{rule_name}': partner de tipo desconocido '{spec.get('type')}'")
    via = spec.get("via", "siblings")
    if via not in ("siblings", "neighbors"):
        raise ValueError(f"Regla '{rule_name}': partner.via debe ser siblings o neighbors (no '{via}')")
    cw = spec.get("charge_weight")
    if cw is not None:
        cw = {_charge(k): float(v) for k, v in cw.items()}
    return Partner(spec["type"], via, cw)


def _checked(ref, rule_name, type_names, membrane_names, has_partner):
    try:
        check_ref(ref, type_names, membrane_names, has_partner)
    except ValueError as e:
        raise ValueError(f"Regla '{rule_name}': {e}") from None
    return ref


# ------------------------------------------------------ utilidades ---
def _objects(d) -> Counter:
    return Counter({_name(o): n for o, n in (d or {}).items() if n})


def _charge(v) -> int:
    if v not in (0, 1) or isinstance(v, bool):
        raise ValueError(f"La carga debe ser 0 o 1 (no '{v}')")
    return int(v)


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
