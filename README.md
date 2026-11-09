# Simulador de entosis con P-sistemas (alfa 3)

Simulador de **entosis** (una célula se internaliza en otra) basado en **computación con membranas**
(P-sistemas). Entrada: un fichero YAML con la estructura del sistema. Salida: una simulación paso
a paso que se puede ver y analizar en una interfaz interactiva.

```
YAML ──▶ transductor ──▶ objetos del modelo ──▶ motor (Simulator) ──▶ Recorder ──▶ grabación (dict/JSON)
                                                                                      ├─▶ visor interactivo (D3)
                                                                                      └─▶ tablas de análisis (pandas)
```

## 1. Puesta en marcha (Windows PowerShell, Python ≥ 3.10)

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py                                   # interfaz gráfica
python run_cli.py templates\01_entosis_2_celulas.yaml            # solo terminal
python tests\test_engine.py                                      # pruebas del motor
```

## 2. Estructura del proyecto

| Ruta | Qué contiene |
|---|---|
| `psystem/model.py` | **Datos**: `Membrane`, `Rule`, `Item`, `Condition`, `Need`, `Engulf`, `Record`, `PSystem`. Sin lógica de simulación. |
| `psystem/refs.py` | **Referencias relativas** (`self`, `parent`, `child:Vacuole`…): `resolve()` y `check_ref()`. |
| `psystem/transducer.py` | **YAML → modelo**: tipos, población, variabilidad, validación con mensajes claros. |
| `psystem/engine.py` | **Motor** `Simulator`: máximo paralelismo, planificar/aplicar reglas, sucesos. |
| `gui/recorder.py` | Envuelve al `Simulator` y **graba cada paso** (estructura + objetos + reglas + sucesos). |
| `gui/analysis.py` | Tablas pandas calculadas a partir de una grabación. |
| `gui/viewer.py` + `gui/assets/` | Visor HTML/D3 (`viewer.html/.css/.js`, `d3.min.js` incluido: no necesita internet). |
| `app.py` | Interfaz Streamlit: barra lateral + pestañas Visor, Membranas, Eventos, Resultados, Grabación. |
| `templates/` | YAML de ejemplo (ver §8). |
| `tests/test_engine.py` | Pruebas de invariantes del motor (sin dependencias extra). |
| `run_cli.py` | Ejecución por terminal. |

Regla de modularidad: **`psystem/` no conoce la interfaz** y **`gui/` solo lee grabaciones** (dicts).
Se puede cambiar la interfaz entera sin tocar el motor, y al revés.

## 3. Modelo de computación

- **Membranas** organizadas en árbol. La raíz es el **medio** (`SK`, la "piel"); no se puede disolver.
- Cada membrana tiene un **multiconjunto de objetos** (letras: `P`, `a`…) y **reglas**.
- Una membrana puede tener un **tipo** (etiqueta, p. ej. `Cell`, `Vacuole`). Las reglas se definen
  **una vez por tipo** y las comparten todas las membranas de ese tipo. Una célula es una membrana `Cell`
  que contiene una membrana `Vacuole`.
- **Todas las células son iguales** (mismo tipo, mismas reglas). Quién invade a quién, y qué destino
  tiene cada internalización, lo decide la competencia entre reglas, no el tipo de célula.
- **Tiempo discreto**: una regla aplicada tarda un paso. **Sin probabilidades**: la aleatoriedad viene
  solo del orden en que las reglas consumen los objetos y de la elección del compañero.

## 4. Especificación del YAML

```yaml
system:
  name: Nombre                # opcional
  max_steps: 20               # máximo de pasos (por defecto 50)
  seed: 1                     # semilla del azar; sin 'seed' (o null) cada ejecución es distinta
  variability: false          # true = aplicar los rangos 'variability' de la población (por defecto false)

  types:                      # plantillas de membrana
    Cell:
      objects: {a: 3, b: 2}   # objetos iniciales de cada instancia
      children: [Vacuole]     # tipos de hijos que se crean con cada instancia
      rules: { ... }          # reglas (ver §4.2)
    Vacuole: { rules: { ... } }

  membranes:                  # membranas sueltas (p. ej. el medio). Pueden llevar sus propias reglas
    - {name: SK, objects: {P: 2, Q: 3}}
    - {name: X, parent: SK, objects: {...}, rules: { ... }}   # 'parent' ausente = es el medio (solo una)

  population:                 # N copias de un tipo
    - type: Cell
      count: 100
      parent: SK
      prefix: C               # nombres C1…C100 (por defecto "<Tipo>_"); los hijos: C1_Vacuole…
      variability: {a: [0, 3]}   # opcional: 'a' aleatorio entre 0 y 3 por célula (solo si variability: true)
```

**Nombres.** Deben ser únicos y no llevar puntos ni espacios. En YAML, `y n yes no on off` sin comillas se leen
como booleanos: el transductor avisa; escríbelos entre comillas (`'n'`).

### 4.1 Referencias relativas (`refs.py`)

Una referencia dice "a qué membrana me refiero", partiendo de la membrana donde vive la regla (`self`):

| Referencia | Significa |
|---|---|
| `self` | la propia membrana (por defecto en `input`/`output`) |
| `parent` | su padre (desde una célula: el medio; desde una vacuola: su célula) |
| `child:Vacuole` | su primer hijo de tipo `Vacuole` |
| `partner` | el compañero elegido por la regla (solo si declara `partner: <Tipo>`) |
| `parent.parent`, `child:Cell.child:Vacuole`, `partner.child:Vacuole` | pasos encadenados con puntos |
| `SK` | un nombre concreto de membrana (útil para membranas sueltas) |

Si la referencia no apunta a nada en ese momento (p. ej. `child:Cell` en una vacuola vacía), **la regla no se aplica**.

### 4.2 Reglas

```yaml
rules:
  nombre_regla:
    partner: Cell                       # opcional: necesita un compañero (hermano de ese tipo, al azar)
    condition:                          # opcional; todas deben cumplirse
      from_step: 3                      #   no actúa antes de este paso
      until_step: 10                    #   ni después de este
      free: true                        #   self es hija directa del medio (célula libre)
      needs: [{at: parent, object: Q, min: 2, max: 5}]   # umbrales de objetos (min por defecto 1; max opcional)
      empty: [self.child:Vacuole]       #   estas membranas no contienen membranas
    input:                              # objetos que se CONSUMEN (todos deben existir)
      - {object: a, number: 1}          #   at: self por defecto
      - {object: P, number: 2, at: parent}
    output: [{object: L, number: 2, at: partner.child:Vacuole}]   # objetos que se PRODUCEN
    engulf: {cell: self, into: partner.child:Vacuole}   # mueve una membrana (con su contenido) dentro de otra
    dissolve: [child:Cell, child:Cell.child:Vacuole]    # membranas que se DISUELVEN, en este orden
    record: {event: death_internal, cell: child:Cell, other: parent}   # suceso a registrar
```

Una regla necesita al menos un `input`, un `engulf` o un `dissolve`.
Compatibilidad: `target` equivale a `at` en `output`, y en `needs` `membrane`≡`at`, `number`≡`min`.

**Acciones**
- **`engulf`**: mueve `cell` dentro de `into`. No se aplica si `into` ya es el padre de `cell` ni si `into`
  está dentro de `cell` (evita ciclos).
- **`dissolve`**: la membrana **desaparece y sus objetos se destruyen** (la célula se descompone). Las membranas
  que contenía pasan a su padre (por eso una célula interna queda libre si muere su huésped). El medio no se disuelve.
- **`record`**: añade al registro un suceso `{t, event, cell, other}`. Los nombres se fijan en el momento
  de aplicar la regla (antes de que algo se disuelva). El nombre del suceso es libre.

### 4.3 Variabilidad inicial
Con `variability: true`, cada instancia de la población recibe, para cada objeto del bloque `variability`,
un entero aleatorio uniforme en `[mín, máx]` (con la misma `seed`). Con `false` (por defecto) el bloque se ignora.

## 5. Semántica de la simulación (`engine.py`)

Un paso (`Simulator.step()`):
1. `t += 1`. Se barajan todos los pares (membrana, regla) de las membranas existentes.
2. Para cada par, mientras la membrana siga viva: `_find_plan()` busca una forma de aplicar la regla
   (**máximo paralelismo**: se repite mientras se pueda).
   - `_plan()` **comprueba todo sin modificar nada**: tiempo, `free`, `empty`, `needs`, que existan TODOS los objetos
     de `input`, que todas las referencias resuelvan, y las restricciones de `engulf`/`dissolve`.
   - `_apply()` ejecuta el plan de forma **atómica**: consume los `input`, mueve (`engulf`), disuelve y registra.
     Los `output` se **añaden al final del paso** (no pueden usarse hasta el siguiente; si su membrana se disolvió, se pierden).
3. Parada: si en un paso no se aplicó ninguna regla **y** ninguna espera a su `from_step`, el sistema se detiene
   ("ninguna regla aplicable"); si no, se para en `max_steps`.

**Compañeros** (`candidates()`): para una regla con `partner: Cell`, se prueban hasta 25 hermanos de ese tipo al azar
(`MAX_PARTNER_TRIES`; con ≤25 células se prueban todos). Hoy todas las células del medio son vecinas.
Para introducir **vecindad** (como en los sistemas P tisulares) basta con reescribir `candidates()` para que devuelva
solo las células en contacto; el resto del motor no cambia.

**Por qué no hay resultados contradictorios** (p. ej. "escapa y además muere"): las tres salidas de la vacuola
(`kill_inner`, `kill_host`, `escape`) exigen `child:Cell` (una célula dentro) y **consumen los 2 `L`**; en cuanto una se
aplica, las otras ya no pueden. Tras morir o escapar no quedan `L`, y una célula disuelta desaparece del sistema.
`tests/test_engine.py` lo comprueba en 160 simulaciones.

**Rendimiento** (aprox., plantilla 05 con P=60 % de células): 100 células 0,06 s · 500: 0,4 s · 1000: 0,9 s · 2000: 2,9 s.

## 6. Grabación (`gui/recorder.py`)

El motor solo conoce el estado actual. El `Recorder` hace una foto tras cada paso. La grabación es un dict (JSON):

```
name, max_steps, seed, status, fate_counts
rule_defs : {"r0": {name, text, cond, owner}, ...}     # cada regla, una vez (se comparten por tipo)
membranes : {nombre: {type, rules: ["r0", ...]}}       # todas las membranas que han existido
frames    : [{t, parents:{membrana: padre}, objects:{membrana:{objeto:n}},
              events:[{membrane, rule, times}], fates:[{event, cell, other}]}, ...]
```
`parents` solo contiene las membranas que **existen** en ese paso (las disueltas desaparecen). Se puede
guardar como `.json` (reabrir en la app) o como **visor `.html` independiente**.

## 7. Interfaz

**Barra lateral**: plantilla, YAML editable, botón *Simular* (simula hasta el final y graba), abrir grabación `.json`.

- **Visor**: el medio es el espacio; cada célula libre es un círculo; lo que contiene se dibuja anidado.
  Rueda = zoom · arrastrar fondo = desplazar · **arrastrar una célula = moverla** · clic = ficha (ruta, contenido, objetos con
  Δ, reglas con veces aplicadas, gráfica de sus objetos, historial de posición; sirve también para membranas ya disueltas).
  ⏮ ◀ ▶ ▶| ⏭ y deslizador de t=0 al final, velocidad, color por total/profundidad/objeto, buscador (Enter centra),
  atajos ←/→/espacio. El panel lista por paso las reglas, movimientos, disoluciones (✖) y sucesos (◆).
  Los círculos son SVG: fluido hasta unos cientos de células (con más habría que pasar a Canvas).
- **Membranas**: tabla de todas las membranas en el paso elegido (filtro por nombre/objeto/profundidad) con detalle al seleccionar.
- **Eventos**: reglas aplicadas (filtros), cambios de estructura (movimientos y disoluciones) y uso de reglas por tipo
  (incluye las que nunca se aplicaron).
- **Resultados**: nº de cada suceso (`internalization`, `death_internal`, `death_host`, `escape`…) con gráfica de barras,
  tabla de sucesos con las células implicadas y secuencia de sucesos por célula.
- **Grabación**: descargas `.json` y visor `.html`.

## 8. Plantillas (`templates/`)

| Fichero | Contenido |
|---|---|
| `01_entosis_2_celulas.yaml` | 2 células iguales y la regla genérica de invasión (la referencia comentada). |
| `02_poblacion_10.yaml` | 10 células con promotores limitados. |
| `03_control_sin_promotores.yaml` | Control negativo (P=0): no ocurre nada. |
| `04_test_comunicacion.yaml` | Membranas sueltas, máximo paralelismo y envío entre membranas (sin tipos). |
| `05_poblacion_100.yaml` | 100 células; cambia `count` para probar otras escalas. |
| `06_variabilidad.yaml` | Variabilidad inicial activada (`a` aleatorio en 0–3). |

## 9. Cómo ampliar

- **Vecindad / tejidos**: reescribir `Simulator.candidates()` (§5).
- **Nueva acción** (p. ej. dividir una célula): añadir el campo en `model.Rule`, leerlo en `transducer._parse_rule`,
  resolverlo en `engine._plan()` y ejecutarlo en `engine._apply()`; mostrarlo en `recorder.describe_rule()`.
- **Nueva condición**: campo en `model.Condition` + lectura en el transductor + comprobación en `_plan()`.
- **Nuevas métricas/pestañas**: funciones en `gui/analysis.py` (reciben la grabación) y una pestaña en `app.py`;
  no hace falta tocar el motor. Si necesitan nuevos datos por paso, añadirlos en `Recorder._snapshot()`.
- **Otra interfaz**: usar `parse_text` → `Simulator` → `Recorder.to_dict()`; todo lo demás es opcional.

## 10. Decisiones y limitaciones actuales

- No hay anidamiento: la regla `invade` exige que invasor y huésped sean libres y con vacuola vacía (es una decisión de las
  *reglas*; el motor sí admitiría anidar).
- Si muere el huésped, la célula interna (si la hay) queda libre en el medio; para que muera con él, añadir su `dissolve` a `kill_host`.
- Una célula que escapa o queda libre puede volver a invadir si quedan promotores `P`.
- La grabación guarda un frame por paso con todos los objetos: para muchos pasos × muchas membranas el `.json` crece linealmente.
- Aún no hay probabilidades ni tiempos de retardo por regla; la propuesta de métricas adicionales (estados por célula, línea
  temporal, tiempos clave, mapas de calor…) queda pendiente de decisión.
