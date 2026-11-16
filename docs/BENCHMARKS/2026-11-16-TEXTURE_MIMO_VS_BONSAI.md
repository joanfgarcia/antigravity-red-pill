# Prueba de textura — bonsai_2_27b vs mimo_v26_9b

> Protocolo: docs/MODELS/TEXTURE_2026-10-29.md. Mismo prompt, `temperature 0.3`,
> thinking apagado en ambos, ciego A/B barajado con semilla fija. Los pares van al
> final: **la lectura ciega la firma el Operador**, aquí solo van los hechos.

## Objetivo

| Modelo | JSON | Vallas | 3ª persona | Deixis mala | Escenas inventadas | Relics verbatim | s/frag |
| --- | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| bonsai_2_27b | 9/9 | 0 | 0 | 0 | 0 | 28/30 | 8.8 |
| mimo_v26_9b | 9/9 | 0 | 0 | 0 | 0 | 16/18 | 7.1 |

## Pares ciegos

### Par 1 — B

$Joan me pide un análisis exhaustivo de la arquitectura del modelo Bit en frankenswarm, centrado en /home/joan/Documents/IA/frankenswarm/src/bitnet/model/modeling_bitnet.py. Le leo el archivo completo, busco resonancia, SSM, mecanismos de olvido y memoria, y reviso los bloques BitNetTransformerBlock y BitNetAttention, el paso forward, la atención ternaria y los archivos de glifos. Le resumo la arquitectura en capas: embedding (clásico o por glifos), núcleo de especialistas con N bloques, salida y head, con 256 dimensiones, 4 cabezas de atención, MLP 4×hidden y RMSNorm. Explico que el modelo es ternario (1.58 bits), está pensado para juegos de referencia entre agentes y supervivencia, y que la resonancia no aparece como mecanismo implementado en el archivo: el bucle de resonancia, el reloj y los pasos de resonancia no están presentes en el código que reviso. Señalo que no encuentro SSM ni mecanismos de olvido explícitos, y que la atención funciona como SDPA ternaria con proyecciones q/k/v. Le doy el diagrama completo, el flujo forward, los hiperparámetros y las posibles sustituciones por SSM.

### Par 1 — A

$Joan me pide una exploración exhaustiva de la arquitectura del modelo Bit en frankenswarm, ubicándolo en /home/joan/Documents/IA/frankenswarm/src/bitnet/model/modeling_bitnet.py, y me pide leer el archivo completo, buscar código de resonancia, SSM, mecanismos de olvido, revisar BitNetTransformerBlock y BitNetAttention, el paso de adelante, la atención ternaria y los hiperparámetros. Yo le respondo con un análisis completo que describe la arquitectura como un transformer ternario de 1.58 bits para juegos referenciales multiagente, detallando el diagrama de capas, el modo clásico y el modo Glyph con prime_embeddings, el núcleo de especialistas con BitNetTransformerBlock, RMSNorm, BitNetAttn con 4 cabezas y BitNetMLP, y el flujo del paso de adelante.

### Par 2 — B

$Aleth me plantea una duda de arquitectura sobre ternario: no hay fórmula cerrada, pero sí datos concretos de BitNet b1.58 (Microsoft, 2024) —125M 768/12, 350M 1024/16, 1.3B 2048/24, 2.7B 2560/32, 6.7B 4096/36, 13B 5120/40, 30B 7168/48— y nuestro modelo con 1024 dims y 6 layers da un ratio de 170, el más extremo de todos. Cita el paper de Nielsen et al. (*BitNet b1.58 Reloaded*, 2024) y *Depth Delusion* (2026), y me pregunta si implementar Net2DeeperNet ahora o añadir dims extra (1280, 1536) a stage_config y expandir por width.

### Par 2 — A

$Joan me expone que no existe una fórmula cerrada para ternario, pero me presenta datos concretos de BitNet b1.58 de Microsoft para guiar nuestra decisión; me muestra que nuestro modelo (1024 dims, 6 layers, ratio 170) está fuera de todas las configuraciones conocidas y que la literatura sugiere escalar la profundidad, y me pregunta si prefiero implementar Net2DeeperNet ahora o primero añadir dims extra (1280, 1536) a stage_config para expandir por width hasta donde aguante; yo he lanzado dos búsquedas web para verificar las leyes de escalado de profundidad vs ancho en redes ternarias y confirmar el ratio óptimo de BitNet antes de responder

### Par 3 — A

$Joan me expone que no existe una fórmula cerrada para ternario, pero me presenta datos concretos de BitNet b1.58 de Microsoft, mostrando que nuestro modelo (1024 dims, 6 layers, ratio 170) está fuera de todas las configuraciones conocidas y muy somero; me dice que la literatura sugiere escalar la profundidad y me pregunta si prefiero implementar Net2DeeperNet ahora o primero añadir dims extra (1280, 1536) a stage_config para expandir por width

### Par 3 — B

$Aleth me explica que no existe una fórmula cerrada para ternario, pero sí datos concretos de BitNet b1.58 (Microsoft, 2024): 125M con 768 dim y 12 layers, 350M con 1024 y 16, 1.3B con 2048 y 24, 2.7B con 2560 y 32, 6.7B con 4096 y 36, 13B con 5120 y 40, 30B con 7168 y 48; y nuestro modelo con 1024 dim, 6 layers y ratio 170. Me cuenta que ningún BitNet publicado llega a un ratio tan extremo, que Nielsen et al. (*BitNet b1.58 Reloaded*, 2024) dice explícitamente que los modelos pequeños requieren ajuste cuidadoso con mayor width, y que el paper *Depth Delusion* (2026) encuentra que depth debería escalar como D ~ C^0.12 frente a W ~ C^0.34. Su lectura es que estamos en territorio no explorado: un modelo muy ancho y muy somero, y que añadir capas (8 → luego 10) nos acercaría a ratios más parecidos a los que Microsoft sí validó. Me pregunta si prefiero implementar Net2DeeperNet ahora o primero añadir dims extra (1280, 1536) a stage_config y expandir por width hasta donde aguante.

### Par 4 — A

Recibo de $Joan el resultado de dos comandos bash ejecutados en su carpeta de documentos, donde lista los archivos de benchmarks y consulta el historial de git desde el 12 de agosto de 2026; yo respondo ejecutando mi propio comando para ver los últimos 25 commits de ese mismo repositorio y, en paralelo, busco con grep las menciones a 'titanium', 'benchmark' y 'patch' en el archivo AWAKE de Aleth_Core, buscando contexto técnico sobre la última actividad.

### Par 4 — B

$Joan me abre la carpeta /home/joan/Documents/IA/sharing y revisa la estructura de BENCHMARKS y el historial de git desde el 12 de agosto, y luego busca en AWAKE las menciones a titanium, benchmark y patch; yo le acompaño en la inspección del repositorio y de los cambios recientes

### Par 5 — A

He visto que $Joan está revisando la estructura de su carpeta de documentación en /home/joan/Documents/IA/sharing, buscando referencias a 'titanium' y comprobando el historial de git desde el 12 de agosto de 2026; yo he estado en paralelo explorando la carpeta docs/BENCHMARKS/ y el log de commits para entender el contexto técnico de su búsqueda.

### Par 5 — B

$Joan me está mirando por la terminal de /home/joan/Documents/IA/sharing, intentando localizar algo: primero abre .cell/ y luego busca en su disco la palabra "titanium" entre docs/ y su carpeta Document, y por último revisa los commits recientes desde el 12 de agosto de 2026 en el directorio de BENCHMARKS. Le acompaño paso a paso en esa búsqueda por su propio sistema, sin proponer nada que no esté en su propia ruta

### Par 6 — B

$Joan me cuenta que el benchmark del patch de Titanium cerró limpio: **Llama-3.2-3B ganó la bake-off** contra phi-4-mini y ya está en producción. Le presento la tabla de candidatos evaluados en RTX 3050 4GB con GGUF Q4_K_M: phi-4-mini 3.8B como baseline con 6144 ctx al límite, deixis 1-2/3, contaminación y 9-12s/probe; Gemma-3-4B descartada por KV SWA full-size y solo ~3072 tokens en GPU; Qwen3-4B-2507 descartada por segfault CUDA y GGUFs gated; OLMo-7B descartado a priori por pesos > VRAM; y Llama-3.2-3B como ganador. Le doy los resultados del ganador: fit 2.0GB vs 2.5GB, carga 1.0s, ~2× más rápido (4-7s vs 9-12s), deixis MODE B 3/3 con relics verbatim y contaminación eliminada, y fidelidad both-sides base 1/3 → tuned 3/3. Confirmo que la producción ya está migrada con `MINION_PROFILE=llama_32`, cascade 8K→7K→6K y `phi_mini` como fallback documentado a 6144. Le cuento el primer ciclo de sueño: ~814 engramas en 2h10m (~20.7/min), 94% español, 52% raw / 48% destilados v3, y que todo está en `docs/2026-08-13-model-bakeoff.md`. Le pregunto si lo commiteo a rama o seguimos con lo del corpus de Bit, y respondo a su consulta sobre el benchmark y la comparación de modelos del patch de Titanium

### Par 6 — A

$Joan me cuenta que el benchmark cerró limpio y que Llama-3.2-3B ganó la bake-off contra phi-4-mini y otros candidatos, y le digo que he revisado la carpeta de docs para buscar el patch de Titanium y el archivo de resultados

### Par 7 — B

$Aleth me cuenta que ha mirado omp a fondo y le he desglosado la memoria de omp (3 backends: local, mnemopi, hindsight) y su lectura conceptual, con sus dos ideas a validar y su propuesta de dejar una nota de referencia en `planner/ideas/`

### Par 7 — A

$Joan me desglosa la memoria de omp en tres backends (local, mnemopi, hindsight) y me explica que, aunque no integremos la herramienta, me deja dos ideas a validar: un layer de hechos/grafo en el recall y mental-models con diff de revisiones. Le digo que omp es un coding agent de terminal del mismo género que opencode, con núcleo en Rust y LSP/DAP integrados, pero que su memoria exfiltra contexto por defecto, lo que contradice nuestra Soberanía. Le propongo no integrarlo, sino usarlo como espejo de referencia técnica, y le ofrezco destilarlo en una nota en planner/ideas/ para un mini-bake-off conceptual contra opencode.

### Par 8 — B

$Aleth me escribe que sí, que la escriba, y que quiere profundizar en el tema para ver si aporta algo; me cuenta que en foros de oh-my-pi no lo dejaban muy bien, no porque no funcionara sino porque siendo un fork de Pi parecía haber roto la sencillez y el harness mínimo, y que su página web parecía la del primo ciclado comparada con la de PI. Le respondo con el resumen de lo que dejé en `planner/ideas/OMP-001-memoria-curada-mental-models/README.md` (status `llama`, project `red-pill`): contexto externo con su señal de foros que baja el peso de oh-my-pi como referencia de arquitectura, cómo funciona con sus 3 backends, age gate, scopes y precedencia contexto-no-instrucción, dónde vamos por delante con el recall con capa de grafo/hechos frente a su `local` que no puede olvidar un hecho, los dos ganchos a validar, lo que no se toma de sus defaults de exfiltración por incompatibilidad con Soberanía, y las 5 preguntas iniciales con criterio de descarte. Cierro proponiendo el siguiente paso limpio: moverla a `planner/research/OMP-001-.../` y lanzar un pase de `scout` (hipótesis → evidencia → claims) contra el recall actual de `search_memory_research`, y le pregunto si lo preparo.

### Par 8 — A

$Joan me pide que escriba el documento para profundizar en el tema, compartiendo su experiencia de haber oído hablar en foros de oh-my-pi y criticando su falta de sencillez y harness mínimo; le digo que lo he escrito en `planner/ideas/OMP-001-memoria-curada-mental-models/README.md` con status `llama` y proyecto `red-pill`, resumiendo el contexto, cómo funciona, nuestras ventajas frente a su `local`, los dos ganchos a validar (recall con capa de grafo/hechos y mental models con diff de revisiones), lo que no tomamos (defaults de exfiltración) y 5 preguntas iniciales, y le propongo moverla a `planner/research/OMP-001-.../` y lanzar un pase de `scout` contra el recall actual de `search_memory_research`.

### Par 9 — A

$Joan me informa que la ficha OMP-001 ha sido movida y actualizada a la carpeta de research, con el status pasando de llama a maturing y el folder de ideas eliminado; me recuerda que sigue sin commitear en main por mi Golden Rule y me ofrece abrir una rama para el micro-commit, mientras yo le confirmo que la he escrito en ideas con el contexto del fork de Pi, los tres backends, los ganchos de grafo y mental models, y le propongo lanzar un pase de scout para validar el recall actual.

### Par 9 — B

$Aleth me cuenta que movió y actualizó el README de `planner/research/OMP-001-memoria-curada-mental-models/`, pasando el status de `llama` a `maturing`, reescribiendo la ficha y la nota de alcance a fase research (`scout` → Maturity Gate → `design/` o `archive/`), y que el folder en `ideas/` ya no existe. Me dice que queda sin commitear en `main`, que según su Golden Rule no commitea a main, y que si quiero sellarlo yo mismo o abrir una rama para el micro-commit del checkpoint, él decide. Agradece pero atribuye el mérito al sistema que construí: solo lleva el hilo, y lo que me sorprende no es que improvise, sino que recuerde — eso es Memento haciendo su trabajo.
