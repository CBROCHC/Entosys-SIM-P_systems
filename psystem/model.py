"""model.py - Los DATOS del P-sistema (membranas, reglas, condiciones).

Aquí no hay lógica de simulación: solo estructuras y operaciones muy básicas.

Idea clave: las reglas NO nombran membranas concretas. Usan REFERENCIAS RELATIVAS
(texto) como "self", "parent" o "child:Vacuole", que el motor resuelve en el momento
de aplicar la regla (ver refs.py). Así una misma regla sirve para cualquier célula.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


# ============================================================ REGLAS ===
@dataclass
class Item:
    """`number` copias del objeto `obj` en la membrana a la que apunta la referencia `at`.
    Se usa tanto para lo que la regla CONSUME (input) como para lo que PRODUCE (output)."""
    obj: str
    number: int = 1
    at: str = "self"                 # referencia relativa; "self" = la membrana donde vive la regla


@dataclass
class Engulf:
    """Acción 'engulf': mueve la membrana `cell` (con todo su contenido) dentro de `into`."""
    cell: str                        # referencia a la membrana que se mueve
    into: str                        # referencia a la membrana destino


@dataclass
class Record:
    """Apunta un suceso en el registro (p. ej. muerte, escape, internalización)."""
    event: str                       # nombre libre del suceso
    cell: str                        # referencia a la célula protagonista
    other: str | None = None         # referencia a la otra célula implicada (opcional)


@dataclass
class SetCharge:
    """Cambia la carga de la membrana `at`: a 0, a 1, o la invierte ("flip")."""
    at: str
    to: int | str


@dataclass
class Need:
    """Umbral de objetos: la membrana `at` debe tener entre `min` y `max` copias de `obj`."""
    at: str
    obj: str
    min: int = 1
    max: int | None = None           # None = sin máximo (max: 0 sirve para pedir "ninguno")


@dataclass
class ChargeCheck:
    """La carga de la membrana `at` debe ser uno de `values` (0 y/o 1)."""
    at: str
    values: list[int]


@dataclass
class Condition:
    """Condiciones extra para que una regla pueda aplicarse (todas a la vez)."""
    from_step: int = 1               # no actúa antes de este paso
    until_step: int | None = None    # ni después de este (None = sin límite)
    needs: list[Need] = field(default_factory=list)            # umbrales de objetos
    charge: list[ChargeCheck] = field(default_factory=list)    # condiciones sobre la carga
    free: bool = False               # `self` debe ser hija directa del medio (célula libre)
    empty: list[str] = field(default_factory=list)             # estas membranas no deben contener membranas


@dataclass
class Partner:
    """El 'compañero' que necesita una regla (p. ej. el huésped al que invadir)."""
    type: str                                    # tipo de membrana del compañero
    via: str = "siblings"                        # "siblings": cualquier hermana · "neighbors": solo vecinas en contacto
    charge_weight: dict | None = None            # {carga del candidato: peso} para elegirlo con más/menos probabilidad


@dataclass
class Rule:
    name: str
    inputs: list[Item] = field(default_factory=list)      # objetos que se consumen
    outputs: list[Item] = field(default_factory=list)     # objetos que se producen
    engulf: Engulf | None = None                          # mover una membrana dentro de otra
    dissolve: list[str] = field(default_factory=list)     # membranas que se disuelven (desaparecen)
    set_charge: list[SetCharge] = field(default_factory=list)   # cambios de carga
    record: Record | None = None                          # suceso a registrar
    partner: Partner | None = None                        # compañero que necesita (opcional)
    condition: Condition = field(default_factory=Condition)
    weight: float = 1.0                                   # peso en la ruleta entre reglas aplicables
    delay: int = 0                                        # pasos extra hasta que aparecen los productos

    @property
    def is_source(self) -> bool:
        """Una regla sin `input` no gasta nada: se aplica como mucho una vez por paso y membrana."""
        return not self.inputs


# ========================================================== MEMBRANAS ===
@dataclass(eq=False)       # eq=False: las membranas se comparan por identidad
class Membrane:
    name: str
    type: str | None = None                                  # etiqueta ("Cell", "Vacuole"...) o None
    objects: Counter = field(default_factory=Counter)        # multiconjunto de objetos
    rules: list[Rule] = field(default_factory=list)          # (pueden compartirse entre membranas del mismo tipo)
    parent: Membrane | None = field(default=None, repr=False)
    children: list[Membrane] = field(default_factory=list, repr=False)
    alive: bool = True                                       # False cuando se ha disuelto
    charge: int = 0                                          # polarización: 0 o 1
    contacts: list[Membrane] = field(default_factory=list, repr=False)   # vecinas (en orden estable)
    pos: tuple | None = None                                 # (columna, fila) si hay rejilla de vecindad


def link(a: Membrane, b: Membrane) -> None:
    """Hace vecinas a `a` y `b` (contacto simétrico)."""
    if a is not b and b not in a.contacts:
        a.contacts.append(b)
        b.contacts.append(a)


# ========================================================= P-SISTEMA ===
class PSystem:
    def __init__(self, name: str, membranes: dict[str, Membrane],
                 max_steps: int = 50, seed: int | None = None, neighborhood: bool = False):
        self.name = name
        self.membranes = membranes                   # nombre -> Membrane (solo las que existen ahora)
        self.skin = next(m for m in membranes.values() if m.parent is None)   # el medio
        self.max_steps = max_steps
        self.seed = seed
        self.neighborhood = neighborhood             # ¿hay vecindad definida en el YAML?
        self.t = 0                                   # paso actual

    # ---- consultas de estructura
    def is_inside(self, membrane: Membrane, container: Membrane) -> bool:
        """True si `membrane` es `container` o está dentro de él (a cualquier profundidad)."""
        while membrane is not None:
            if membrane is container:
                return True
            membrane = membrane.parent
        return False

    # ---- cambios de estructura
    def move_membrane(self, cell: Membrane, destination: Membrane) -> None:
        """Reubica `cell` (con todo lo que lleva dentro) como hija de `destination`.

        Vecindad: si `cell` sale de una membrana (p. ej. una vacuola) que estaba dentro de una
        hermana (el huésped) y queda libre junto a ella, pasa a ser su vecina."""
        old_parent = cell.parent
        old_parent.children.remove(cell)
        destination.children.append(cell)
        cell.parent = destination
        host = old_parent.parent
        if host is not None and host.parent is cell.parent:
            link(cell, host)

    def dissolve_membrane(self, m: Membrane) -> None:
        """Disuelve `m`: sus OBJETOS se destruyen (la célula se descompone) y las membranas
        que contenía pasan a su padre. Sus contactos desaparecen. La piel no se puede disolver."""
        parent = m.parent
        for child in list(m.children):
            child.parent = parent
            parent.children.append(child)
        parent.children.remove(m)
        for other in m.contacts:
            other.contacts.remove(m)
        m.contacts.clear()
        m.children.clear()
        m.objects.clear()
        m.alive = False
        del self.membranes[m.name]
