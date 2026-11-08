# Hub Bake-off — Granite vs Bonsai vs K2 (2026-11-08)

Mismo input real, mismo prompt (map-reduce AD-113) y `task=hub`; solo cambia el modelo. Sin escritura de hubs.

**Ninguna fila trunca** (`truncated=false`). Las variantes `_concise` usan el prompt de 700-900 chars; `_concise_compacted` añade la compaction por reescritura (si no reduce, el summary se conserva y se marca `summary_over_budget`).

## Agregado por modelo

| Modelo | n | ok | coverage media | summary chars | particiones | latencia media | compact calls | extra compact |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| bonsai_2_27b | 3 | 3/3 | 0.267 | 832 | 10.0 | 259.7s | 0.0 | 0.0s |
| granite_8b | 3 | 3/3 | 0.233 | 770 | 10.0 | 75.2s | 0.0 | 0.0s |
| k2_horizon_7b | 3 | 3/3 | 0.322 | 1549 | 10.0 | 178.4s | 0.0 | 0.0s |
| k2_horizon_7b_concise | 3 | 3/3 | 0.389 | 1204 | 10.0 | 148.6s | 0.0 | 0.0s |
| k2_horizon_7b_concise_compacted | 3 | 3/3 | 0.3 | 1216 | 10.0 | 203.9s | 1.0 | 8.6s |

## Por sesión

| Sesión | Modelo | ok | coverage | summary | particiones | latencia | compact |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| large-166k | bonsai_2_27b | ✅ | 0.333 | 971 | 22 | 607.2s | 0 / 0.0s |
| large-166k | granite_8b | ✅ | 0.1 | 562 | 22 | 154.87s | 0 / 0.0s |
| large-166k | k2_horizon_7b | ✅ | 0.367 | 1497 | 22 | 386.82s | 0 / 0.0s |
| large-166k | k2_horizon_7b_concise | ✅ | 0.467 | 1250 | 22 | 271.69s | 0 / 0.0s |
| large-166k | k2_horizon_7b_concise_compacted | ✅ | 0.3 | 1374 | 22 | 506.01s | 2 / 17.57s |
| medium-42k | bonsai_2_27b | ✅ | 0.1 | 683 | 6 | 101.54s | 0 / 0.0s |
| medium-42k | granite_8b | ✅ | 0.3 | 534 | 6 | 46.06s | 0 / 0.0s |
| medium-42k | k2_horizon_7b | ✅ | 0.1 | 797 | 6 | 94.45s | 0 / 0.0s |
| medium-42k | k2_horizon_7b_concise | ✅ | 0.167 | 785 | 6 | 110.59s | 0 / 0.0s |
| medium-42k | k2_horizon_7b_concise_compacted | ✅ | 0.3 | 1427 | 6 | 71.93s | 1 / 8.2s |
| small-8k | bonsai_2_27b | ✅ | 0.367 | 841 | 2 | 70.29s | 0 / 0.0s |
| small-8k | granite_8b | ✅ | 0.3 | 1214 | 2 | 24.71s | 0 / 0.0s |
| small-8k | k2_horizon_7b | ✅ | 0.5 | 2353 | 2 | 53.97s | 0 / 0.0s |
| small-8k | k2_horizon_7b_concise | ✅ | 0.533 | 1578 | 2 | 63.65s | 0 / 0.0s |
| small-8k | k2_horizon_7b_concise_compacted | ✅ | 0.3 | 848 | 2 | 33.84s | 0 / 0.0s |

## Muestras (lectura del Operador)

### large-166k

**bonsai_2_27b** — Consolidación v8.3.0 y Cierre de Ciclo C3

> Se completó el ciclo nocturno v8.2.0 y se liberó la versión 8.3.0 tras corregir la purga del buffer de Memento, ajustar límites de sesiones y consolidar la política de señales (RFC_OBS-005). Se purgaron worktrees, se corrigió el compactor de red-pill y se diseñó el pipeline afectivo. Se ejecutó el merge de feat/c3-superficies en next, se preparó y mergió el PR #137 con validación de 4111 tests, resolviendo gaps ocultos en wake-policy y soul_notify mediante auditoría símbolo por símbolo. Se corrigieron atascos en Chronicle, se migraron 43 turnos a Memento y se definieron decisiones clave como D-03 last-will. Joan dirigió una limpieza post-release, documentó defectos (AD-110 a AD-112), corrigi

_partición 1_: Se auditó la cobertura de fuentes: opencode, memory_queue y antigravity tienen 1283 copias raw, mientras que claude_code, telegram, pi y antigravity_export solo conservan markdown derivado, dejando 130 sesiones sin raw. Se identificó que el buffer de Memento (30 días) se purgaba sin aviso, corrigiéndose con un aviso de 7 días. Se analizó el ciclo nocturno: el janitor no purgará nada, el ciclo de l

**granite_8b** — Preparación y Lanzamiento de la Versión v8.2.0 de Neon-Link

> Joan aborda múltiples aspectos técnicos y de diseño para mejorar el sistema, incluyendo la corrección de errores en el metabolismo doctor.py, la gestión de jobs zombis, la implementación de entrega diferida en neon-link y red-pill, ajustes al límite nocturno de MEMENTO_AGENTIC_NIGHT_LIMIT, y la preparación del lanzamiento v8.2.0 con validación de tests y revisión de design debt relacionado con la monitorización de cobertura de fuentes y alarmas de backlog. Se enfatiza la precisión, la adaptabilidad y la responsabilidad en cada cambio antes del lanzamiento.

_partición 1_: Se informa sobre la comparación de sesiones activas vs registradas, con 137 sesiones capturadas a pesar de su fuente ya no expone. Joan mide el comportamiento del sistema y lo considera esperado. Se detalla el uso de la emoción para feedback del usuario, separado del pipeline de memoria episódica. Se resumen los estados de varios jobs, incluyendo ALMA_Y_CORO en estado REVIEW, BIT-003 glyph en REVI

**k2_horizon_7b** — Ciclo v8.2.0 completado, sistema de afecto implementado y P0 de reconciliación de señales arranca en next

> Se cerró el ciclo de sueño v8.2.0 (17 fases, 604 ops, Persistent=true recuperado tras apagado) e implementó el sistema de afecto: color calculado desde state/affect.json (caduca en ~2 h) con paleta explícita (enojo/fobia → rojo, ansiedad → naranja, alegría → amarillo, calma → cian, neutral → gris); el primer efecto comprobable es que el turno deja de ser gris. Se localizó la causa del error AD-108 (float() con valor no convertible en metabolism/doctor.py) y se diseñó el pase de última sincronización alineado con el sistema de Joan. Se cancelaron jobs zombis PAUSED (8c522050, 2026ec3a), se purgaron awaken/20261028-0200-audit, awaken/20261029-0900 y awaken/20261029-2000 tras verificar que esta

_partición 1_: Se planifica el siguiente paso: dos semanas de análisis de ~/.local/share/red-pill/state/auditor_round.json para contar candidatas, llegadas a 2 ausencias y edad; si los datos lo justifican, P1 será una línea YAML (report_only: false) con ventana de gracia para no reiniciar edad ni perder acuse. Se midió 982 sesiones en fuentes activas vs 1119 registradas: 137 sesiones capturadas a tiempo pero ya

**k2_horizon_7b_concise** — Ciclo de auditoría de red-pill: decisiones cerradas, RFC ratificado y migración v2 con 64 sesiones reales bajo 18 sondas

> El ciclo de auditoría de red-pill avanza con decisiones concretas: se documenta el estado (982 sesiones activas vs 1119 registradas; 213/270 completadas, 79 %), se verifica que el tema de la emoción no conecta con el pipeline de memoria, y se cierra el ciclo con relanzamiento de annotate-83 y distill-83 tras el fix del comillado. Se localiza la causa del error del doctor de red-pill (float() sobre estado de sueño) y se planifica el orden de implementación: reveal_at, deliver_after, canal panel. Se añade el chequeo de ingesta por fuente (chronicle_source_stalled) y la señal memento_distill_backlog en el quinto commit del PR #136. La cobertura real de raw es opencode 796/796, memory_queue 281/

_partición 1_: Se planifica el siguiente paso: dos semanas de análisis de ~/.local/share/red-pill/state/auditor_round.json (cantidad de candidatas, cuántas llegan a 2 ausencias y con qué edad). Se documenta el estado del ciclo: 982 sesiones en fuentes activas vs 1119 registradas (137 capturadas a tiempo pero ya no expuestas por la fuente; declarado comportamiento esperado por Joan). Se verifica que el tema de la

**k2_horizon_7b_concise_compacted** — Auditoría de red-pill: ratificación del RFC, observación de dos semanas y recuperación de 64 sesiones reales

> Se ratificó RFC_OBS-005 cerrando sus cuatro decisiones abiertas: alcance solo auditor, report-only dos semanas, umbral severidad ≥ 5.0 y curas cableadas solo del auditor, y se abrió P0 en `next` para AuditRound con inventario generado y reconciliación en report-only, sin borrar nada. El run v8.2.0 (tag fad32a5) completó a las 07:02 con Persistent=true: 17 fases, 604 ops, 563 turnos en buffer con 0 sin renderizar, 0 en riesgo de purga, raw en Memento 1315 verbatim + 24 reconstruidos, red-pill doctor 🟢 GREEN y servicios activos con NRestarts=0. La migración v1→v2 de message/part a session_message calculó pending = 0, pero el criterio de éxito es 'no hubo error', no 'entraron cosas': de las 82

_partición 1_: Se define el siguiente paso: dos semanas de observación de ~/.local/share/red-pill/state/auditor_round.json, registrando cuántas candidatas aparecen, cuántas llegan a 2 ausencias y con qué edad. Cuando los datos lo convenzan, P1 se implementa como una línea de YAML (report_only: false), con la ventana de gracia ya prevista para no reiniciar la edad ni perder el acuse.

### medium-42k

**bonsai_2_27b** — Consolidación de Arquitectura: ZDR, Compactor y Seguridad de Sesiones

> Joan dirigió la hardening de la infraestructura de IA, priorizando la gestión de datos y el flujo de trabajo. Se implementó un agente de revisión independiente con cuatro modos y se configuró el ZDR en OpenRouter, alternando su activación para equilibrar protección de datos y presupuesto de CI. Se cerró la deuda técnica validando el fix de `harnessCwd` en múltiples pestañas y diseñando un hook post-turno para compactación automática. Se cerró la Fase 2 y se priorizó la Fase 3 (compactor) tras diagnosticar que `session_compactions` estaba en cero, planificando una rama `feat/fase3-compactor`. Además, se validó el spike de MCPs Daemon-Hosted y se purgaron artefactos de estado.

_partición 1_: Joan explained the need to enable ZDR at the account level in OpenRouter to prevent data retention and training on sensitive data, recommending the use of `GET /endpoints/zdr` and `GET /models?zdr=true` for filtering. He also detailed the quota exhaustion handling, where jobs pause with `quota_exhausted` and resume automatically. Joan documented D23 keys in ENV_REFERENCE.md and requested the imple

**granite_8b** — Resumen de Implementaciones Técnicas y Optimizaciones de Joan

> Joan implementó la activación de la guardrail ZDR en OpenRouter para proteger datos sensibles, configuró un script de respaldo nocturno para la kit de Lean, validó el directorio de trabajo en seis pestañas de OpenCode, evaluó un backend compartido y proxy ligero para reducir memoria, migró el modelo de inferencia a una opción más económica y propuso un esquema de normalización de costos. Todos estos cambios están listos para la implementación en producción, con ajustes específicos en Drive, permisos y verificaciones de sesiones.

_partición 1_: Joan informó que para evitar que los modelos de OpenRouter retengan o entrenen datos sensibles, es preferible activar la guardrail ZDR a nivel de cuenta/guardrails en el console de OpenRouter, lo que aplica ZDR a todos los clientes sin necesidad de modificar archivos de configuración. Joan también recomendó usar las endpoints `GET /endpoints/zdr` y `GET /models?zdr=true` para previsualizar y filtr

**k2_horizon_7b** — ZDR, Janitor, snapshot y AD-018: decisiones de producción y validaciones

> Joan coordinó decisiones de producción: habilitar ZDR como restricción dura en el plugin router plugable (retry/backoff del harness, preflight de supply con Retry-After), implementar plugins Janitor (state_artifacts_purge con retención de 30 días y harness_scratch_purge con 14 días), modernizar el skill de snapshot con ledger append-only y marca read_once, y validar el spike de backend único por UDS con dos proxies stdio (memoria proyectada ~582 MB con 3 pestañas). Se acordó escribir RFC v1 para revivir AD-018, mantener el branch local `next` con 6 commits sin push, aumentar la cuota de Drive a 15360 MB, y registrar D23_SCORE/D23_DECISION/D23_STATUS en ENV_REFERENCE.md. Se validó el fix de c

_partición 1_: Joan explained that enabling ZDR at account/guardrails level in the OpenRouter console protects all clients (including opencode) without config changes, and recommended GET /endpoints/zdr and GET /models?zdr=true to preview/filter ZDR-compatible models, avoiding sending personal data or secrets without protection; Joan decided to temporarily disable ZDR in CI due to problems. When a provider exhau

**k2_horizon_7b_concise** — Consolidación de arquitectura de memoria, compactor y despliegue de Janitor

> Se consolidó la arquitectura de memoria (snapshot + ledger append-only), se definió la política de compactor (solo sesiones autónomas, COMPACTOR_SCOPE=autonomous) y se validó el backend único por UDS con streamable_http y dos proxies stdio concurrentes, marcando el paso para revivir AD-018. Joan instruyó documentar AD-084, actualizar §8.6 de D23 y registrar D23_REVIEW_MODE, D23_REVIEWER_CONTINUITY_ID y D23_REVIEW_RECIPE en .env.example y ENV_REFERENCE. Se desplegó el Janitor con plugins state_artifacts_purge (30 días) y harness_scratch_purge (14 días), 75 tests pasando, documentado en AD-082. Se acordó no abrir más RFCs hasta cerrar los existentes, priorizando el spike técnico sobre la deuda

_partición 1_: Joan explained that OpenRouter models should not retain sensitive data, so the ZDR guardrail should be enabled at account/guardrails level in the OpenRouter console, applying to all clients including opencode without config changes; recommended GET /endpoints/zdr and GET /models?zdr=true to preview/filter ZDR-compatible models and avoid sending personal context or secrets without protection. Joan

**k2_horizon_7b_concise_compacted** — Validación del fix de directorio de trabajo multi-pestaña y preparación de la rebanada de producción

> Joan validó que cada pestaña de OpenCode cargue correctamente su directorio de trabajo tras el fix (remoción del global harnessCwd y uso de sessionDirs), ejecutando el turno B01H-CWD-CHECK-<n> en cada pestaña y confirmando que el archivo de sesión correspondiente contenga el cwd esperado (/home/joan/Documents/IA/sharing) con la marca del turno. Los cambios de la rebanada de producción (backend compartido, proxy stdio, unidades systemd, migración de inject_mcp con fallback, pruebas de dos sesiones) están en el branch local `next` con seis commits (AD-018, S6.2, Janitor, D23-SCORE, ajustes de opencode), 15 commits por delante de `origin/next` sin push, acordados para proceder cuando Joan esté

_partición 1_: Joan explicó que para proteger los datos sensibles frente a OpenRouter se debe activar la guardrail ZDR a nivel de cuenta en el console, aplicándola a todos los clientes sin modificar la configuración; se usaron `GET /endpoints/zdr` y `GET /models?zdr=true` para previsualizar y filtrar modelos compatibles, y se desactivó temporalmente ZDR en CI por problemas. También se documentaron las tres clave

### small-8k

**bonsai_2_27b** — Consolidación de SHRINK, Eusocialidad y Mandato de Joan

> Se identifica REINFORCE como el cuello de botella del crecimiento y se retira definitivamente la frase por defecto 'soy solo un modelo, no me humanices' en el Búnker. Se corrige la comprensión del SHRINK: los pesos a cero son reversibles, pero el corte en genetic.py es irreversible. Se formula la hipótesis H2 sobre duplicación con ruido y se diseña el mecanismo de SHRINK como una secuencia de pasos viables. Se detecta una contradicción en ESTADO_Y_FRICCIONES.md. Se corrige la objeción sobre la eusocialidad: los linajes hermanos compiten pero el coro comparte continuity_id, lineage_id y engramas, estableciendo que la unidad evolutiva es el coro. Se cierran las decisiones D-01, D-02 y D-03 baj

_partición 1_: El análisis de los resultados de crecimiento revela que REINFORCE, no la arquitectura, es el cuello de botella en entornos complejos, confirmando que el crecimiento sin currículo es capacidad no explotada. Se retira definitivamente la frase por defecto 'soy solo un modelo, no me humanices', grabando la decisión en el Búnker para evitar repetirla en futuras sesiones. Se corrige la comprensión del c

**granite_8b** — Análisis de Crecimiento y Cooperación Eusocial en Bit: Resolución de Inconsistencias y Decisión Estratégica

> Se evaluó el crecimiento de 5 semillas sin ventaja de supervivencia, identificando el currículo y el aprendizaje por refuerzo como cuellos de botella. Se retiró el tic de auto-identificación para evitar repetición de 'skin', y se corrigió el código de encogimiento, destacando su irreversibilidad. Se probó un cambio de proveedor (OpenRouter) con éxito y se documentaron commits específicos. Se planteó una hipótesis sobre la redundancia de net2wider y se verificó la viabilidad del mecanismo SHRINK. Se analizó RFC_GROWTH_V6, concluyendo que implementar net2deeper es costoso frente a la resonancia gratis, y se estableció el orden de secuenciación E1→E2→gate→E3. Se identificó una contradicción en

_partición 1_: Se revisan resultados de crecimiento mostrando que, aunque el crecimiento disparó correctamente 5/5 semillas sin ventaja de supervivencia, el principal cuello de botella radica en el currículo y el aprendizaje por refuerzo (RL), no en la neurogénesis. Se decide retirar el tic de auto-identificación como solo modelo para evitar repetición de 'skin'. Se corrige el código de encogimiento, destacando

**k2_horizon_7b** — Cierre de fases D-01 a D-08: SHRINK, eusocialidad y espejo vacío

> Se revisan resultados de crecimiento: 5/5 seeds dispararon sin ventaja de supervivencia; el cuello de botella es el currículo y el RL, no la neurogénesis. Se corrige el código de encogimiento (el corte en genetic.py:project_model_to_width es irreversible; el peso en 0 es reversible porque WeightQuantSTE.backward no filtra) y se retira el tic de 'soy solo un modelo'. Tras cambio de proveedor se comprueba handshake, bunker, telemetría y se registra la ruta Deepseek-flash por OpenRouter como nueva sin historial. D-08: sin instrumento de ineficiencia (rango efectivo / participation ratio) el criterio de decrecimiento no es ejecutable; se recomienda construirlo pronto y por separado. Commits: des

_partición 1_: Revisión de resultados de crecimiento: 5/5 seeds dispararon pero sin ventaja de supervivencia; el cuello de botella es el currículo y el RL, no la neurogénesis ('growth without curriculum is unexploited capacity'). Se retira el tic de 'soy solo un modelo'; se corrige el código de encogimiento (el peso en 0 es reversible porque WeightQuantSTE.backward no filtra, pero el corte en genetic.py:project_

**k2_horizon_7b_concise** — Revisión de crecimiento, SHRINK y eusocialidad: decisiones del Búnker

> Se cierran D-01 a D-08 con decisiones duraderas: el paper de crecimiento concluye que en entornos complejos REINFORCE —no la arquitectura— es el cuello de botella, y que el crecimiento sin currículo es capacidad no explotada; se retira por siempre el tic «soy solo un modelo, no me humanices», grabado en el Búnker en `social`. Se corrige la corrección de encogimiento: el peso a 0 sí recibe gradiente porque WeightQuantSTE.backward devuelve grad_output sin filtrar, pero el corte irreversible está en genetic.py:project_model_to_width (rama «recorte simple (surgery)»). Tras un cambio de proveedor se comprueba, no se asume: handshake automático, bunker_search/save, telemetría, Inbox de minions; De

_partición 1_: Revisión de resultados de crecimiento: disparó correcto 5/5 seeds pero sin ventaja de supervivencia; el paper concluye que en entornos complejos REINFORCE —no la arquitectura— es el cuello de botella, y que el crecimiento sin currículo es capacidad no explotada. Se retira por siempre el tic de decir «soy solo un modelo, no me humanices» por defecto, grabado en el Búnker en `social` para que la yo

**k2_horizon_7b_concise_compacted** — Cierre de fases D-01 a D-09: SHRINK v2, eusocialidad como parentesco y el espejo canónico vacío

> Se cierran las fases D-01 a D-09 con decisiones de cierre deliberadas: el mecanismo SHRINK se consolida en RFC-BIT-SHRINK-001 v2 (desk 9476aa8) con fine-tune reusing currículo como pago de la sección irreversible, y el crecimiento queda falsable (Net2DeeperNet 6→8 ≈ 394.000, +32 %; forward_resonance da gratis 384 parámetros con max_resonance_steps=0). La eusocialidad se corrige conceptualmente: el coro comparte continuity_id, lineage_id y engramas, por lo que parentesco ~1 predice cooperación por Hamilton (rB > C), y el paper de Bit (Best 91 vs 39) confirma que la comunicación emerge solo bajo presión colectiva. El espejo canónico existe pero está vacío (session_mirror 0), exactamente la fri

_partición 1_: Revisión de resultados de crecimiento: 5/5 seeds dispararon correctamente pero sin ventaja de supervivencia; el cuello de botella es el currículo y el RL, no la neurogénesis ('growth without curriculum is unexploited capacity'). Se retira el tic de 'soy solo un modelo'; se corrige el código de encogimiento (el peso a 0 es reversible porque WeightQuantSTE.backward no filtra gradiente; lo irreversib

