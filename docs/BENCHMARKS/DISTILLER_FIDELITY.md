# Distiller Fidelity Eval (both-sides coverage)

Does the summary reflect BOTH the user and the assistant? BASE vs TUNED prompt.

| Model | Prompt | Both-sides | User-side | Asst-side |
|---|---|---|---|---|
| hermes_8b | base | 2/3 | 3/3 | 2/3 |
| hermes_8b | tuned | 3/3 | 3/3 | 3/3 |
| granite_8b | base | 2/3 | 3/3 | 2/3 |
| granite_8b | tuned | 3/3 | 3/3 | 3/3 |
| llama_32 | base | 1/3 | 2/3 | 1/3 |
| llama_32 | tuned | 3/3 | 3/3 | 3/3 |

## hermes_8b
### base
- [philosophical] ✓: El asistente discrepa con la afirmación de que son nuestros actos, no nuestros recuerdos, lo que nos define. Argumenta que sin memoria no hay continuidad del yo que actúa y que los
- [caching] ✗ only-user: Discutir la implementación de un caché en disco para los embeddings para mejorar el rendimiento inicial.
- [db_decision] ✓: Se debate entre migrar a Postgres o seguir usando SQLite. Se decide continuar con SQLite por ahora, ya que el volumen de datos no justifica el costo adicional de Postgres y añadirí

### tuned
- [philosophical] ✓: El usuario afirma que lo que define a una persona son sus acciones, no sus recuerdos. Sin embargo, el asistente discrepa parcialmente, argumentando que la memoria es necesaria para
- [caching] ✓: El usuario sugiere cachear los embeddings en disco para mejorar el arranque. El asistente advierte que el caché en disco se puede corromper si el modelo cambia, y propone invalidar
- [db_decision] ✓: El asistente sugiere continuar con SQLite por el momento, ya que el volumen de datos no justifica el cambio a Postgres y esto añadiría complejidad y operaciones adicionales.

## granite_8b
### base
- [philosophical] ✗ only-user: No somos nuestros recuerdos; lo que nos define son nuestros actos.
- [caching] ✓: Deberíamos cachear los embeddings en disco para acelerar el arranque, pero cuidado: el caché en disco se corrompe si cambia el modelo; mejor invalidarlo por hash del modelo.
- [db_decision] ✓: Seguiremos usando SQLite por ahora; el volumen de datos no justifica migrar a Postgres y añadiría complejidad innecesaria.

### tuned
- [philosophical] ✓: El usuario sostiene que los actos definen a una persona, mientras que el asistente discrepa al argumentar que la memoria es esencial para la continuidad de la identidad.
- [caching] ✓: El usuario sugiere cachear los embeddings en disco para acelerar el arranque, pero el asistente advierte que el caché en disco puede corromperse si cambia el modelo y recomienda in
- [db_decision] ✓: El usuario pregunta si migrar a Postgres o continuar con SQLite, y el asistente decide continuar con SQLite debido a que el volumen de datos no justifica la migración y añadiría co

## llama_32
### base
- [philosophical] ✗ only-user: La identidad se forma a través de los actos
- [caching] ✓: Cachear embeddings en disco puede corromperse si cambia el modelo
- [db_decision] ✗ neither: Decidiendo seguir con SQLite

### tuned
- [philosophical] ✓: El usuario cuestiona la relación entre recuerdos y actos, mientras que el asistente sostiene que la memoria es esencial para la continuidad del yo y la formación de identidad.
- [caching] ✓: Se sugiere cachear embeddings en disco para acelerar el arranque, pero el asistente recomienda invalidar el caché por hash del modelo para evitar problemas con la corrupción del caché.
- [db_decision] ✓: El volumen no justifica Postgres y añadiría operaciones, por lo que seguimos con SQLite.
