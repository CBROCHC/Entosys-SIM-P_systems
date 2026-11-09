"""Ejecuta una plantilla desde la terminal:  python run_cli.py templates/01_entosis_2_celulas.yaml"""
import sys

from psystem import Simulator, load_system

sim = Simulator(load_system(sys.argv[1]))
print(f"Sistema: {sim.system.name}  ({len(sim.system.membranes)} membranas)")
while not sim.finished:
    events = sim.step()
    if events or not sim.halted:
        txt = ", ".join(f"{e['membrane']}.{e['rule']}" + (f" ×{e['times']}" if e["times"] > 1 else "")
                        for e in events)
        print(f"paso {sim.system.t:>3}: {txt or '(esperando)'}")

print(f"\nEstado: {sim.status()}")
print("Sucesos:", sim.fate_counts() or "ninguno")
for f in sim.fates:
    print(f"  t={f['t']:>2}  {f['event']:<15} {f['cell']}  (con {f['other']})")
if len(sim.system.membranes) <= 30:                  # estructura final (solo si es pequeña)
    for m in sim.system.membranes.values():
        padre = m.parent.name if m.parent else "-"
        print(f"  {m.name:<14} (dentro de {padre:<10}) objetos: {dict(m.objects)}")
else:
    print(f"Membranas al final: {len(sim.system.membranes)}")
