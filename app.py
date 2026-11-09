"""app.py - Interfaz Streamlit (v2).   Ejecutar con:  streamlit run app.py

Flujo:  YAML -> parse_text -> Simulator -> Recorder (graba todos los pasos) -> grabación (dict)
La grabación alimenta TODAS las pestañas: el visor D3 y las tablas de análisis (gui/analysis.py).
Para cambiar el visor o añadir análisis no hay que tocar el motor: solo gui/.
"""
import json
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from gui import analysis
from gui.recorder import Recorder
from gui.viewer import build_html
from psystem import Simulator, parse_text

def show_html(html: str, height: int) -> None:
    """Incrusta una página HTML (st.iframe en Streamlit recientes, components.html en antiguos)."""
    if hasattr(st, "iframe"):
        st.iframe(html, height=height)
    else:
        components.html(html, height=height, scrolling=False)


TEMPLATES = sorted((Path(__file__).parent / "templates").glob("*.yaml"))

st.set_page_config(page_title="Simulador de entosis (alfa 2)", layout="wide")
st.title("Simulador de entosis con P-sistemas (alfa 2)")


# --------------------------------------------------- barra lateral ---
def simulate(text: str) -> None:
    try:
        rec = Recorder(Simulator(parse_text(text)))
        rec.run()                                       # simula hasta el final y graba todos los pasos
        st.session_state.recording = rec.to_dict()
    except Exception as e:                              # error de YAML -> mensaje, sin romper la app
        st.sidebar.error(f"Error en el YAML: {e}")


choice = st.sidebar.selectbox("Plantilla", TEMPLATES, format_func=lambda p: p.stem)
yaml_text = st.sidebar.text_area("YAML (editable)", choice.read_text(encoding="utf-8"),
                                 height=380, key=f"yaml_{choice.name}")
if st.sidebar.button("Simular", type="primary") or "recording" not in st.session_state:
    simulate(yaml_text)
st.sidebar.caption("Si el YAML no tiene `seed`, cada simulación da un resultado distinto.")

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

c1, c2, c3, c4 = st.columns(4)
c1.metric("Sistema", rec["name"])
c2.metric("Pasos grabados", T)
c3.metric("Membranas al inicio / final", f"{len(rec['frames'][0]['parents'])} / {len(rec['frames'][-1]['parents'])}")
c4.metric("Estado", rec["status"])

tab_view, tab_mem, tab_ev, tab_res, tab_save = st.tabs(["Visor", "Membranas", "Eventos", "Resultados", "Grabación"])


# ----------------------------------------------------------- Visor ---
with tab_view:
    st.caption("Rueda = zoom · arrastrar el fondo = desplazar · arrastrar una célula = moverla · "
               "clic = ver sus objetos, reglas y evolución · ▶ reproduce de t=0 al final.")
    show_html(build_html(rec), height=800)


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
        st.write(f"**Reglas aplicadas** ({len(view)} filas)")
        st.dataframe(view, hide_index=True, height=300)

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


# -------------------------------------------------------- Grabación ---
with tab_save:
    st.write("La grabación contiene, para cada paso desde t=0, la estructura de membranas, "
             "sus objetos y las reglas aplicadas. Con ella se puede volver a ver la evolución completa "
             "sin volver a simular.")
    s1, s2 = st.columns(2)
    s1.download_button("⬇ Grabación (.json) — reabrir en esta app", json.dumps(rec, ensure_ascii=False),
                       file_name=f"{rec['name']}.json", mime="application/json")
    s2.download_button("⬇ Visor independiente (.html) — se abre en cualquier navegador, sin Python",
                       build_html(rec), file_name=f"{rec['name']}_visor.html", mime="text/html")
    st.caption(f"Estado de la simulación: {rec['status']}")
