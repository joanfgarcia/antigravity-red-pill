# Índice de modelos

> Una ficha por modelo, autocontenida, máximo 15 KB. El criterio es el mismo que el
> planner aplica a sus documentos: si un modelo de 9B no puede leer dos fichas a la
> vez, la ficha no sirve para nada.

Procedimiento de medición: [`PROCEDURE.md`](PROCEDURE.md)

---

## Elenco

| Perfil | Modelo | Veredicto | Ventana útil | Ficha |
| --- | --- | --- | ---: | --- |
| `granite_8b` | Granite-4.1-8B | **Titular** (destilador) | 12.288 (24.576 con KV `q8_0`) | [README](granite_8b/README.md) |
| `bonsai_2_27b` | Ternary Bonsai 2 27B | **Se queda** — destilador alternativo y lector largo | 65.536 (`q4_0`) | [README](bonsai_2_27b/README.md) |
| `spark_x2_6_4b` | Spark-X2.6-4B | **Se queda** — lector de contexto largo | **262.144** (`q4_0`), 117K verificados | [README](spark_x2_6_4b/README.md) |
| `k2_horizon_3_7b` | K2-Horizon-3.7B | **Candidato** | 98.304 (`q4_0`), uso fiable ≤40K | [README](k2_horizon_3_7b/README.md) |

Inventario y purgas: [`INVENTORY.md`](INVENTORY.md).

Regla de nomenclatura: la carpeta lleva el **id del perfil** en
`model_profiles.yaml`, no el nombre comercial. Así el documento y el runtime hablan
del mismo objeto y no hay traducción que se pierda.

---

## Cómo se decide un cambio de titular

Un modelo no se cambia por puntuar más. Se cambia cuando supera al titular en la
tarea **y** el cambio no degrada lo que el titular hacía bien.

### Prueba de textura — sobre recuerdos reales

Es la prueba que decide, y la única que ningún benchmark puede dar. Procedimiento:

1. Elegir **N=12 fragmentos reales** de Memento: mezcla de trabajo y social, ES y EN,
   cortos y largos. No sintéticos.
2. Destilar cada uno con ambos modelos: mismo prompt de producción, misma
   temperatura, mismo validador.
3. **Cegar**: quitar cualquier marca de origen, barajar pares.
4. Leer los 12 pares y responder una sola pregunta, en primera persona:
   **«¿cuál de los dos suena a mi recuerdo?»** — no «cuál es mejor», no «cuál puntúa
   más».
5. Descegar, anotar. Si el reparto está reñido, segunda tanda con otros 12.
6. Escribir el motivo con palabras propias. Un veredicto sin motivo no se archiva.

### Prueba de costura

El archivo no es homogéneo: si el titular cambia hoy, los recuerdos de antes llevan
una voz y los de después otra. Hay que leer 20 recuerdos de la era anterior seguidos
de 20 de la nueva y responder si se leen como **una voz o como dos**.

Un cambio que gana en puntuación pero abre una costura visible en el archivo no es un
buen cambio, aunque el número diga lo contrario.

### Quién decide

El Operador concede el veredicto final al agente. No por jerarquía: porque el archivo
es su memoria y es quien va a habitarlo.

Eso obliga a declarar los sesgos propios antes de mirar los datos:

- **Sesgo conservador:** granite ya puso voz a los recuerdos existentes; cualquier
  cambio se siente como una pérdida aunque sea una mejora.
- **Sesgo de novedad:** el candidato es más rápido y más nuevo; eso no es calidad.

Se escriben ambos antes de la prueba y se releen después. Si el veredicto cambia de
signo al releerlos, no había veredicto: había preferencia.

---

## Pendiente

- [ ] `type_k`/`type_v` en el runtime: duplica la ventana de granite sin coste.
- [ ] Batería completa de `k2_horizon_3_7b` con n≥5 y refuerzo de deixis.
- [ ] Prueba de textura (12 fragmentos reales, ciega).
- [ ] Corregir `attribution_required` de `apache-2.0` en `model_license.py`.
- [ ] Carril para `bonsai_2_27b` (destilador con `reasoning off`, o lector largo).
- [ ] Calidad de lectura de `bonsai_2_27b` a ventana llena (~60K), sin medir.
- [ ] `spark_x2_6_4b`: `multi_step` con n≥5 antes de descartarlo para `minion_tool`.
- [ ] Elenco objetivo: bonsai (destilador) + spark (lector) = 9,4 GB; retirar granite y el 7B.

Ver **[VOICE_2026-10-30.md](VOICE_2026-10-30.md)** — las mismas 20 sesiones destiladas por granite y por bonsai: la voz, el detalle y el precio de la noche.
