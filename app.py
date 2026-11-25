"""app.py - Interfaz Streamlit (v3).   Ejecutar con:  python -m streamlit run app.py

Flujo:  YAML (+ parámetros + semilla) -> parse_text -> Simulator -> Recorder (graba todos los pasos)
        -> grabación (dict) -> TODAS las pestañas: visor D3, tablas, mapa de reglas, explicaciones.
Para cambiar el visor o añadir análisis no hace falta tocar el motor: solo gui/.
"""
import json
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from gui import analysis
from gui.explain import explain_at
from gui.recorder import Recorder
from gui.viewer import build_html
from psystem import Simulator, parse_text, read_params

TEMPLATES = sorted((Path(__file__).parent / "templates").glob("*.yaml"))


def show_html(html: str, height: int) -> None:
    """Incrusta una página HTML (st.iframe en Streamlit recientes, components.html en antiguos)."""
    if hasattr(st, "iframe"):
        st.iframe(html, height=height)
    else:
        components.html(html, height=height, scrolling=False)


st.set_page_config(page_title="Simulador de entosis (alfa 3)", layout="wide")
st.title("Simulador de entosis con P-sistemas (alfa 3)")


# --------------------------------------------------- barra lateral ---
def simulate(text: str, params: dict, seed: int | None) -> None:
    try:
        rec = Recorder(Simulator(parse_text(text, params, seed)), yaml_text=text, params=params)
        rec.run()                                       # simula hasta el final y graba todos los pasos
        st.session_state.recording = rec.to_dict()
    except Exception as e:                              # error de YAML -> mensaje, sin romper la app
        st.sidebar.error(f"Error en el YAML: {e}")


choice = st.sidebar.selectbox("Plantilla", TEMPLATES, format_func=lambda p: p.stem)
yaml_text = st.sidebar.text_area("YAML (editable)", choice.read_text(encoding="utf-8"),
                                 height=340, key=f"yaml_{choice.name}")

params = {}                                             # parámetros del YAML -> un deslizador cada uno
try:
    declared = read_params(yaml_text)
except Exception as e:
    declared = {}
    st.sidebar.error(f"No se pueden leer los parámetros: {e}")
if declared:
    with st.sidebar.expander("Parámetros del modelo", expanded=True):
        for name, p in declared.items():
            nums = [p["value"], p["min"], p["max"], p["step"]]
            cast = float if any(isinstance(x, float) for x in nums) else int
            params[name] = st.slider(p["label"], cast(p["min"]), cast(p["max"]), cast(p["value"]),
                                     cast(p["step"]), key=f"param_{choice.name}_{name}")

seed_text = st.sidebar.text_input("Semilla (vacío = la del YAML, o aleatoria)", "")
seed = int(seed_text) if seed_text.strip().lstrip("-").isdigit() else None

if st.sidebar.button("Simular", type="primary") or "recording" not in st.session_state:
    simulate(yaml_text, params, seed)

upload = st.sidebar.file_uploader("…o abrir una grabación guardada (.json)", type="json")
if upload is not None and st.session_state.get("last_upload") != (upload.name, upload.size):
    st.session_state.last_upload = (upload.name, upload.size)
    try:
        data = json.load(upload)
        assert "frames" in data and "membranes" in data and "rule_defs" in data
        st.session_state.recording = data
    except Exception:
        st.sidebar.error("Ese fichero no es una grabación válida.")

if "recording" not in st.session_state:
    st.stop()
rec = st.session_state.recording
T = len(rec["frames"]) - 1

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Sistema", rec["name"])
c2.metric("Pasos grabados", T)
c3.metric("Membranas al inicio / final", f"{len(rec['frames'][0]['parents'])} / {len(rec['frames'][-1]['parents'])}")
c4.metric("Semilla", rec["seed"])
c5.metric("Estado", rec["status"])

tab_view, tab_mem, tab_ev, tab_res, tab_map, tab_exp, tab_save = st.tabs(
    ["Visor", "Membranas", "Eventos", "Resultados", "Mapa de reglas", "Explicar", "Grabación"])


# ----------------------------------------------------------- Visor ---
with tab_view:
    st.caption("Rueda = zoom · arrastrar el fondo = desplazar · arrastrar una célula = moverla · clic = estudiar "
               "sus reglas aplicadas, lo que consumieron/produjeron y las condiciones cumplidas · ▶ reproduce de t=0 al final · "
               "SVG / PNG / Vídeo guardan lo que ves.")
    show_html(build_html(rec), height=840)


# ------------------------------------------------------- Membranas ---
with tab_mem:
    t = st.slider("Paso", 0, T, T) if T > 0 else 0
    df = analysis.membranes_table(rec, t)

    f1, f2 = st.columns([2, 1])
    text = f1.text_input("Filtrar (nombre de membrana u objeto)")
    depths = f2.multiselect("Profundidad", sorted(df.profundidad.unique()))
    if text:
        mask = df.membrana.str.contains(text, case=False) | df.objetos.str.contains(text, case=False)
        df = df[mask]
    if depths:
        df = df[df.profundidad.isin(depths)]
    st.caption(f"{len(df)} membranas (haz clic en una fila para ver su detalle; ordena con la cabecera)")

    selection = st.dataframe(df, hide_index=True, on_select="rerun", selection_mode="single-row",
                             key="mem_table", height=380)
    rows = selection.selection.rows
    if rows:
        name = df.iloc[rows[0]]["membrana"]
        frame = rec["frames"][t]
        st.subheader(f"{name}  (paso {t})")
        d1, d2, d3 = st.columns(3)
        with d1:
            st.write("**Ruta:** " + " › ".join(analysis.path_of(frame["parents"], name)))
            st.write("**Objetos**")
            objs = frame["objects"].get(name, {})
            st.dataframe([{"objeto": o, "n": n} for o, n in sorted(objs.items())], hide_index=True)
        with d2:
            st.write("**Posición en el tiempo**")
            st.dataframe([{"desde el paso": p, "dentro de": parent}
                          for p, parent in analysis.position_history(rec, name)], hide_index=True)
        with d3:
            st.write("**Reglas**")
            st.dataframe(analysis.membrane_rules_table(rec, name), hide_index=True)


# ---------------------------------------------------------- Eventos ---
with tab_ev:
    ev = analysis.events_table(rec)
    if ev.empty:
        st.info("No se aplicó ninguna regla en esta simulación.")
    else:
        e1, e2, e3 = st.columns(3)
        rules = e1.multiselect("Regla", sorted(ev.regla.unique()))
        mtext = e2.text_input("Membrana contiene")
        lo, hi = e3.slider("Pasos", 1, T, (1, T)) if T > 1 else (1, T)
        view = ev[(ev.paso >= lo) & (ev.paso <= hi)]
        if rules:
            view = view[view.regla.isin(rules)]
        if mtext:
            view = view[view.membrana.str.contains(mtext, case=False)]
        st.write(f"**Reglas aplicadas** ({len(view)} filas) — qué consumió y produjo cada una, con qué compañero y qué acciones hizo")
        st.dataframe(view, hide_index=True, height=320)

    st.write("**Cambios de estructura** (internalizaciones, escapes, disoluciones)")
    moves = analysis.moves_table(rec)
    st.dataframe(moves, hide_index=True) if len(moves) else st.caption("Ninguno.")

    st.write("**Uso de reglas** (una fila por regla de cada tipo, aunque no se aplicara nunca)")
    usage = analysis.rule_usage_table(rec)
    only_unused = st.checkbox("Solo reglas nunca aplicadas")
    st.dataframe(usage[usage.veces == 0] if only_unused else usage, hide_index=True, height=300)


# -------------------------------------------------------- Resultados ---
with tab_res:
    fates = analysis.fates_table(rec)
    if fates.empty:
        st.info("No se registró ningún suceso (internalización, muerte, escape) en esta simulación.")
    else:
        counts = fates.suceso.value_counts()
        cols = st.columns(len(counts))
        for col, (event, n) in zip(cols, counts.items()):
            col.metric(event, int(n))
        st.bar_chart(counts, y_label="nº de sucesos", x_label="suceso")
        st.write("**Sucesos y células implicadas** (celula = protagonista, con = la otra célula)")
        st.dataframe(fates, hide_index=True, height=260)
        st.write("**Secuencia de sucesos por célula**")
        st.dataframe(analysis.fates_by_cell(rec), hide_index=True, height=260)


# ----------------------------------------------------- Mapa de reglas ---
with tab_map:
    st.write("Mapa de dependencias entre **objetos** (elipses, agrupados por tipo de membrana) y **reglas** (cuadrados). "
             "Flecha continua: se consume (objeto → regla) o se produce (regla → objeto, verde). Discontinua: umbral que la regla "
             "exige sin gastarlo. Debajo, avisos para revisar el modelo.")
    owners = sorted({d["owner"] for d in rec["rule_defs"].values()})
    shown = st.multiselect("Mostrar reglas de", owners, default=owners)
    if shown:
        st.graphviz_chart(analysis.dependency_dot(rec, shown))
    warn = analysis.rule_warnings(rec)
    st.write(f"**Avisos** ({len(warn)})")
    st.dataframe(warn, hide_index=True) if len(warn) else st.success("Sin avisos.")


# ---------------------------------------------------------- Explicar ---
with tab_exp:
    st.write("**¿Por qué se aplicó (o no) una regla en un paso?** Se reconstruye el estado al *inicio* del paso desde la grabación "
             "y se evalúan las condiciones con el mismo código del motor. Ojo: dentro de un paso otras reglas pueden haber "
             "gastado objetos o movido membranas antes, así que para una regla que sí se aplicó, la lista exacta de condiciones "
             "cumplidas en el momento de aplicarla está en el visor (tarjeta verde de la membrana).")
    if not rec.get("yaml"):
        st.info("Esta grabación no incluye el YAML: no se puede reconstruir el estado.")
    elif T < 1:
        st.info("No hay pasos que explicar.")
    else:
        x1, x2, x3 = st.columns(3)
        step = x1.slider("Paso a explicar", 1, T, min(3, T)) if T > 1 else 1
        frame0 = rec["frames"][step - 1]
        mem = x2.selectbox("Membrana (existente al inicio del paso)", sorted(frame0["parents"]))
        rule_ids = rec["membranes"][mem]["rules"]
        rule_names = [rec["rule_defs"][r]["name"] for r in rule_ids]
        rule = x3.selectbox("Regla", rule_names) if rule_names else None
        if rule is None:
            st.info("Esta membrana no tiene reglas.")
        else:
            out = explain_at(rec, step, mem, rule)
            if out["applied_times"]:
                st.success(f"En el paso {step} esta regla se aplicó {out['applied_times']} vez/veces en {mem}.")
            else:
                st.warning(f"En el paso {step} esta regla NO se aplicó en {mem}.")
            st.caption(f"Peso (ruleta): {out['weight']} · retardo: {out['delay']}")
            for label, checks in out["scenarios"]:
                if label:
                    st.write(f"**{label}**")
                for ok, txt in checks:
                    st.write(("✅ " if ok else "❌ ") + txt)
                if checks and all(ok for ok, _ in checks):
                    st.caption("→ con este escenario la regla sería aplicable.")
            if out["options"]:
                st.write("**Reglas aplicables al inicio del paso en esta membrana (compiten en la ruleta):** "
                         + ", ".join(f"{n} (peso {w})" for n, w in out["options"]))
            else:
                st.write("Ninguna regla de esta membrana era aplicable al inicio del paso.")


# -------------------------------------------------------- Grabación ---
with tab_save:
    st.write("La grabación es **autocontenida**: guarda, para cada paso desde t=0, la estructura, los objetos, las cargas, los "
             "productos en curso y las reglas aplicadas con todo su detalle; además el YAML, los parámetros y la semilla, "
             "así que cualquier resultado se puede reproducir.")
    s1, s2 = st.columns(2)
    s1.download_button("⬇ Grabación (.json) — reabrir en esta app", json.dumps(rec, ensure_ascii=False),
                       file_name=f"{rec['name']}.json", mime="application/json")
    s2.download_button("⬇ Visor independiente (.html) — se abre en cualquier navegador, sin Python",
                       build_html(rec), file_name=f"{rec['name']}_visor.html", mime="text/html")
    st.caption(f"Estado de la simulación: {rec['status']} · semilla {rec['seed']} · parámetros {rec.get('params') or '—'}")
    if rec.get("yaml"):
        if st.button("Re-simular con el YAML, los parámetros y la semilla de esta grabación"):
            simulate(rec["yaml"], rec.get("params") or {}, rec["seed"])
            st.rerun()
        with st.expander("YAML de esta grabación"):
            st.code(rec["yaml"], language="yaml")
