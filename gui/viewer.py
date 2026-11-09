"""viewer.py - Construye el visor interactivo (HTML + D3.js) a partir de una grabación.

El visor es una página autocontenida (D3 incluido, no necesita internet).
Sirve tanto para incrustarlo en Streamlit como para guardarlo como .html independiente.
"""
import json
from pathlib import Path

ASSETS = Path(__file__).parent / "assets"


def build_html(recording: dict) -> str:
    html = (ASSETS / "viewer.html").read_text(encoding="utf-8")
    data = json.dumps(recording, ensure_ascii=False).replace("</", "<\\/")   # seguro dentro de <script>
    return (html.replace("/*__CSS__*/", (ASSETS / "viewer.css").read_text(encoding="utf-8"))
                .replace("/*__D3__*/", (ASSETS / "d3.min.js").read_text(encoding="utf-8"))
                .replace("/*__JS__*/", (ASSETS / "viewer.js").read_text(encoding="utf-8"))
                .replace("/*__DATA__*/null", data))
