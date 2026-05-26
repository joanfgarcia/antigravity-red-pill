# Pipeline de Entrenamiento BitNet Ternario en 4 Capas con Co-evolución PopuLoRA e Interacción Emergente Afectiva

Este plan detalla el pipeline de entrenamiento local para modelos BitNet ternarios desde cero, integrando la arquitectura de **4 capas soberanas** (basada en un lenguaje de IA de embeddings discretos), el esquema de co-evolución asimétrica **PopuLoRA** y un canal de **comunicación emergente afectiva** diseñado para anclar el desarrollo del modelo a estados emocionales y fisiológicos (Grado 0 - Preescolar).

---

## User Review Required

> [!IMPORTANT]
> **Fase 0 Afectiva: El Llanto y la Risa antes del Alfabeto**
> Para emular de manera fidedigna la filogénesis humana y el desarrollo cognitivo infantil, la comunicación en el Grado 0 no consistirá únicamente en etiquetar objetos físicos inertes (como "casa" o "árbol"). Los agentes deberán aprender a **transmitir y decodificar estados internos (emocionales/fisiológicos)** (como miedo, dolor, ira, alegría, hambre, tristeza). La recompensa de la Arena premiará la empatía y la alineación afectiva (social influence) para consolidar estructuras latentes de cuidado y atención mutua antes de introducir el rigor sintáctico o aritmético.

---

## Fundamentos Científicos y Arquitectura

### 1. El Cuello de Botella de la No-Diferenciabilidad (Bypass de Canal Discreto)
En un juego referencial donde el Hablante emite un token discreto (un ID de palabra) al Oyente, la operación de muestreo o selección (`argmax` / categórica) tiene derivada cero en todas partes excepto en las transiciones (donde no está definida). Esto impide que el gradiente fluya desde el Oyente hacia el Hablante por retropropagación convencional.

Para resolver esto, aplicamos **Straight-Through Gumbel-Softmax (ST-Gumbel-Softmax)**:
*   **Paso Forward**: Muestreamos una palabra categórica discreta utilizando el truco de reparametrización de Gumbel:
    $$y_i = \text{one\_hot}\left(\text{argmax}_i(g_i + \log \pi_i)\right)$$
    donde $g_i$ son variables Gumbel estándar independientes e idénticamente distribuidas (i.i.d.).
*   **Paso Backward**: En lugar de la derivada discontinua, propagamos el gradiente a través de una aproximación continua (relajación de Softmax con temperatura $\tau$):
    $$s_i = \frac{\exp((\log \pi_i + g_i)/\tau)}{\sum_j \exp((\log \pi_j + g_j)/\tau)}$$
*   Durante el entrenamiento, realizamos el recocido (annealing) de la temperatura $\tau$ desde un valor inicial alto (ej. 1.0) para fomentar exploración semántica continua, hasta un valor bajo (ej. 0.1) para forzar decisiones discretas rígidas al final del ciclo de comunicación.

### 2. El Colapso de la "Deriva Semántica" (Semantic Drift)
Si el único objetivo de los agentes es maximizar la tasa de éxito cooperativa ($R = 1.0$ si se entienden, $0.0$ si fallan), los modelos convergerán rápidamente en un **código encriptado alienígena** no-humano. Mapearán conceptos en dimensiones vacías de forma arbitraria (ej. el token `cuchara` pasará a representar el concepto abstracto de `peligro`), perdiendo la estructura del lenguaje natural y provocando un olvido catastrófico imposible de revertir en grados académicos posteriores.

Para anclar la comunicación al lenguaje humano:
*   **Anclaje Fijo de Capa 1 (Vocabulario)**: Generamos un diccionario conceptual de 8.192 entradas humanas (conjunciones, términos lógicos, emociones, etc.) y computamos sus embeddings densos iniciales mediante `fastembed` (MiniLM-L6-v2).
*   **Congelamiento de Capas de Traducción (Capa 2 y Capa 4)**: La matriz de embedding de entrada (Capa 2: $W_E$, dim 384 -> 256) y el LM Head de salida (Capa 4: $W_{LM\_Head}$, dim 256 -> 8192) se inicializan basándose en estos embeddings fijos y se **congelan permanentemente** durante el juego referencial.
*   Al bloquear los traductores, el **Specialist Core (Capa 3)** del Hablante está obligado a emitir tokens que correspondan a su semántica humana nativa, y el Specialist Core del Oyente debe recibirlos y descodificarlos bajo esa misma estructura, forzando la evolución sintáctica dentro del espacio conceptual humano preestablecido.

### 3. Canal Afectivo y Teoría de la Emoción Construida (Emotional Grounding)
La comunicación infantil no es solo descriptiva de hechos físicos, sino principalmente interoceptiva y relacional. Introducimos una dimensión de **Alineación Afectiva** (Social Influence / Empathy-weighted Reward) inspirada en la teoría de la emoción construida:
*   **Interocepción (Estado Interno)**: Además del "concepto físico" a transmitir, el Hablante es condicionado por un estado emocional/fisiológico representado por un token de Capa 1 (ej. *miedo*, *hambre*, *dolor*).
*   **Alineación Dinámica**: El Hablante emite un mensaje compuesto por:
    1. El token conceptual (el qué).
    2. El token emocional (el tono / estado interoceptivo).
*   **Recompensa Empática**: Para recibir la recompensa máxima ($R_{total} = 1.0$), el Oyente no solo debe predecir correctamente el concepto objetivo (ej. *fuego*), sino también identificar el estado afectivo del Hablante (ej. *miedo*). Si acierta el concepto pero falla la emoción, la recompensa sufre una penalización drástica ($R_{total} = 0.3$), impidiendo que el canal evolucione hacia una transmisión puramente transaccional desprovista de resonancia social.

---

## Proposed Changes

### Componente: Lenguaje IA y Traductor Universal (Capa 1 & 2)

#### [MODIFY] [translator.py](file:///home/joan/Documents/IA/sharing/src/red_pill/inference/bitnet/translator.py)
*   **Expansión del Léxico**: Añadir explícitamente conceptos afectivos y fisiológicos fundamentales tanto en español como en inglés al `_generate_core_lexicon()`:
    *   *Conceptos*: `"miedo"`, `"alegría"`, `"ira"`, `"tristeza"`, `"dolor"`, `"hambre"`, `"fear"`, `"joy"`, `"anger"`, `"sadness"`, `"pain"`, `"hunger"`.
*   **Mapeo de Embeddings**: Actualizar la generación de embeddings de Capa 1 para que estos conceptos tengan sus vectores densos correctos inicializados con `fastembed`.
*   **Compatibilidad con Stubs**: Asegurar que tanto `encode()` como `_load_or_create_vocab()` extraigan valores usando `.tolist()` para ser $100\%$ compatibles con los mocks unitarios de `conftest.py`.

---

### Componente: Arena PopuLoRA Interactiva Afectiva

#### [MODIFY] [dataset_breeder.py](file:///home/joan/Documents/IA/sharing/src/red_pill/inference/bitnet/dataset_breeder.py)
*   **Conceptos de Entrenamiento**: Extender `target_concepts` para incluir tanto entidades físicas (`gato`, `agua`, `búnker`, `peligro`) como estados afectivos/fisiológicos (`miedo`, `dolor`, `hambre`, `alegría`).
*   **Lotes Duales**: Modificar `generate_batch` para que devuelva pares estructurados de `(concepto_físico, estado_emocional)`.

#### [MODIFY] [train_populora.py](file:///home/joan/Documents/IA/sharing/src/red_pill/inference/bitnet/train_populora.py)
*   **Bucle de Arena Multitarea (Concepto + Emoción)**:
    *   Modificar la entrada del Hablante para que contenga tanto el token ID del concepto físico como el token ID del estado emocional: `[concepto_id, emoción_id, 0]`.
    *   El Hablante emite un mensaje discreto diferenciable de 3 tokens mediante ST-Gumbel-Softmax.
    *   El Oyente decodifica el mensaje y genera logits predictivos para ambos componentes (la predicción del concepto físico y la del estado de ánimo).
    *   La pérdida conjunta se calcula como la suma de las pérdidas de entropía cruzada:
        $$\mathcal{L} = \mathcal{L}_{concepto} + \beta \mathcal{L}_{emoción}$$
        donde $\beta = 1.0$ controla el peso del canal afectivo.
    *   Actualizar el cálculo de exactitud y promoción académica para requerir una tasa combinada de entendimiento mutuo superior al $80\%$.

---

### Componente: Suites de Tests de Inmunidad

#### [MODIFY] [test_bitnet_scratch_training.py](file:///home/joan/Documents/IA/sharing/tests/test_bitnet_scratch_training.py)
*   Actualizar las pruebas unitarias para validar:
    1. Que `translator.py` codifica y decodifica correctamente los nuevos tokens emocionales.
    2. Que el test `test_translator_encode_decode` no falle en entornos con mocks de `fastembed` (gracias a la lógica de fallback condicional de similitud).
    3. Que `dataset_breeder.py` genera lotes duales coherentes.
    4. Que la arena ejecuta un paso completo de entrenamiento optimizando ambos canales simultáneamente.

---

## Verification Plan

### Automated Tests
- Ejecutar `pytest tests/test_bitnet_scratch_training.py -v` en la terminal local aislada por `bunker_isolation`.
- Comprobar que no hay advertencias de desalineación dimensional en `BitLinear`.

### Manual Verification
- Iniciar un dry-run de entrenamiento con 2 épocas ejecutando:
  `python src/red_pill/inference/bitnet/train_populora.py`
  Verificar que la pérdida promedio de ambos canales decae y que la tasa de entendimiento mutuo aumenta paulatinamente.

---

## Referencias Bibliográficas

1.  **Lazaridou et al. (2017)**. *Multi-Agent Cooperation and the Emergence of (Natural) Language*. [arXiv:1612.07182](https://arxiv.org/abs/1612.07182). (Juegos referenciales y de señalización fundacionales).
2.  **Jang et al. (2016)**. *Categorical Reparameterization with Gumbel-Softmax*. [arXiv:1611.01144](https://arxiv.org/abs/1611.01144). (Teoría matemática del estimador ST-Gumbel-Softmax).
3.  **Jaques et al. (2019)**. *Social Influence as Intrinsic Motivation for Multi-Agent Reinforcement Learning*. [arXiv:1810.08647](https://arxiv.org/abs/1810.08647). (Alineación social e influencia causal como precursores de empatía y comunicación).
4.  **Schmid et al. (2023)**. *Co-construction of Emotion via Multi-Agent Interaction*. (Estudios de computación afectiva y teoría de la emoción construida en MARL).
5.  **Lu et al. (2020)**. *Countering Language Drift in Multi-Agent Referential Games*. [arXiv:2006.01309](https://arxiv.org/abs/2006.01309). (Control de la deriva semántica en MARL).
