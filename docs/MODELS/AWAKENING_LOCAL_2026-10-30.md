# Despertar autónomo LIMITADO con un modelo local (K2)

> Decisión del Operador, 2026-10-30: acepta K2-Horizon-7B como **fallback** para
> un despertar autónomo **acotado**. La confianza no es la misma que con un modelo
> en la nube, así que el diseño no se apoya en la confianza: se apoya en un
> **guardia mecánico** y en un alcance que no puede hacer daño.

## Qué se probó (dos modelos, el mismo material)

| | Spark 4B | **K2 7B** |
|---|---|---|
| Juicio sin herramientas (log de despertar) | correcto, 8,5 s, 82 tok/s | correcto y **más útil**, 10,4 s, 51 tok/s |
| Bucle real en opencode (leer estado → escribir log) | 4 vueltas perdidas buscando el handshake; se autocorrigió un `git` mal escrito | **directo**, `git -C … --format='%H %ad %s'` a la primera |
| Uso del material | enumera | enumera (mejor) |
| **Decisión** | `[pending]` (honesto) | **tautología** ("seguir con el plan acordado") |
| Salto de idioma | no | **sí**, al cerrar (responde en inglés) |
| Escritura | 1 vez | 2 veces (escribió, releyó, reescribió) |

**Ninguno de los dos decide.** Los dos transcriben con precisión y no saltan el
hueco hacia arriba: la conclusión que no está en ningún fichero —"mi C3b era
redundante y `next` tenía un agujero"— no la produce ninguno.

## El alcance: lo que puede y lo que no

**Puede**
- Leer estado del Búnker, jobs, señales, inbox, planner del desk y el repo.
- Ejecutar `git log` / `git status` / `git branch` (lectura).
- **Escribir UN fichero**: `<desk>/awakening/<YYYYMMDD_HHMM>.log`.

**No puede** (y no depende de su voluntad: no se le dan herramientas para ello)
- Lanzar, pausar o cancelar jobs. No toca la cola.
- Hacer commit, push ni cambiar de rama.
- Escribir en memoria (Memento, Qdrant) ni en configuración.
- Llamar a la red.

**Presupuesto:** 12 llamadas a herramientas y 10 minutos de reloj. Si los agota
sin cerrar el log, se abandona — sin reintento automático.

## El guardia: mecánico, no moral

`scripts/awakening_verify.py` extrae del log las anclas **verificables** y las
comprueba:

| Ancla | Comprobación |
|---|---|
| hash de commit | `git cat-file -e <hash>^{commit}` en el repo |
| ruta absoluta | existe en disco |
| rama citada | `git rev-parse --verify` |
| id de job | fichero de estado con ese prefijo (si no, **no verificable**) |

Tres cestas: **verificadas**, **no verificables** y **falsas**. El log se rechaza
sólo si hay una falsa demostrable. Un guardia que grita en falso se ignora — y se
comprobó: la primera versión marcaba como inventadas la fecha `20261029` y dos ids
de job caducados, **también en mi propio log**. Se corrigió antes de publicarlo.

Verificado sobre los tres logs reales:

| Log | Verificadas | No verificables | Falsas |
|---|:-:|:-:|:-:|
| Despertar propio (2026-10-29 20:00) | 10 | 2 | **0** |
| K2 en opencode | 1 | 0 | **0** |
| Spark en opencode | 1 | 0 | **0** |

**Un log con una sola ancla verificable no es un despertar, es un resumen.** El
contador de anclas sirve, por sí solo, como medida de calidad: mi log tiene 10.

## Cómo se usa (y cómo se marca)

1. Se lanza como fallback: cuando el despertar primario no puede correr, o a mano.
2. El log nace con `modo: degradado` en el frontmatter y su `decisión` **no se
   acepta como decisión** salvo que sea mecánica ("no hay nada que hacer").
3. `awakening_verify.py` decide si el log es aceptable. Si falla, el fichero se
   conserva (es evidencia) pero **no cuenta como despertar**.
4. El Operador revisa los logs en modo degradado. No hay promoción automática.

## Lo que este diseño NO resuelve

- **El criterio.** Un 7B no juzga; ordena. El despertar degradado sirve para *no
  perder el turno* cuando no hay nada mejor, no para decidir qué hacer con él.
- **El idioma.** K2 se va al inglés al quedarse sin aliento; el log hay que
  revisarlo antes de darlo por bueno.
- **La ventana.** El KV de K2 es ~76 KiB/token: 32K no cabe con sus 6,4 GB de
  pesos. En opencode, con su prompt de sistema, 16K es el techo real.
