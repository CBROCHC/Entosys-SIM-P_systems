"""refs.py - Referencias relativas entre membranas.

Una referencia es un texto que dice "a qué membrana me refiero" PARTIENDO DE la
membrana donde vive la regla (`self`) y, si la regla lo pide, de su compañero (`partner`):

    self                      la propia membrana
    partner                   el compañero elegido por la regla (ver `partner:` en el YAML)
    parent                    el padre de self
    child:Vacuole             el primer hijo de self que sea de tipo Vacuole
    partner.child:Vacuole     se pueden encadenar pasos con puntos
    parent.parent             el abuelo (p. ej. el medio, visto desde una vacuola)
    SK                        un nombre concreto de membrana (para membranas sueltas)

Si el primer paso no es `self`, `partner` ni un nombre de membrana, se parte de `self`
(así "parent" significa "self.parent").
"""
from __future__ import annotations

from .model import Membrane, PSystem


def resolve(system: PSystem, ref: str, me: Membrane, partner: Membrane | None) -> Membrane | None:
    """Devuelve la membrana a la que apunta `ref` ahora mismo, o None si no existe."""
    steps = ref.split(".")
    first = steps[0]
    if first == "self":
        current, steps = me, steps[1:]
    elif first == "partner":
        current, steps = partner, steps[1:]
    elif first in system.membranes:
        current, steps = system.membranes[first], steps[1:]
    else:
        current = me                                   # relativa a self
    for step in steps:
        if current is None:
            return None
        current = _next(current, step)
    return current


def _next(m: Membrane, step: str) -> Membrane | None:
    if step == "parent":
        return m.parent
    if step.startswith("child:"):
        wanted = step[len("child:"):]
        return next((c for c in m.children if c.type == wanted), None)
    raise ValueError(f"Paso de referencia desconocido: '{step}'")


def check_ref(ref: str, type_names: set[str], membrane_names: set[str], has_partner: bool) -> None:
    """Valida la sintaxis de una referencia al leer el YAML (lanza ValueError si está mal)."""
    steps = ref.split(".")
    first = steps[0]
    if first == "partner" and not has_partner:
        raise ValueError(f"'{ref}': usa 'partner' pero la regla no declara 'partner: <Tipo>'")
    rest = steps[1:] if first in ("self", "partner") or first in membrane_names else steps
    for step in rest:
        if step == "parent":
            continue
        if step.startswith("child:") and step[len("child:"):] in type_names:
            continue
        raise ValueError(f"'{ref}': paso '{step}' no válido (usa parent, child:<Tipo>, self, partner "
                         f"o el nombre de una membrana)")
