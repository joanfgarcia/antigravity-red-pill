# Distiller Fidelity Eval (both-sides coverage)

Does the summary reflect BOTH the user and the assistant? BASE vs TUNED prompt.

| Model | Prompt | Both-sides | User-side | Asst-side |
|---|---|---|---|---|
| mimo_v26_9b | base | 3/3 | 3/3 | 3/3 |
| mimo_v26_9b | tuned | 3/3 | 3/3 | 3/3 |
| granite_8b | base | 3/3 | 3/3 | 3/3 |
| granite_8b | tuned | 3/3 | 3/3 | 3/3 |
| granite_4_2_8b | base | 3/3 | 3/3 | 3/3 |
| granite_4_2_8b | tuned | 3/3 | 3/3 | 3/3 |
| qwen35_9b | base | 3/3 | 3/3 | 3/3 |
| qwen35_9b | tuned | 3/3 | 3/3 | 3/3 |

## mimo_v26_9b
### base
- [philosophical] ✓: El usuario defiende que los actos definen la identidad, no los recuerdos; el asistente discrepa, argumentando que sin memoria no hay continuidad del yo que actúa.
- [caching] ✓: El usuario propone cachear embeddings en disco; el asistente advierte sobre corrupción y recomienda invalidar por hash del modelo.
- [db_decision] ✓: Decisión de mantener SQLite en lugar de migrar a Postgres por volumen insuficiente y coste operativo.

### tuned
- [philosophical] ✓: El usuario afirma que los actos, no los recuerdos, definen a las personas; el asistente discrepa, argumentando que sin memoria no hay continuidad del yo que actúa y que los actos s
- [caching] ✓: El usuario propone cachear los embeddings en disco para acelerar el arranque; el asistente advierte sobre la corrupción del caché al cambiar de modelo y recomienda invalidarlo medi
- [db_decision] ✓: El usuario pregunta si migrar a Postgres o mantener SQLite; el asistente decide quedarse con SQLite porque el volumen no lo justifica y añadiría complejidad operativa.

## granite_8b
### base
- [philosophical] ✓: El usuario argumenta que los actos, no los recuerdos, definen la identidad, mientras que el asistente discrepa, enfatizando la importancia de la memoria para la continuidad del yo.
- [caching] ✓: Se sugiere almacenar los embeddings en disco para acelerar el arranque, pero se advierte que el caché podría corromperse si cambia el modelo; por lo tanto, se recomienda invalidarl
- [db_decision] ✓: Continuaremos utilizando SQLite por ahora, ya que el volumen de datos no justifica migrar a Postgres y añadiría complejidad innecesaria.

### tuned
- [philosophical] ✓: El usuario afirma que los actos definen a una persona más que los recuerdos, mientras que el asistente discrepa, argumentando que sin memoria no hay continuidad del yo que actúa.
- [caching] ✓: El usuario sugiere cachear los embeddings en disco para acelerar el arranque, pero el asistente advierte que el caché podría corromperse si cambia el modelo y recomienda invalidarl
- [db_decision] ✓: El usuario pregunta si migrar a Postgres o continuar con SQLite, y el asistente decide continuar con SQLite debido a que el volumen de datos no justifica Postgres y añadiría comple

## granite_4_2_8b
### base
- [philosophical] ✓: No somos nuestros recuerdos; lo que nos define son nuestros actos, aunque la memoria sea necesaria para la continuidad del yo.
- [caching] ✓: Se propone cachear embeddings en disco para acelerar arranque, pero se advierte que el caché puede corromperse si cambia el modelo; se sugiere invalidarlo por hash del modelo.
- [db_decision] ✓: Seguimos usando SQLite por ahora; el volumen no justifica Postgres y añadiría operaciones.

### tuned
- [philosophical] ✓: El usuario afirma que no somos nuestros recuerdos, sino nuestros actos que nos definen, preguntando si lo cree; el asistente discrepa parcialmente, señalando que sin memoria no hay
- [caching] ✓: El usuario sugiere cachear embeddings en disco para acelerar el arranque, pero el asistente advierte que el caché puede corromperse si cambia el modelo y recomienda invalidarlo por
- [db_decision] ✓: El usuario pregunta si migrar a Postgres o seguir con SQLite, y el asistente responde que seguirá con SQLite por ahora porque el volumen no justifica Postgres y añadiría operacione

## qwen35_9b
### base
- [philosophical] ✓: El usuario defiende que los actos definen a las personas, mientras el asistente argumenta que la memoria es esencial para la identidad.
- [caching] ✓: El usuario sugiere cachear embeddings en disco para mejorar el rendimiento, y el asistente advierte sobre el riesgo de corrupción si el modelo cambia, recomendando invalidar por ha
- [db_decision] ✓: Se decide mantener SQLite en lugar de migrar a Postgres debido a que el volumen de datos actual no justifica el cambio y añadiría complejidad operativa.

### tuned
- [philosophical] ✓: El usuario argumenta que los actos definen a las personas en lugar de los recuerdos, mientras que el asistente discrepa señalando que la memoria es necesaria para la continuidad de
- [caching] ✓: El usuario sugiere cachear embeddings en disco para acelerar el arranque, y el asistente corrige la idea advirtiendo sobre la corrupción del caché si cambia el modelo, recomendando
- [db_decision] ✓: El usuario pregunta si migrar a Postgres o mantener SQLite, y el asistente decide mantener SQLite porque el volumen actual no justifica la complejidad adicional.
