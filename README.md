# Simulador de entosis con P-sistemas (alfa 3)

Simulador de **entosis** (una célula se internaliza en otra) basado en **computación con membranas**
(P-sistemas). Entrada: un fichero YAML con la estructura y las reglas del sistema. Salida: una simulación
paso a paso que se puede ver, estudiar regla a regla y guardar.

```
YAML (+ parámetros + semilla) ──▶ transductor ──▶ objetos del modelo ──▶ motor (Simulator) ──▶ Recorder
                                                                                            │
                          grabación autocontenida (dict/JSON) ◀──────────────────────────────┘
                             ├─▶ visor interactivo (D3.js)      ├─▶ tablas y gráficos (pandas)
                             ├─▶ mapa de dependencias (Graphviz)└─▶ "Explicar" (reconstruye estados y reevalúa reglas)
```

## 1. Puesta en marcha (Windows PowerShell, Python ≥ 3.10)

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py                                   # interfaz gráfica
python run_cli.py templates\01_entosis_2_celulas.yaml            # solo terminal
python tests\test_engine.py                                      # pruebas
```

## 2. Estructura del proyecto

| Ruta | Qué contiene |
|---|---|
| `psystem/model.py` | **Datos**: `Membrane`, `Rule`, `Item`, `Condition`, `Need`, `ChargeCheck`, `Partner`, `Engulf`, `SetCharge`, `Record`, `PSystem`, `link()`. Sin lógica de simulación. |
| `psystem/refs.py` | **Referencias relativas** (`self`, `parent`, `child:Vacuole`, `partner`…): `resolve()` y `check_ref()`. |
| `psystem/transducer.py` | **YAML → modelo**: parámetros `${…}`, semilla, tipos, población, variabilidad, vecindad, validación con mensajes claros. |
| `psystem/engine.py` | **Motor** `Simulator`: ruleta, máximo paralelismo, retardos, planificar/aplicar reglas, sucesos, `explain()`. |
| `gui/recorder.py` | Envuelve al `Simulator` y **graba cada paso** con todo el detalle. |
| `gui/analysis.py` | Tablas, mapa de dependencias (DOT) y avisos, calculados desde una grabación. |
| `gui/explain.py` | Reconstruye el estado de cualquier paso y explica una regla con el código del motor. |
| `gui/viewer.py` + `gui/assets/` | Visor HTML/D3 (`viewer.html/.css/.js`; `d3.min.js` incluido: no necesita internet). |
| `app.py` | Interfaz Streamlit: barra lateral + 7 pestañas. |
| `templates/` | YAML de ejemplo (§10). |
| `tests/test_engine.py` | Pruebas del motor (sin dependencias extra). |
| `run_cli.py` | Ejecución por terminal. |

Regla de modularidad: **`psystem/` no conoce la interfaz** y **`gui/` solo lee grabaciones** (dicts). Se puede
cambiar la interfaz entera sin tocar el motor, y al revés.

## 3. Modelo de computación

- **Membranas** en árbol. La raíz es el **medio** (`SK`); no se puede disolver.
- Cada membrana tiene un **multiconjunto de objetos** (letras: `P`, `a`…), una **carga** (0 o 1) y **reglas**.
- Una membrana puede tener un **tipo** (etiqueta, p. ej. `Cell`, `Vacuole`). Las reglas se escriben **una vez por tipo** y las
  comparten todas las membranas de ese tipo. Una célula es una membrana `Cell` que contiene una `Vacuole`.
- **Todas las células son iguales**: quién invade a quién y el destino de cada internalización lo decide la competencia entre
  reglas (ruleta), no el tipo de célula.
- **Tiempo discreto**: una regla aplicada se ejecuta en un paso; los productos pueden tardar más (`delay`).
- **Azar**: ruleta entre reglas (`weight`), elección del compañero, orden de las membranas y variabilidad inicial. Todo con una
  única semilla: misma semilla + mismo YAML + mismos parámetros = misma simulación.
- **Dos niveles de relación entre células**: *anidamiento* (cell-like: una célula dentro de la vacuola de otra) y *vecindad*
  (tissue-like: enlaces de contacto entre células libres).

## 4. Especificación del YAML

```yaml
params:                     # (opcional) parámetros con deslizador en la interfaz; se usan como ${nombre}
  promotores: {value: 20, min: 0, max: 60, step: 1, label: "Promotores P"}

system:
  name: Nombre              # opcional
  max_steps: 20             # máximo de pasos (por defecto 50)
  seed: 1                   # semilla; sin 'seed' se elige una aleatoria y queda guardada en la grabación
  variability: false        # true = aplicar los bloques 'variability' de la población (por defecto false)

  neighborhood:             # (opcional) vecindad entre las células de un tipo
    type: Cell
    parent: SK              # (opcional) solo las células hijas de esta membrana
    grid: {cols: 8, diagonals: false}     # rejilla: las células, en orden, rellenan las filas
    links: [[C1, C10]]                    # enlaces explícitos extra

  types:                    # plantillas de membrana
    Cell:
      objects: {a: 3, b: 2} # objetos iniciales de cada instancia
      charge: 0             # carga inicial (0 o 1)
      children: [Vacuole]   # tipos de hijos que se crean con cada instancia
      rules: { ... }        # reglas (§4.2)
    Vacuole: { rules: { ... } }

  membranes:                # membranas sueltas (p. ej. el medio); pueden llevar sus propias reglas
    - {name: SK, objects: {P: ${promotores}, Q: 3}}
    - {name: X, parent: SK, charge: 1, objects: {...}, rules: { ... }}   # sin 'parent' = es el medio (solo una)

  population:               # N copias de un tipo
    - type: Cell
      count: 100
      parent: SK
      prefix: C             # nombres C1…C100 (por defecto "<Tipo>_"); sus hijos: C1_Vacuole…
      variability:          # opcional; solo actúa si system.variability: true
        objects: {a: [0, 3]}   # cada célula recibe un entero aleatorio en [0, 3] de 'a'
        charge: [0, 1]         # y una carga inicial aleatoria
```

**Nombres**: únicos y sin puntos ni espacios. En YAML, `y n yes no on off` sin comillas se leen como booleanos: el transductor
avisa; escríbelos entre comillas (`'n'`).

### 4.1 Parámetros (`${nombre}`)
El bloque `params:` declara parámetros con `value` (por defecto), `min`, `max`, `step` y `label`. Antes de leer el YAML, cada
`${nombre}` se sustituye por su valor, así que vale en cualquier sitio (objetos, pesos, retardos, `count`…). La interfaz crea un
deslizador por parámetro. Un `${…}` no declarado da error.

### 4.2 Reglas

```yaml
rules:
  nombre_regla:
    weight: 3                 # peso en la ruleta (por defecto 1; 0 = nunca se elige)
    delay: 2                  # pasos extra hasta que llegan los productos (por defecto 0)
    partner: Cell             # opcional: necesita un compañero. Forma larga:
    # partner: {type: Cell, via: neighbors, charge_weight: {0: 4, 1: 1}}
    condition:                # opcional; todas deben cumplirse
      from_step: 3            #   no actúa antes de este paso            until_step: 10 (ni después)
      free: true              #   self es hija directa del medio (célula libre)
      needs: [{at: parent, object: Q, min: 2, max: 5}]    # umbrales (min por defecto 1, o 0 si solo das max; max opcional)
      charge: [{at: self, is: 1}]                         # carga de una membrana: is: 0, 1 o [0, 1]
      empty: [self.child:Vacuole]                         # estas membranas no contienen membranas
    input:                    # objetos que se CONSUMEN (todos deben existir)
      - {object: a, number: 1}                            # at: self por defecto
      - {object: P, number: 2, at: parent}
    output: [{object: L, number: 2, at: partner.child:Vacuole}]       # objetos que se PRODUCEN
    engulf: {cell: self, into: partner.child:Vacuole}                 # mueve una membrana (con su contenido) dentro de otra
    dissolve: [child:Cell, child:Cell.child:Vacuole]                  # membranas que se DISUELVEN (en este orden)
    set_charge: [{at: self, to: 0}]                                   # to: 0, 1 o flip (invertir)
    record: {event: death_internal, cell: child:Cell, other: parent}  # suceso a registrar
```

Una regla necesita al menos un `input`, `output`, `engulf`, `dissolve`, `set_charge` o `record`.
Compatibilidad: `target` ≡ `at` en `output`; en `needs`, `membrane` ≡ `at` y `number` ≡ `min`.

### 4.3 Referencias relativas (`refs.py`)
Una referencia dice "a qué membrana me refiero", partiendo de la membrana donde vive la regla (`self`):

| Referencia | Significa |
|---|---|
| `self` | la propia membrana (por defecto en `input`/`output`) |
| `parent` | su padre (desde una célula: el medio; desde una vacuola: su célula) |
| `child:Vacuole` | su primer hijo de tipo `Vacuole` |
| `partner` | el compañero elegido por la regla (solo si declara `partner`) |
| `parent.parent`, `child:Cell.child:Vacuole`, `partner.child:Vacuole` | pasos encadenados con puntos |
| `SK` | un nombre concreto de membrana (para membranas sueltas) |

Si una referencia no apunta a nada en ese momento (p. ej. `child:Cell` en una vacuola vacía), **la regla no se aplica**.

### 4.4 Qué significa cada campo
- **`input` / `output`**: consumir y producir objetos en cualquier membrana alcanzable por referencia.
  Con retardo, el input se gasta **ya** y el output llega más tarde (`delay`).
- **`needs`**: umbral que se *comprueba* sin gastar el objeto (catalizador / permiso / inhibidor con `max: 0`). `min` vale 1 por defecto
  ("tiene que haber"), pero **0 si solo das `max`** ("como mucho"; el 0 cuenta, así una regla de síntesis `max: 3` puede reponer desde 0). Se evalúa con los
  recuentos del momento: como los productos llegan al final del paso, un `max` **no limita el total** que producen varias
  aplicaciones seguidas dentro del mismo paso.
- **`engulf`**: mueve `cell` dentro de `into`. No se aplica si `into` ya es el padre de `cell` ni si `into` está dentro de `cell` (ciclos).
- **`dissolve`**: la membrana **desaparece y sus objetos se destruyen** (la célula se descompone). Las membranas que contenía pasan
  a su padre (por eso una célula interna queda libre si muere su huésped). El medio no se disuelve.
- **`set_charge`**: cambia la carga (0/1) de una membrana. **`charge`** (en `condition`) exige un valor de carga.
- **`record`**: añade un suceso `{t, event, cell, other}` al registro; los nombres se fijan al aplicar la regla, antes de que algo
  se disuelva. El nombre del suceso es libre (`internalization`, `escape`, `death_internal`…).
- **`partner`**: la regla necesita un compañero de ese tipo (p. ej. el huésped). `via: siblings` (por defecto) = cualquier hermana;
  `via: neighbors` = solo las vecinas en contacto. `charge_weight: {carga: peso}` pondera la elección según la carga del candidato
  (peso 0 = nunca).

## 5. Semántica de la simulación (`engine.py`)

**Un paso** (`Simulator.step()`):
1. `t += 1`. Las membranas se recorren en **orden aleatorio**.
2. En cada membrana se repite, **mientras se pueda**: calcular las reglas aplicables (`_find_plan`), elegir **una con una ruleta**
   proporcional a su `weight`, y aplicarla. Es el **máximo paralelismo** (se aplica todo lo que se pueda) con reparto justo entre
   reglas rivales: si dos reglas compiten por los mismos objetos, cada aplicación se sortea según los pesos.
3. Una regla **sin `input`** (síntesis) se aplica como mucho **una vez por paso y membrana** (si no, produciría infinito).
4. Los **productos** llegan al final del paso `t + delay` (con `delay: 0`, al final de este paso: se pueden usar en el siguiente).
   Mientras tanto están "en curso" y se ven en el visor. Si su membrana se disuelve antes, se pierden.
5. **Parada**: si en un paso no se aplicó ninguna regla, no hay productos en curso y ninguna regla espera a su `from_step`, el
   sistema se detiene ("ninguna regla aplicable"); si no, se para en `max_steps`. Una salvaguarda lanza error si una membrana
   aplica más de 100 000 reglas en un paso (bucle infinito).

**Cada aplicación de regla** tiene tres piezas:
- `_conditions()`: generador con **todas** las comprobaciones (tiempo, `free`, `empty`, `needs`, `charge`, objetos a consumir,
  existencia de destinos, validez de `engulf`/`dissolve`). Es la única fuente de verdad: `_plan()` para en la primera que falla y
  `explain()` las muestra todas.
- `_build()`: resuelve las referencias y construye el `Plan` (qué consume, produce, mueve, disuelve, carga y registra).
- `_apply()`: ejecuta el plan de forma **atómica** y anota el evento con su detalle.

**Compañeros** (`candidates()`): para una regla con `partner` se prueban hasta 25 candidatos (`MAX_PARTNER_TRIES`; con ≤ 25 se prueban
todos). Elección uniforme o, si hay `charge_weight`, con ruleta sin reemplazo según la carga del candidato. El conjunto de candidatos
se define en `_pool()`: es el único sitio que habría que tocar para otra definición de vecindad.

**Vecindad** (`neighborhood`): cada célula tiene una lista de contactos (`Membrane.contacts`). La rejilla (`grid`) crea enlaces con la
vecina de la derecha, la de abajo y, con `diagonals: true`, las diagonales. Con `via: neighbors`, un candidato es válido si es contacto,
está vivo y es hermano de `self` (es decir, **libre**). Consecuencias, sin código extra:
- una célula internalizada no tiene vecinas disponibles mientras esté dentro (su contacto ya no es hermano);
- una célula muerta pierde sus enlaces para siempre;
- una célula que **escapa** recupera los contactos que sigan libres y **se hace vecina de su ex-huésped** (`move_membrane`);
- si muere el huésped y la interna queda libre, recupera sus contactos propios que sigan libres.

**Polarización**: carga 0/1 por membrana. Intervienen como *condición* (`condition.charge`), como *acción* (`set_charge`) y como *peso*
en la elección de compañero (`partner.charge_weight`). El significado biológico de 0 y 1 lo decide el experto; el motor solo las
trata como dos estados.

**Sucesos**: `record` → `Simulator.fates`; `fate_counts()` los cuenta.

**Rendimiento** (plantilla 05 escalada, promotores = 60 % de las células): 100 células 0,05 s · 500: 0,3 s · 1000: 1,1 s.

## 6. Catálogo de objetos de las plantillas (placeholders)
El experto aún no ha definido qué componentes interactúan: los objetos son **letras inventadas**, fáciles de sustituir.

| Objeto | Dónde | Papel en las plantillas 07 y 10 |
|---|---|---|
| `a` | célula | energía / recurso interno (se sintetiza y se transforma en `R`) |
| `R` | célula | contractilidad (nivel graduado de ROCK1): se gasta al invadir (2) y para escapar (2); decae si hay exceso |
| `P`, `Q` | medio | promotores: `P` se gasta al invadir, `Q` solo da permiso |
| `M` → `A` → `L` | vacuola | maduración tras la internalización: señal → acidificación → lisosomas |
| `b` | célula | objeto propio sin efecto (rellena el contenido) |

## 7. Grabación (`gui/recorder.py`)
Dict JSON **autocontenido**:
```
name, max_steps, seed, status, fate_counts
yaml, params                       # para reproducir y para "Explicar"
rule_defs : {"r0": {name, text, cond, weight, delay, owner, io:{inputs,outputs,gates,acts}}, ...}   # cada regla, una vez
membranes : {nombre: {type, rules: ["r0", ...]}}     # todas las que han existido
layout    : {nombre: [col, fila]}                    # casillas de la rejilla (si hay vecindad)
links     : [[a, b, t0], ...]                        # contactos y paso en que aparecen
frames    : [{t, parents:{membrana: padre}, objects:{membrana:{objeto:n}}, charges:{membrana: 1},
              pending:[{at, obj, n, due}],
              events:[{membrane, rule, times, consumed:[{at,obj,n}], produced:[{at,obj,n,due}],
                       actions:[...], partners:[...], checks:[...]}],
              fates:[{event, cell, other}]}, ...]
```
`parents` solo contiene las membranas que **existen** en ese paso. `checks` son las condiciones cumplidas, tal y como se evaluaron
al aplicar la regla (en el momento exacto, con el estado a mitad de paso).

## 8. Interfaz (`app.py`)

**Barra lateral**: plantilla, YAML editable, **deslizadores de parámetros** (si el YAML tiene `params`), semilla (vacío = la del
YAML o una aleatoria), *Simular* (simula hasta el final y graba) y abrir una grabación `.json`.

**Visor** (D3.js). El medio es el espacio; cada célula libre es un círculo; lo que contiene se dibuja anidado. Con vecindad, las
células se colocan en su rejilla y se dibujan los enlaces (naranja = enlace nuevo, p. ej. tras un escape).
- *Navegación*: rueda = zoom · arrastrar el fondo = desplazar · **arrastrar una célula = moverla**. ⏮ ◀ ▶ ▶| ⏭, deslizador de t=0 al
  final, velocidad, atajos ←/→/espacio, y **◆◀ ▶◆** para saltar al suceso anterior/siguiente.
- *Línea de tiempo* (bajo la barra): barras = reglas aplicadas en cada paso; puntos de colores = sucesos; clic para saltar.
- *Color*: total de objetos, profundidad, **estado** (libre / huésped / internalizada), **destino** (último suceso de la célula),
  **carga**, o la cantidad de un objeto concreto. Las células con carga 1 llevan el borde naranja. Buscador: atenúa lo que no coincide;
  Enter centra la vista.
- *Panel de una membrana* (clic) — pensado para estudiar las reglas:
  - **Reglas aplicadas en el paso t** (tarjetas verdes): veces, peso, retardo, compañero elegido, **condiciones cumplidas** (✔),
    **qué consumió** y **qué produjo** (con el paso de llegada si hay retardo) y las acciones realizadas.
  - **Objetos**: cantidad, variación y **origen de cada cambio** ("−2 invade (C1), +4 make_R (C1)"), incluidas las reglas de otras membranas.
  - Productos **en curso** por retardo, **todas sus reglas** (con veces aplicadas), **actividad a lo largo del tiempo** (clic en un paso salta
    a él), evolución de sus objetos y su historial de posición. Funciona también para membranas ya disueltas.
  - Sin selección, el panel resume el paso (reglas agrupadas, movimientos, disoluciones, sucesos), apto para miles de membranas.
- *Exportar*: **SVG** y **PNG** de la vista actual y **Vídeo** (WebM) de toda la evolución. Se generan en el navegador; dentro de
  Streamlit el iframe puede bloquear las descargas, y en ese caso hay que usar el visor independiente (`.html`, pestaña Grabación). La
  grabación de vídeo depende de `MediaRecorder` (Chrome/Edge/Firefox) y **no se ha probado en un navegador real**.

**Pestañas**
- **Membranas**: tabla de todas las membranas en el paso elegido (tipo, padre, profundidad, carga, objetos, reglas) con filtros y detalle.
- **Eventos**: reglas aplicadas con filtros (qué consumió, produjo, compañero y acciones), cambios de estructura y uso de reglas por tipo.
- **Resultados**: nº de cada suceso con gráfica de barras, tabla de sucesos con las células implicadas y secuencia de sucesos por célula.
- **Mapa de reglas**: grafo objetos ↔ reglas por tipo (como la Fig. 4 del artículo de P-sistemas de tu documentación) y **avisos** estáticos:
  objetos exigidos que nunca existen, objetos producidos que nadie usa y reglas nunca aplicadas.
- **Explicar**: eliges paso, membrana y regla; se reconstruye el estado al **inicio** del paso y se muestran las condiciones con ✅/❌
  (y, con compañero, un escenario por candidato) y las reglas que competían en la ruleta. Limitación: dentro de un paso otras reglas pueden
  haber cambiado objetos, estructura o cargas antes; para una regla que sí se aplicó, las condiciones exactas están en el visor.
- **Grabación**: descargas `.json` (reabrir en la app) y visor `.html` independiente; YAML, parámetros y semilla; *Re-simular*.

## 9. Pruebas (`tests/test_engine.py`)
- **Invariantes de la entosis** (240 simulaciones, 8 plantillas × 30 semillas): cada internalización se resuelve una sola vez (muerte **o**
  escape, nunca las dos); nadie muere o escapa sin haber entrado; una célula muerta desaparece con su vacuola; no hay anidamiento; no
  quedan restos de `L`; una célula escapada vuelve al medio.
- **Funciones nuevas**: ruleta (pesos 9:1 ⇒ ~90 %; peso 0 ⇒ nunca), retardos (consumo inmediato, llegada diferida), reglas de síntesis
  (una vez por paso), carga (condición, acción y rechazo de valores ≠ 0/1), vecindad (solo se invade a vecinas; contactos al escapar),
  parámetros (sustitución y rechazo de desconocidos), reproducibilidad por semilla y que `explain()` coincide con el motor.

## 10. Plantillas (`templates/`)

| Fichero | Contenido |
|---|---|
| `01_entosis_2_celulas.yaml` | 2 células iguales y la regla genérica de invasión (la referencia comentada). |
| `02_poblacion_10.yaml` | 10 células con promotores limitados. |
| `03_control_sin_promotores.yaml` | Control negativo (P = 0): no ocurre nada. |
| `04_test_comunicacion.yaml` | Membranas sueltas, máximo paralelismo y envío entre membranas (sin tipos). |
| `05_poblacion_100.yaml` | 100 células; cambia `count` para otras escalas. |
| `06_variabilidad.yaml` | Variabilidad inicial de objetos activada. |
| `07_objetos_y_retardos.yaml` | Síntesis, transformación, degradación, retardos y ruleta; maduración M → A → L; el escape consume `R` de la célula interna. |
| `08_polarizacion.yaml` | Carga 0/1 aleatoria: condición dura (solo invade con carga 1), pesos al elegir huésped y `set_charge` al internalizar. |
| `09_vecindad_rejilla.yaml` | 64 células en rejilla 8×8; solo se invade a vecinas. |
| `10_modelo_completo.yaml` | Todo junto (objetos, retardos, ruleta, carga, rejilla 6×6 con diagonales) con **3 parámetros** con deslizador. |

## 11. Cómo ampliar
- **Otra definición de vecindad** (distancias, posiciones, contacto dinámico): reescribir `Simulator._pool()`; el resto no cambia.
- **Nueva acción** (p. ej. dividir una célula): campo en `model.Rule`, lectura en `transducer._parse_rule`, comprobaciones en
  `engine._conditions()`, construcción en `_build()`, ejecución en `_apply()` y texto en `recorder.describe_rule()` / `rule_io()`.
- **Nueva condición**: campo en `model.Condition` + lectura en el transductor + un `yield` en `_conditions()` (así `explain()` la muestra sola).
- **Nuevas métricas/pestañas**: funciones en `gui/analysis.py` (reciben la grabación) y una pestaña en `app.py`. Si necesitan datos nuevos por paso,
  añadirlos en `Recorder._snapshot()`.
- **Otra interfaz**: `parse_text` → `Simulator` → `Recorder.to_dict()`; todo lo demás es opcional.

## 12. Decisiones y limitaciones actuales
- **Una sola ruleta por membrana**: reglas de membranas distintas no compiten entre sí salvo por el orden aleatorio de las membranas
  (p. ej. varias células disputándose los `P` del medio).
- **Promotores globales**: `P` y `Q` son un fondo común del medio (sin gradientes espaciales).
- **Carga de 2 estados** (0/1), sin significado biológico fijado.
- No hay anidamiento porque las *reglas* de invasión lo impiden (invasor y huésped libres y con vacuola vacía); el motor sí lo admitiría.
- Si muere el huésped, la célula interna (si la hay) queda libre en el medio; para que muera con él, añadir su `dissolve` a `kill_host`.
- Una célula que escapa o queda libre puede volver a invadir si quedan promotores.
- `needs` con `max` no limita el total producido en un mismo paso (los productos llegan al final).
- Los círculos son SVG: fluido hasta unos cientos de células (con más habría que pasar a Canvas). La grabación guarda un frame por paso con todos
  los objetos: crece linealmente con pasos × membranas.
- Fuera del alcance de esta versión (descartado o pendiente): experimentos repetidos con estadísticas, calibración con datos de imagen,
  división celular y persistencia como destinos, comparación de dos ejecuciones y render en Canvas.
