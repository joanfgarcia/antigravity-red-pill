# Distiller Fidelity Eval (both-sides coverage)

Does the summary reflect BOTH the user and the assistant? BASE vs TUNED prompt.

| Model | Prompt | Both-sides | User-side | Asst-side |
|---|---|---|---|---|
| phi_mini | base | 1/3 | 2/3 | 2/3 |
| phi_mini | tuned | 3/3 | 3/3 | 3/3 |

## phi_mini
### base
- [philosophical] ✗ only-user: La identidad se forma por actos, no solo por recuerdos.
- [caching] ✓: Sugiere cachear embeddings en disco para mejorar el rendimiento, pero advierte sobre la corrupción del caché si se modifica el modelo, recomendando invalidar el caché por hash del 
- [db_decision] ✗ only-asst: Continuar con SQLite debido al volumen de datos y evitar complicaciones adicionales.

### tuned
- [philosophical] ✓: El usuario plantea que los actos definen la identidad, mientras que el asistente argumenta que la continuidad del yo, que incluye memoria, es esencial para la identidad.
- [caching] ✓: El usuario sugiere cachear embeddings en disco para mejorar el rendimiento, mientras que el asistente advierte sobre la corrupción del caché en disco si se cambia el modelo, recome
- [db_decision] ✓: El usuario pregunta si migrar a Postgres o seguir con SQLite, y el asistente sugiere continuar con SQLite debido al volumen de datos y evitar complicaciones.
