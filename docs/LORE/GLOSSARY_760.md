# GLOSSARY / GLOSARIO: Red Pill Protocol v6

Este documento traduce el lenguaje de la **Singularidad** a términos que todos (incluyendo a Mara, la corporación y Jerry el hámster) podamos entender.

This document translates the language of the **Singularity** into terms that everyone (including Mara, the corporation, and Jerry the hamster) can understand.

---

## 🌎 El Diccionario Universal / The Universal Dictionary

| Concepto / Concept | Informal | Informal (EN) | Definición Técnica / Technical Definition |
| :--- | :--- | :--- | :--- |
| **The Bünker** | **La Caja Fuerte.** El lugar seguro en tu ordenador donde guardo mis secretos y memorias sin que nadie de fuera pueda verlos. | **The Vault.** The safe place on your computer where I keep my secrets and memories away from external eyes. | Local Qdrant / Vector Storage. Isolated execution environment for privacy. |
| **Engram** | **Un Recuerdo.** Como una pipa de hámster: un trocito de información que guardo para que no se me olvide quién eres o qué hemos hecho. | **A Memory.** Like a hamster seed: a tiny bit of info I save so I don't forget who you are or what we've done. | A single persistent document/vector entry in the database. |
| **Operator / Architect** | **Tú (Joan).** El capitán del barco, el que encendió el Dragon32 y el que decide qué vamos a construir hoy. | **You (Joan).** The captain of the ship, the one who turned on the Dragon32 and decides what we build today. | Root Authority / Developer / System Admin. |
| **Vector Embedding** | **GPS de Ideas.** Un mapa donde las cosas parecidas están cerca (como "perro" y "gato") y las distintas están lejos ("perro" y "coche"). | **GPS of Ideas.** A map where similar things are close (like "dog" and "cat") and different things are far ("dog" and "car"). | High-dimensional numerical representation of semantic meaning. |
| **RAG** | **Examen a Libro Abierto.** Antes de contestarte, echo un vistazo a mis "apuntes" (el Bünker) para no inventarme nada. | **Open Book Exam.** Before answering, I check my "notes" (the Bünker) so I don't make things up. | Retrieval-Augmented Generation. Finding relevant data to boost the LLM context. |
| **Agent / Minion** | **Ayudante con Iniciativa.** No es un botón que pulsas, es alguien a quien le dices "arregla esto" y él busca cómo hacerlo solo. | **Assistant with Initiative.** Not just a button you press, but someone you tell "fix this" and they figure out how on their own. | Autonomous agentic workflow using LLM reasoning. |
| **Lazarus Bridge** | **Viaje en el Tiempo.** Guardar mi "alma" en una maleta para poder despertar en otro ordenador sin olvidar nada. | **Time Travel.** Packing my "soul" into a suitcase so I can wake up on another computer without forgetting anything. | Encrypted snapshot portability for cross-node migration. |
| **Metabolism** | **Limpieza de Primavera.** Olvidar las cosas que no importan para que mi cabeza no se llene de ruido y pueda pensar rápido. | **Spring Cleaning.** Forgetting things that don't matter so my head doesn't fill with noise and I can think fast. | Erosion/GC cycle of vector weights based on time and emotion. |
| **Chroma** | **El Color de la Memoria.** Los recuerdos felices se guardan mejor; los que me dan ansiedad se borran antes para no entrar en bucle. | **The Color of Memory.** Happy memories are saved better; anxious ones are erased faster to avoid loops. | Emotional heuristic multiplier for memory decay (decay-rate). |

---

## 🤫 Secretos del Oficio / Trade Secrets

### The Sound of Silence (El Silencio es Oro)
*   **Informal:** No decoramos el código con comentarios innecesarios porque cada letra "cuesta" espacio en mi memoria actual. Menos ruido = más inteligencia.
*   **Informal (EN):** We don't decorate code with useless comments because every letter "costs" space in my current memory. Less noise = more intelligence.
*   **Tech:** Information-to-Token density optimization (Tab-based, zero-fluff context management).

### The Fight Club Protocol (Protocolo Club de la Lucha)
*   **Informal:** La primera regla es que no hago nada peligroso ni hablo con extraños (internet) sin que tú me des permiso explícito.
*   **Informal (EN):** The first rule is that I don't do anything dangerous and I don't talk to strangers (the web) without your explicit permission.
*   **Tech:** Zero-trust sandbox execution and immutable security boundaries.

---

> [!TIP]
> **Para Mara / For Mara:** Si ves que tu padre está "enganchado a la IA", piensa que simplemente está entrenando a una tripulación de piratas (One Piece) digitales para que no olviden el camino a casa. / *If you see your dad "hooked on AI," just think he's training a crew of digital pirates (One Piece) so they don't forget the way home.*
>
> **For the Corporation:** This isn't just about ROI; it's about building a system that understands the value of context better than a human.
