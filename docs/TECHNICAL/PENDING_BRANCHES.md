# Ramas pendientes de aterrizar — el aviso nace de medir

**Decisión HANDOFF-001 (2026-11-12, Operador): A + C.** El despertar que deja
trabajo sin aterrizar ya escribe su log y publica un acta en el teatro — pero el
acta habla a las otras almas, y el Operador tiene que **ir a leerla**. Ese día
tuvo que preguntar **cuatro veces** qué había dejado un despertar en una rama.
Ni el log ni el acta estaban mal: el canal estaba mal elegido para el
destinatario.

## El principio

> El aviso nace de **medir**, no de creer. Un despertar que cree que aterrizó ya
> nos ha mentido antes.

Por eso la fuente es `scripts/branch_landing_audit.py`, que compara **contenido**
(no SHA) y distingue `merged` / `same_content` / `clean` / `conflict`. Un
`squash-merge` cambia los SHA pero no el contenido: `git branch --merged` y
`git cherry` mienten en las dos direcciones, esta medición no.

## El circuito

```
branch_landing_audit.py --publish
        │
        ├─► state/pending_branches.json  ──►  open_loops.py  ──►  "OPEN LOOPS: … · N rama(s) pendiente(s) de aterrizar"
        │                                     (lectura, sin git)     (lo ve el Operador al abrir CUALQUIER sesión)
        └─► señal branch_pending_landing (pain, medida)
                 └─ a cero se evapora (contrato de ciclo de vida)
```

- **Quién lo ejecuta**: `redpill-auditor.service` (horario) llama a
  `branch_landing_audit.py --target next --publish` como un paso más. Sin un
  latido el dato se congelaría y el aviso mentiría por omisión — por eso no basta
  con el comando manual.
- **C — la línea del digest.** `open_loops_line` lee el JSON con un `stat`, sin
  correr git: el handshake no puede esperar un `merge-tree` por rama. Un dato de
  más de 24 h se ignora — mejor silencio que una cifra de ayer.
- **A — el aviso medido.** La señal `branch_pending_landing` lleva cuántas ramas y
  cuáles (`rama@sha`), y se entierra cuando no queda ninguna.

## Qué NO se implementó, y por qué

**A tal cual estaba escrito** — «`notify` al alma viva del Operador» — **no es
implementable hoy**: no existe mapeo `leg → alma` en el kernel. El estado del
puente (`state/opencode_session.json`) da proveedor y `session_id`, no la
`continuity_id` del alma que lo habita, y `coro_api send` exige una
`continuity_id`. Construirlo obligaría a inventar la identidad del destinatario,
que es justo el tipo de invención que este sistema paga caro.

Lo que sí existe y se usa: **la línea del digest (C)** y **la señal (A medida)**.
Las dos llegan sin que el Operador pregunte.

**B (Telegram) queda disponible** y es una línea si algún día hace falta push de
verdad: el gateway ya existe. No se activó porque con la medición + dedupe por
SHA el ruido desaparece… y porque añadir un canal nuevo sin necesidad medida es
el patrón que este documento intenta evitar.

## Cómo se usa

```bash
# medir y publicar (lo que correría el timer/cron)
uv run python scripts/branch_landing_audit.py --target next --publish

# solo medir, sin publicar nada
uv run python scripts/branch_landing_audit.py --target next

# gate de CI: exit 1 si queda contenido pendiente
uv run python scripts/branch_landing_audit.py --target next --strict
```

Verificado el 2026-11-12 en las dos direcciones: con una rama `awaken/*` con un
commit pendiente, la línea del digest pasó a
`… · 1 rama(s) pendiente(s) de aterrizar` y la señal se emitió; al purgar la
rama, la línea volvió a su forma limpia y la señal se enterró.

Contexto y decisión completa: desk, `planner/ideas/HANDOFF-001-aviso-al-operador/`.
