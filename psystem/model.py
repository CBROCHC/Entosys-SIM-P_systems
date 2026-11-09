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
class Need:
    """Umbral de objetos: la membrana `at` debe tener entre `min` y `max` copias de `obj`."""
    at: str
    obj: str
    min: int = 1
    max: int | None = None           # None = sin máximo (max: 0 sirve para pedir "ninguno")


@dataclass
class Condition:
    """Condiciones extra para que una regla pueda aplicarse (todas a la vez)."""
    from_step: int = 1               # no actúa antes de este paso
    until_step: int | None = None    # ni después de este (None = sin límite)
    needs: list[Need] = field(default_factory=list)       # umbrales de objetos
    free: bool = False               # `self` debe ser hija directa del medio (célula libre)
    empty: list[str] = field(default_factory=list)        # estas membranas no deben contener membranas


@dataclass
class Rule:
    name: str
    inputs: list[Item] = field(default_factory=list)      # objetos que se consumen
    outputs: list[Item] = field(default_factory=list)     # objetos que se producen
    engulf: Engulf | None = None                          # mover una membrana dentro de otra
    dissolve: list[str] = field(default_factory=list)     # membranas que se disuelven (desaparecen)
    record: Record | None = None                          # suceso a registrar
    partner: str | None = None                            # tipo de "compañero" (hermano) que necesita
    condition: Condition = field(default_factory=Condition)


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


# ========================================================= P-SISTEMA ===
class PSystem:
    def __init__(self, name: str, membranes: dict[str, Membrane],
                 max_steps: int = 50, seed: int | None = None):
        self.name = name
        self.membranes = membranes                   # nombre -> Membrane (solo las que existen ahora)
        self.skin = next(m for m in membranes.values() if m.parent is None)   # el medio
        self.max_steps = max_steps
        self.seed = seed
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
        """Reubica `cell` (con todo lo que lleva dentro) como hija de `destination`."""
        cell.parent.children.remove(cell)
        destination.children.append(cell)
        cell.parent = destination

    def dissolve_membrane(self, m: Membrane) -> None:
        """Disuelve `m`: sus OBJETOS se destruyen (la célula se descompone) y las membranas
        que contenía pasan a su padre. La piel no se puede disolver."""
        parent = m.parent
        for child in list(m.children):
            child.parent = parent
            parent.children.append(child)
        parent.children.remove(m)
        m.children.clear()
        m.objects.clear()
        m.alive = False
        del self.membranes[m.name]
