"""Pruebas del motor.  Ejecutar:  python tests/test_engine.py   (sin dependencias extra)

A) Invariantes de la entosis, repitiendo muchas simulaciones con semillas distintas:
   1. Cada internalización se resuelve como mucho UNA vez (muerte o escape, nunca las dos).
   2. Nadie escapa o muere sin haber sido internalizado antes.
   3. Una célula muerta desaparece del sistema (con su vacuola y sus objetos).
   4. No hay anidamiento: la profundidad máxima es medio > huésped > vacuola > interna.
   5. Los objetos L siempre se consumen: no quedan restos.
   6. Una célula escapada vuelve a ser hija directa del medio.
B) Funciones nuevas: ruleta (weight), retardos (delay), reglas de síntesis, carga, vecindad,
   parámetros, y que explain() coincide con lo que hace el motor.
"""
import os
import sys

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gui.explain import explain_at                              # noqa: E402
from gui.recorder import Recorder                               # noqa: E402
from psystem import Simulator, parse_text                       # noqa: E402

TEMPLATES = os.path.join(os.path.dirname(__file__), "..", "templates")


def run(template: str, seed: int, params: dict | None = None) -> Simulator:
    text = open(os.path.join(TEMPLATES, template), encoding="utf-8").read()
    sim = Simulator(parse_text(text, params, seed))
    sim.run()
    return sim


def depth(m) -> int:
    d = 0
    while m.parent is not None:
        m, d = m.parent, d + 1
    return d


def check_entosis(sim: Simulator) -> None:
    s = sim.system
    internalized = {}                       # célula -> nº de internalizaciones pendientes de resolver
    for f in sim.fates:                     # (en orden cronológico)
        if f["event"] == "internalization":
            internalized[f["cell"]] = internalized.get(f["cell"], 0) + 1
        elif f["event"] in ("death_internal", "escape"):
            assert internalized.get(f["cell"], 0) >= 1, f"{f} sin internalización previa (o resuelta dos veces)"
            internalized[f["cell"]] -= 1
    for f in sim.fates:                     # 3
        if f["event"] in ("death_internal", "death_host"):
            assert f["cell"] not in s.membranes, f"{f['cell']} murió pero sigue existiendo"
            assert f["cell"] + "_Vacuole" not in s.membranes, f"vacuola de {f['cell']} sigue existiendo"
    assert all(depth(m) <= 4 for m in s.membranes.values()), "hay anidamiento excesivo"     # 4
    for m in s.membranes.values():
        if m.type == "Cell" and m.parent.type == "Vacuole":
            assert not m.children[0].children, "una célula interna aloja a otra (anidamiento)"
    for m in s.membranes.values():          # 5
        assert m.objects["L"] == 0, f"quedan {m.objects['L']} L en {m.name}"
    last = {}                               # 6
    for f in sim.fates:
        last[f["cell"]] = f["event"]
    for cell, event in last.items():
        if event == "escape" and cell in s.membranes:
            assert s.membranes[cell].parent is s.skin, f"{cell} escapó pero no está en el medio"


MINI = """
system:
  name: mini
  max_steps: {steps}
  membranes:
    - name: SK
      objects: {{x: {x}}}
      rules:
{rules}
"""


def mini(rules: str, x: int = 1, steps: int = 5, seed: int = 0) -> Simulator:
    sim = Simulator(parse_text(MINI.format(rules=rules, x=x, steps=steps), None, seed))
    return sim


def test_roulette():
    """Dos reglas rivales por el mismo objeto con pesos 9 y 1: la primera gana ~90 % de las veces."""
    wins = 0
    for seed in range(600):
        sim = mini("        a: {weight: 9, input: [{object: x}], output: [{object: A}]}\n"
                   "        b: {weight: 1, input: [{object: x}], output: [{object: B}]}", seed=seed)
        sim.run(1)
        wins += sim.system.membranes["SK"].objects["A"]
    assert 0.85 < wins / 600 < 0.95, f"proporción de 'a' = {wins / 600:.2f} (esperado ~0.90)"
    # weight 0 = la regla nunca se elige
    sim = mini("        a: {weight: 0, input: [{object: x}], output: [{object: A}]}")
    sim.run()
    assert sim.system.membranes["SK"].objects["A"] == 0


def test_needs_max_only_includes_zero():
    """`needs: {object: x, max: 3}` significa "como mucho 3", y 0 cuenta: si no, una regla de síntesis
    que repone x se quedaría bloqueada para siempre en cuanto x llegara a 0."""
    sim = mini("        s: {condition: {needs: [{at: self, object: x, max: 3}]}, output: [{object: x}]}", x=0, steps=3)
    sim.run()
    assert sim.system.membranes["SK"].objects["x"] == 3          # repone 1 por paso desde 0
    sim = mini("        s: {condition: {needs: [{at: self, object: x, min: 1, max: 3}]}, output: [{object: x}]}", x=0, steps=3)
    sim.run()
    assert sim.system.membranes["SK"].objects["x"] == 0          # con min: 1 explícito sí exige que haya


def test_delay():
    """delay: 2 -> el objeto se gasta ya y el producto llega 2 pasos más tarde de lo normal."""
    sim = mini("        a: {delay: 2, input: [{object: x}], output: [{object: A}]}", steps=6)
    sk = sim.system.membranes["SK"]
    sim.step()                                                  # paso 1: se consume x; A aún no existe
    assert sk.objects["x"] == 0 and sk.objects["A"] == 0 and len(sim.pending) == 1
    assert sim.pending_summary() == [{"at": "SK", "obj": "A", "n": 1, "due": 3}]
    sim.step(); assert sk.objects["A"] == 0                     # paso 2: sigue en curso
    sim.step(); assert sk.objects["A"] == 1 and not sim.pending  # llega al final del paso 3


def test_source_rule_once_per_step():
    sim = mini("        s: {output: [{object: S}]}", x=0, steps=4)
    sim.run()
    assert sim.system.membranes["SK"].objects["S"] == 4          # 1 por paso, no infinitas


def test_charge():
    text = """
system:
  name: carga
  max_steps: 3
  types:
    Cell:
      charge: 1
      rules:
        flip: {condition: {charge: [{at: self, is: 1}]}, set_charge: [{at: self, to: 0}]}
  membranes: [{name: SK}]
  population: [{type: Cell, count: 2, parent: SK, prefix: C}]
"""
    sim = Simulator(parse_text(text, None, 0))
    assert [m.charge for m in sim.system.membranes.values() if m.type == "Cell"] == [1, 1]
    sim.step()
    assert [m.charge for m in sim.system.membranes.values() if m.type == "Cell"] == [0, 0]
    try:
        parse_text(text.replace("charge: 1", "charge: 2"), None, 0)
        raise AssertionError("debería rechazar una carga distinta de 0/1")
    except ValueError:
        pass


def test_neighbors():
    """Cadena C1-C2-C3: C1 solo puede invadir a C2 (su única vecina), nunca a C3."""
    base = open(os.path.join(TEMPLATES, "09_vecindad_rejilla.yaml"), encoding="utf-8").read()
    data = yaml.safe_load(base)
    sd = data["system"]
    sd["population"][0]["count"] = 3
    sd["neighborhood"]["grid"] = {"cols": 3}
    sd["membranes"][0]["objects"]["P"] = 2                       # solo cabe una invasión
    for seed in range(60):
        sim = Simulator(parse_text(yaml.dump(data), None, seed))
        sim.run()
        first = next((f for f in sim.fates if f["event"] == "internalization"), None)
        assert first is not None
        assert {first["cell"], first["other"]} in ({"C1", "C2"}, {"C2", "C3"}), f"{first} no son vecinas"
    # contactos: al escapar, la célula recupera los suyos y se hace vecina de su ex-huésped
    sim = Simulator(parse_text(yaml.dump(data), None, 0))
    c1, c2 = sim.system.membranes["C1"], sim.system.membranes["C2"]
    assert c1.contacts == [c2]
    sim.system.move_membrane(c1, sim.system.membranes["C2_Vacuole"])       # C1 entra en C2
    sim.system.move_membrane(c1, sim.system.skin)                          # y sale
    assert c2 in c1.contacts and c1 in c2.contacts


def test_params():
    text = open(os.path.join(TEMPLATES, "10_modelo_completo.yaml"), encoding="utf-8").read()
    s1 = parse_text(text, {"promotores": 7}, 1)
    assert s1.membranes["SK"].objects["P"] == 7
    try:
        parse_text(text, {"no_existe": 1}, 1)
        raise AssertionError("debería rechazar un parámetro desconocido")
    except ValueError:
        pass


def test_seed_reproducible():
    a, b = run("07_objetos_y_retardos.yaml", 5), run("07_objetos_y_retardos.yaml", 5)
    assert a.fates == b.fates and a.system.t == b.system.t


def test_explain_matches_engine():
    """explain() reconstruye el estado al INICIO del paso. Dentro de un paso otras reglas pueden haber
    cambiado estructura, cargas o hecho bajar un objeto bajo un umbral `max`, así que solo exigimos
    coincidencia exacta a las reglas que dependen únicamente de que existan objetos (los objetos
    solo pueden disminuir durante un paso): si se aplicaron, al inicio ya se cumplían."""
    text = open(os.path.join(TEMPLATES, "07_objetos_y_retardos.yaml"), encoding="utf-8").read()
    rec = Recorder(Simulator(parse_text(text, None, 3)), yaml_text=text, params={})
    rec.run()
    data, checked = rec.to_dict(), 0
    only_objects = {"decay_R", "acidify", "engage_lysosome", "kill_inner", "kill_host", "escape"}
    for frame in data["frames"][1:]:
        for e in frame["events"]:
            out = explain_at(data, frame["t"], e["membrane"], e["rule"])
            assert out["applied_times"] == e["times"]
            if e["rule"] in only_objects:
                bad = [txt for _, checks in out["scenarios"] for ok, txt in checks if not ok]
                assert not bad, (e["membrane"], e["rule"], frame["t"], bad)
                checked += 1
    assert checked > 10
    # y una regla que NO puede aplicarse debe mostrar qué condición falla
    out = explain_at(data, 1, "C1", "invade")                      # en t=1 aún no se cumple 't ≥ 3'
    assert any(not ok and txt.startswith("t ≥ 3") for _, checks in out["scenarios"] for ok, txt in checks)


def main():
    total = 0
    for template in ["01_entosis_2_celulas.yaml", "02_poblacion_10.yaml", "05_poblacion_100.yaml",
                     "06_variabilidad.yaml", "07_objetos_y_retardos.yaml", "08_polarizacion.yaml",
                     "09_vecindad_rejilla.yaml", "10_modelo_completo.yaml"]:
        for seed in range(30):
            check_entosis(run(template, seed))
            total += 1
    assert run("03_control_sin_promotores.yaml", 0).fates == []
    sim = run("04_test_comunicacion.yaml", 0)
    assert sim.system.membranes["B"].objects["d"] == 2 and sim.system.membranes["A"].objects["b"] == 2
    for t in (test_roulette, test_needs_max_only_includes_zero, test_delay, test_source_rule_once_per_step, test_charge, test_neighbors,
              test_params, test_seed_reproducible, test_explain_matches_engine):
        t()
        print(f"  ok  {t.__name__}")
    print(f"OK: {total} simulaciones de entosis comprobadas + control + comunicación + pruebas de funciones")


if __name__ == "__main__":
    main()
