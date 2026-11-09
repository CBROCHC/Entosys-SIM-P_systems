"""Pruebas del motor.  Ejecutar:  python tests/test_engine.py   (sin dependencias extra)

Comprueban, repitiendo muchas simulaciones con semillas distintas, las reglas de oro:
  1. Cada internalización se resuelve como mucho UNA vez (muerte o escape, nunca las dos).
  2. Nadie escapa o muere sin haber sido internalizado antes.
  3. Una célula muerta desaparece del sistema (con su vacuola y sus objetos).
  4. No hay anidamiento: la profundidad máxima es medio > huésped > vacuola > interna.
  5. Los objetos L (maduración de la vacuola) siempre se consumen: no quedan restos.
  6. Una célula escapada vuelve a ser hija directa del medio.
"""
import os
import sys

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from psystem import Simulator, parse_text                      # noqa: E402

TEMPLATES = os.path.join(os.path.dirname(__file__), "..", "templates")


def run(template: str, seed: int) -> Simulator:
    data = yaml.safe_load(open(os.path.join(TEMPLATES, template), encoding="utf-8"))
    data["system"]["seed"] = seed
    sim = Simulator(parse_text(yaml.dump(data)))
    sim.run()
    return sim


def depth(m) -> int:
    d = 0
    while m.parent is not None:
        m, d = m.parent, d + 1
    return d


def check(sim: Simulator) -> None:
    s = sim.system
    # 1 y 2: por cada célula, la lista de sucesos debe seguir el orden internalización -> (muerte|escape)
    by_cell = {}
    for f in sim.fates:
        by_cell.setdefault(f["cell"], []).append(f)
    internalized = {}                       # célula -> nº de internalizaciones pendientes de resolver
    for f in sim.fates:                     # (en orden cronológico)
        if f["event"] == "internalization":
            internalized[f["cell"]] = internalized.get(f["cell"], 0) + 1
        elif f["event"] in ("death_internal", "escape"):
            assert internalized.get(f["cell"], 0) >= 1, f"{f} sin internalización previa (o resuelta dos veces)"
            internalized[f["cell"]] -= 1
    # 3: una célula que murió ya no existe (ni ella ni su vacuola)
    for f in sim.fates:
        if f["event"] in ("death_internal", "death_host"):
            assert f["cell"] not in s.membranes, f"{f['cell']} murió pero sigue existiendo"
            assert f["cell"] + "_Vacuole" not in s.membranes, f"vacuola de {f['cell']} sigue existiendo"
    # 4: sin anidamiento (medio=0, huésped=1, vacuola=2, interna=3, vacuola de la interna=4)
    assert all(depth(m) <= 4 for m in s.membranes.values()), "hay anidamiento excesivo"
    for m in s.membranes.values():
        if m.type == "Cell" and m.parent.type == "Vacuole":          # célula interna
            assert not m.children[0].children, "una célula interna aloja a otra (anidamiento)"
    # 5: no quedan restos de L en ninguna membrana
    for m in s.membranes.values():
        assert m.objects["L"] == 0, f"quedan {m.objects['L']} L en {m.name}"
    # 6: las células escapadas están libres... salvo que luego vuelvan a ser internalizadas
    last = {}
    for f in sim.fates:
        last[f["cell"]] = f["event"]
    for cell, event in last.items():
        if event == "escape" and cell in s.membranes:
            assert s.membranes[cell].parent is s.skin, f"{cell} escapó pero no está en el medio"


def main():
    total = 0
    for template in ["01_entosis_2_celulas.yaml", "02_poblacion_10.yaml", "05_poblacion_100.yaml",
                     "06_variabilidad.yaml"]:
        for seed in range(40):
            check(run(template, seed))
            total += 1
    # control: sin promotores no ocurre nada
    assert run("03_control_sin_promotores.yaml", 0).fates == []
    # test de comunicación: máximo paralelismo y envío entre membranas
    sim = run("04_test_comunicacion.yaml", 0)
    assert sim.system.membranes["B"].objects["d"] == 2 and sim.system.membranes["A"].objects["b"] == 2
    print(f"OK: {total} simulaciones comprobadas + control + comunicación")


if __name__ == "__main__":
    main()
