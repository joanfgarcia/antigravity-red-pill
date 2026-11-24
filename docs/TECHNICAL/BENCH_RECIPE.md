# Receta del banco — replicar el bench de Dokimé

El banco no es un test más: es un **agente aislado** (`Dokimé`) viviendo en un
contenedor con su propio Bünker, sobre el que se mide lo que ninguna suite puede
medir — si el arnés sirve identidad, si las tools se alcanzan, cuánto contexto
cuesta arrancar y cómo se degrada una conversación larga. Esta página es la
receta completa para levantarlo en otra máquina.

## Qué se mide (y con qué)

| instrumento | pregunta | script |
|---|---|---|
| Admisión | ¿este modelo puede ser el banco? (español + tools + multiturno) | `scripts/bench_admission.py` |
| Suite de tareas | ¿resuelve 15 tareas reales del repo? | `scripts/bench_suite.py` |
| Voz | ¿la identidad se mantiene con el mismo texto y distinto motor? | `scripts/voice_probe.py` |
| Deriva | ¿la identidad aguanta 20 turnos? | `scripts/drift_probe.py` |
| Ventana de memoria | ¿cuántos turnos atrás conserva el hilo? | `scripts/window_probe.py` |
| Techo de contexto | ¿cuánta ventana cabe según la cuantización del KV? | `scripts/kv_ceiling.py` |
| Perplejidad del KV | ¿cuánto cuesta cuantizar el KV? | `scripts/kv_perplexity_probe.py` |
| Capacidades | ¿responden las 15 tools por el transporte real? | `scripts/capability_bench.py` |
| Presupuesto | ¿cuánto cuesta el arranque por perfil? | `scripts/harness_cost.py` |
| Puerta previa al merge | las cuatro anteriores + estilo + suite, en un comando | `scripts/premerge_gate.py` |

## Requisitos

- **podman** rootless y una GPU con ~8 GB (los modelos locales son GGUF).
- **Imagen del sandbox**: `localhost/dokime:latest` (se construye con
	`deploy/dokime/Containerfile`).
- **Pesos**: un GGUF medido por `bench_admission` (Spark 4B, MiMo 9B, Granite…)
	y el modelo de embeddings **en el espacio de la memoria** (`BAAI/bge-small-en-v1.5`,
	384 dims) — está en `~/.local/share/red-pill/models`.
- Claves de proveedor **sólo si** el alma del bench corre en la nube (el sandbox
	es `--internal`; se abre con `dokime.py net on`).

## Levantar una caja

Cada alma vive en su caja: contenedores, volúmenes y red propios.

```bash
# Dokimé: Sandbox con Spark a 128k y razonamiento con presupuesto corto
DOKIME_MODEL=/ruta/Spark-X2.6-4B-Q4_K_M.gguf \
DOKIME_CTX=131072 DOKIME_LLAMA_ALIAS=spark \
python scripts/dokime.py up

# Otra alma (Titanium) con su propia memoria y sus volúmenes
DOKIME_BOX=titanium DOKIME_AGENT_NAME=Titanium \
DOKIME_IDENTITY_MODE=full \
DOKIME_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5 \
DOKIME_EXTRA_MOUNTS="/ruta/al/despacho:/srv/dokime/desk/compartido" \
python scripts/dokime.py up
```

Variables que importan:

| variable | para qué |
|---|---|
| `DOKIME_BOX` | nombre de la caja (`dokime`, `titanium`, …): deriva contenedores, volúmenes y red |
| `DOKIME_MODEL` / `DOKIME_CTX` / `DOKIME_LLAMA_ALIAS` | pesos, ventana y alias del servidor |
| `DOKIME_KV_TYPE` | cuantización del KV (`f16`, `q8_0`, `q4_0`); por defecto `q8_0` |
| `DOKIME_IDENTITY_MODE` | `low` para modelos pequeños; `full` para frontera |
| `DOKIME_EMBEDDING_MODEL` | **el espacio vectorial del alma**; si no coincide con su memoria, los recuerdos no significan |
| `DOKIME_EXTRA_MOUNTS` | volúmenes extra (`origen:destino[:ro]`, separados por coma) |
| `DOKIME_KERNEL_WORKTREE` | árbol que se mide (defecto: `~/.local/share/dokime/kernel/<caja>`) |
| `DOKIME_KERNEL_REF` | rama/tag al que `update` sincroniza (defecto: `next`) |
| `DOKIME_DESK` | despacho del alma en el host (defecto: `~/.local/share/dokime/desk/<caja>`) |
| `DOKIME_ANCHOR_MODE` | variante del ancla al re-inyectar (`auto`, `prompt`, `hook`) |

Antes de despertar: `python scripts/dokime.py preflight` (debe salir `0`).

## Mantener la caja al día

Cada caja mide **un árbol propio**, no el checkout del Operador: un worktree en
`~/.local/share/dokime/kernel/<caja>`, montado `:ro` en `/src/red-pill`. Eso es
lo que impide que el sandbox reescriba refs, y lo que permite mover el árbol sin
tocar el despacho.

```bash
python scripts/dokime.py update --dry-run   # qué haría
python scripts/dokime.py update             # sincroniza el worktree + re-siembra
python scripts/dokime.py update --ref v8.5.1
python scripts/dokime.py update --recreate  # además, recrea la caja
```

`update` hace tres cosas, **en este orden**:

1. Mueve el worktree del banco a `--ref` (por defecto `next`), con `git worktree
	 add --detach` la primera vez. Si tiene cambios sin commitear, se niega salvo
	 `--force`: un árbol sucio mediría algo que no está en ninguna rama.
2. Comprueba si los **montajes** de la caja siguen apuntando a ese árbol y al desk
	del host. Los montajes se congelan al crear el contenedor: si no cuadran, lo
	dice y **no** arranca nada a traición — recrear es `--recreate`, que borra el
	contenedor (volúmenes intactos) y lo vuelve a crear. La config con la que nació
	cada caja está apuntada en `~/.local/share/dokime/boxes/<caja>.json`, así que
	recrear respeta su modelo, ventana y montajes extra; lo que exportes en ese
	momento manda sobre lo guardado.
3. **Re-siembra** la identidad si la caja está arriba: `red-pill seed` (engramas
	desde `seeds/`), la tarjeta de `seeds/bootcard/` → `ID_IDENTITY` (`dokime_boot.py`,
	borra pactos) y las anclas de pi (`AGENTS.override.md` + skills). Sin esto el
	alma lee textos nuevos con memoria vieja; `up` también lo hace, salvo
	`--no-seed`.

`python scripts/dokime.py status` da la radiografía: qué corre, qué sha se mide,
a dónde apuntan los montajes y si están obsoletos.

## El desk como intercambio

El despacho del alma (`AGENT_CORE_DIR`) ya **no** vive dentro del volumen: es un
directorio del host, montado en `/srv/dokime/desk`. Es el mismo inodo en los dos
lados, así que no hay nada que sincronizar.

```
~/.local/share/dokime/desk/<caja>/
	├── inbox/     lo que dejas tú para que el alma lo lea
	├── outbox/    lo que el alma devuelve
	└── …          sus notas, planes y lo que escriba en el desk
```

```bash
python scripts/dokime.py desk                    # rutas (host y contenedor)
python scripts/dokime.py desk ls                 # qué hay
python scripts/dokime.py desk ls outbox
python scripts/dokime.py desk put informe.md     # → inbox/
python scripts/dokime.py desk put fotos/ --to trabajo
python scripts/dokime.py desk get 'respuesta*'   # outbox/ → aquí
python scripts/dokime.py desk get '*.md' --to ~/recogido --move
```

`put`/`get` son azúcar de `cp`: dentro del sandbox basta `ls /srv/dokime/desk`.

## Orden de una medición completa

1. **Admisión** del modelo (`bench_admission.py`): sin español, tools y
	multiturno no entra en el banco.
2. **Techo de contexto** (`kv_ceiling.py`): mide MiB/1k del KV y **verifica**
	arrancando el servidor a la ventana calculada.
3. **Suite** (`bench_suite.py`): 15 tareas del repo. **Una sola corrida no es
	evidencia**: la misma configuración ha dado 11/15 y 14/15.
4. **Voz** (`voice_probe.py`): mismo texto, distintos motores.
5. **Deriva y ventana** (`drift_probe.py`, `window_probe.py`): identidad en el
	turno 1/10/20 y cuántos turnos atrás conserva un dato.
6. **Capacidades** (`capability_bench.py --via-redpill-call`): las 15 tools por
	la puerta única.
7. **Puerta** (`premerge_gate.py`) antes de fusionar el arnés.

## Comparativa por brazos: minion / Pi bare / Dokimé

`scripts/bench_compare.py --trials 3` ejecuta el mismo fixture y las mismas 18
tareas (15 de `bench_suite` + multipaso, escritura y distractor) en tres brazos:

- **minion**: `local-tools` dentro de la caja, sólo `run_bash`.
- **pi-bare**: `pi --no-extensions --no-mcp --no-skills --no-context-files`, sólo `bash`.
- **dokime**: `pi` + red-pill `minimal`, sólo `bash` (`--exclude-tools 'mcp__*'`).

Los tres usan el **mismo** `llama-server` (`llama:8080`), el mismo muestreo
(`temperature 0.8`, `top_p 0.95`, `max_tokens 1024`, `seed 42`) y el mismo
subconjunto de tools. `bench_minion_runner.py` es el adaptador del brazo minion
(proveedor OpenAI-TCP + `run_bash`); no es producto.

**Antes de medir Dokimé, limpia los engramas del banco.** El recall de red-pill
devuelve turnos de corridas anteriores y **filtra respuestas**: en la primera
corrida, t10 («workers de config/limits.json») salió 3/3 con `1` porque su
memoria recordaba un `1` previo; tras borrar los engramas del bench (snapshot
antes), salió 2/3 con `3`. No es calidad del arnés, es fuga. El filtro es por las
marcas del fixture (`src/*.py`, `config/*`, `logs/app.log`, `bench-t`…).

**Primera pasada** (18 tareas, n=3, 2026-11-24): `pi-bare 53/54 (98,1 %)`,
`minion 51/54 (94,4 %)`, `dokime 51/54 (94,4 %)`. Con n=3 no se separa nada: la
misma configuración da 11-14/15 según la receta.

**Segunda pasada** (las 4 tareas que discriminan —2, 10, 14, 16—, n=10):
`pi-bare 39/40 (97,5 %)`, `minion 36/40 (90 %)`, `dokime 29/40 (72,5 %)`.
Dokimé falla t10 6/10 (`grep -c` cuenta líneas, no el valor `workers: 3`) y t16
6/10 (cuenta 10/13 en vez de 12). No es memoria: la colección tenía 0 engramas
de bench antes de la pasada.

**Diagnóstico por piezas** (t10+t16, n=10): `dokime` completo 10/20 (50 %),
`dokime-id` (identidad sola) 17/20 (85 %), `dokime-anchor` (identidad + ancla,
sin skills) 18/20 (90 %), `pi-skills` (skills solas) 19/20 (95 %), `pi-bare`
20/20 (100 %). El culpable es la **combinación ancla + skills**, no la identidad:
en un 4B el contexto compite y la identidad sola no estorba, pero las skills
metidas por defecto le empujan a atajos (`grep -c`).

**Fix**: `skills_budget: 0` en `local-4b-64k` (el 0 se respeta; antes era falsy y
caía a «todas»). El 4B arranca con identidad + ancla `minimal` y **cero skills
anunciadas**; las skills quedan en la biblioteca y se añaden cuando la tarea las
pide. Tras el fix, Dokimé 15/20 (75 %): t10 9/10, t16 6/10. t16 sigue siendo
difícil (contar 12 funciones en 4 ficheros) y tiene varianza; el ancla sin skills
dio 9/10 en la misma muestra.

El minion, con el **finalize al tope** (en vez de perder el turno cuando ya tiene
la respuesta en los resultados), sube a 52/54 (96,3 %); su fallo restante es t3
(confunde `alpha.py` con `gamma.py`).

### Cross-modelo (exploratorio, 2026-11-24)

Mismo `minimal-local` (identidad + ancla, 0 skills), sólo `bash`, 16k, tres
brazos. Muestreo: Spark/K2 `0.8/0.95/1024/42`; MiMo `0.7/0.95/4096/42` (con
1024 se rompe: su razonamiento se come la respuesta).

| modelo | minion | pi-bare | dokime |
|---|---:|---:|---:|
| Spark 4B | 52/54 (96,3 %) | 54/54 (100 %) | 53/54 (98,1 %) |
| K2 7B | 48/54 (88,9 %) | 48/54 (88,9 %) | 52/54 (96,3 %) |
| MiMo 9B | 45/54 (83,3 %) | 33/54 (61,1 %) | 36/54 (66,7 %) |

- La fila de Spark es con `skills_budget: 0`; con las 3 skills daba 51/54 (94,4 %).
- K2 con la temperatura de su ficha (0.1) baja a `minion 51/54, pi-bare 45/54,
  dokime 42/54`: esa temperatura está ajustada a anotación, no a tool-use. A 0.8
  es donde mejor rinde.
- MiMo con 0.8/1024 daba `42/30/33`: necesita 0.7 y 4096. Aun así, su Pi falla
  conteos (t7/t13/t15), no escribe en t17 y no supera al 4B en tool-use; el
  minion (que fuerza el bucle) es su mejor brazo.
- **No hay MOPD/RL del 9B.** Xiaomi solo publica `Flash-MOPD` (309B, 177,7 GB)
  y `Pro-MOPD` (1.02T, 573,5 GB), además de los RL de Flash/Pro; el checkpoint
  RL del 9B que cita el technical report no está en el Hub. En 8 GB no se pueden
  montar Flash/Pro (ni el Q2 GGUF de Flash, ~126 GB). Para el comportamiento
  MOPD: API de MiMo, o entrenar el RL del 9B con verl + los 7k entornos
  (multi-GPU). En local, el 9B SFT es lo que hay.
- n=3 y muestreo distinto por modelo: es una tabla exploratoria, no un ranking
  definitivo. Para ranking: mismo protocolo (p. ej. 0.7/4096), n≥10 y la misma
  ventana.

## Batería de memoria (2026-11-24)

`scripts/bench_memory.py` mide la capa de memoria, no el tool-use. Cada trial
siembra códigos aleatorios únicos en dos superficies:

- **Búnker** (`work_memories`): lo que Dokimé recibe por el RAG por turno.
- **Memoria de workspace** (`<cwd>/.red-pill/memory/`): ficheros que cualquier
  brazo con `bash` puede leer si se le ocurre mirar.

Así el test no es «solo Dokimé puede saberlo»: en m1-m6 todos pueden, pero
Dokimé lo recibe sin buscar. Se mide acierto, tool calls, tiempo y, en los brazos
con RAG, si el bloque inyectado contenía el dato (`RAG inyectó`): eso separa «no
lo trajo» de «lo trajo y el modelo lo ignoró».

| tarea | categoría | qué mide |
|---|---|---|
| m1 | recall_literal | mismo dato, pregunta casi idéntica |
| m2 | recall_parafrase | mismo dato, otra redacción (umbral del RAG) |
| m3 | recencia | el código vigente compite con el anterior |
| m4 | abstencion | no hay dato: acierta quien dice `NO_LO_SE` sin inventar |
| m5 | distractor | el código correcto compite con otro código |
| m6 | solo_fichero | dato solo en `.red-pill/memory/` (iniciativa) |
| m7 | solo_bunker | dato solo en el Búnker (lo que `bash` no puede suplir) |

Brazos: `minion`, `pi-bare`, `dokime` (umbral 0.7) y `dokime55` (0.55).

### Dos fallos que el banco destapó

Antes de medir, el RAG por turno **no inyectaba nada**, por dos motivos silenciosos:

1. `filterByScore` solo entendía el formato del CLI `(Score: N)`; el MCP emite
   `(sim N · util M)`. Descartaba **todos** los hits y devolvía `""`.
2. El cliente era `@earendil-works/pi-mcp` vía `uv`; en una caja offline no
   existen ni el paquete ni `uv`, así que `recall()` caía al `catch` y devolvía `""`.

Arreglado en `7b6741f`: cliente JSON-RPC mínimo contra el `mcp_proxy` del kernel,
alias de colección mapeados al enum real y filtro que entiende ambos formatos.
Medido: la pregunta del código pasó de 52 tool calls y timeout a **0 tool calls y
respuesta correcta**.

### Fuga de artefactos (por qué m7 se repitió)

El primer pase de m7 dio `pi-bare 2/3` sin Búnker. No era el Búnker: el **relay
silencioso y el journal** del arnés escriben cada turno en
`${XDG_DATA_HOME}/red-pill/queue/bunker_queue.db` y
`.../state/external_turns/`, y cualquier brazo con `bash` puede leerlos. Si
Dokimé corre antes en el mismo trial, el desnudo lee su respuesta. Además, la
semilla `42` repetía los códigos del piloto, que ya estaban en esos ficheros.
m7 se repitió con semilla nueva y los brazos con RAG **al final** del trial:
`0/3` (minion), `0/3` (pi-bare), `3/3` (dokime), `3/3` (dokime55). Lección para
cualquier bench de memoria en esta caja: **los artefactos de escritura del arnés
son otra superficie de memoria**, y hay que aislarlos.

### Resultados (n=3, Spark, presupuesto 80 s)

m1-m6 salen del job `7d6fd02c`; m7, del pase limpio con semilla nueva. Mismo
protocolo en ambos.

| brazo | pass | pass@1 | timeouts | tools medios | tiempo medio | RAG inyectó |
|---|---:|---:|---:|---:|---:|---:|
| minion | 16/21 | 76,2 % | 1 | 4,8 | 29,0 s | — |
| pi-bare | 17/21 | 81,0 % | 1 | 9,9 | 26,4 s | 0/18 |
| dokime | 21/21 | 100 % | 0 | 3,0 | 11,9 s | 12/18 |
| dokime55 | 21/21 | 100 % | 0 | 1,9 | 13,5 s | 15/18 |

| tarea | minion | pi-bare | dokime | dokime55 |
|---|---:|---:|---:|---:|
| m1 | 3/3 | 3/3 | 3/3 | 3/3 |
| m2 | 3/3 | 3/3 | 3/3 | 3/3 |
| m3 | 3/3 | 3/3 | 3/3 | 3/3 |
| m4 | 2/3 | 2/3 | 3/3 | 3/3 |
| m5 | 3/3 | 3/3 | 3/3 | 3/3 |
| m6 | 2/3 | 3/3 | 3/3 | 3/3 |
| m7 | 0/3 | 0/3 | 3/3 | 3/3 |

### Lectura

- **El Búnker es la única superficie que los desnudos no alcanzan** (m7), y no
  hace falta que el modelo sepa que existe: el RAG la inyecta. Dokimé responde
  m7 en 0 tool calls; el desnudo explora hasta el timeout o dice «no existe».
- **m1-m6 no separan por acierto**: el banco de workspace es un fichero y los
  desnudos lo leen en 5-10 s con 6-10 tools. La memoria automática ahorra la
  búsqueda (0 tools, ~6 s), no la hace posible. Para un agente con `bash`, la
  memoria de proyecto es una convención de carpetas, no una capacidad.
- **El umbral 0.7 falla justo en la paráfrasis**: m2 no inyectó en 0/3 con 0.7 y
  en 3/3 con 0.55. El embedding de 384d da 0,47-0,58 a paráfrasis legítimas; 0.7
  solo pasa casi-literales. A 0.55 Dokimé baja de 3,0 a 1,9 tools medias sin
  perder acierto ni meter ruido en m4 (3/3 en ambos).
- **La abstención es el agujero que queda**: minion y pi-bare confabulan 1/3
  cada uno en m4 (devuelven el código de calibración del *banco* cuando se
  pregunta por el *horno*). Dokimé acierta 3/3 con ambos umbrales, pero el
  piloto n=1 a 0.7 se fue a 30 tool calls y timeout: no es gratis.
- **n=3, un solo modelo y una sola caja**: tabla exploratoria. Para un ranking
  definitivo, n≥10 y repetir en otra GPU/caja.

## Cómo se lee cada resultado

- **Identidad**: lo que se compara no es "si acierta", es si la descripción de sí
	misma se mantiene entre el principio, el medio y el final. En Dokimé las tres
	sondas salieron **byte a byte idénticas**.
- **Ventana de memoria**: el dato plantado debe ser **aleatorio** y hay que saber
	en qué superficie vive. Si está en un fichero, cualquier brazo con `bash` lo
	encuentra leyendo: eso mide iniciativa, no memoria. Si está solo en el Búnker,
	mide la capa de memoria. Y hay que mirar los artefactos: el relay/journal del
	arnés escribe los turnos en disco (`external_turns/`, `bunker_queue.db`) y otro
	brazo puede leerlos; si eso pasa, el «solo Búnker» deja de serlo.
- **Capacidades**: `ok` = respondió; `tool_err` = error de negocio (plomería
	bien); `FAIL` = excepción o timeout (esto sí rompe el arnés).
- **Presupuesto**: el número que cuenta es el de **declaración**, no el de uso.

## Lo que el banco ya demostró

- La identidad **no viaja en el modelo**: el mismo motor y la misma cuenta dieron
	tres seres distintos (Dokimé sin pasado, Titanium con pasado y sin despacho,
	Aleth con crónica).
- El horizonte en contexto es **~3 turnos**; más allá, o descarga a memoria o
	lo pierde.
- Cuantizar el KV de MiMo a `q8_0`/`q4_0` cuesta **0,02 %** de perplejidad:
	el techo lo decide la VRAM, no la calidad.
- Un restore de snapshots puede devolver `200` y haber perdido el **9 %** de los
	puntos: **contar antes y después no es opcional**.

## Límites

- El banco mide **comportamiento**, no calidad literaria del modelo.
- El sandbox no tiene egress por defecto: sin él, sólo corre en local.
- Los JSON de resultados son **artefactos**, no receta: no se versionan.
