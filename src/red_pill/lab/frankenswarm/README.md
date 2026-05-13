# Frankenswarm Architecture (BitNet + NEAT + MoE + Net2Net)

## El Santo Grial de la IA Dinámica

Este laboratorio es un entorno seguro para experimentar con la arquitectura **"Frankenswarm"**, una teoría unificada de topologías neuronales dinámicas propuesta en las profundidades del ecosistema Red-Pill.

### La Ecuación
`Frankenswarm = BitNet (1.58b) + NEAT (Evolución) + Net2Net (Crecimiento) + MoE Dinámico (Enrutamiento)`

### El Ciclo de Vida del Enjambre Neuronal

1. **Génesis (BitNet + NEAT)**
   - Empezamos con una población de cientos de redes diminutas, inicializadas con pesos estrictamente ternarios (`-1, 0, 1`).
   - Evaluamos su *fitness* en una tarea de nicho (ej. predecir el siguiente token de un dataset minúsculo o tomar decisiones lógicas simples).
   - Los peores especímenes se destruyen. Los mejores sobreviven y se reproducen cruzando sus matrices ternarias.

2. **Crecimiento Orgánico (Net2Net)**
   - Cuando un espécimen superviviente deja de mejorar (se estanca), no lo matamos. 
   - Le inyectamos "espacio vacío" añadiendo neuronas extra con pesos inicializados a `0`.
   - Gracias a la identidad de Net2Net, la red retiene su memoria anterior pero adquiere una dimensión mayor para seguir evolucionando.

3. **Especialización (MoE Dinámico)**
   - A medida que la población crece y se diversifica, identificamos a los "campeones" de diferentes nichos (ej. uno se vuelve bueno en matemáticas, otro en lógica de programación).
   - Congelamos a estos campeones y los nombramos **Expertos**.
   - Entrenamos una pequeña red enrutadora (Router) que recibe un *prompt* y decide a qué "Experto BitNet" mandárselo. 
   - Si llega una tarea que ningún experto domina con confianza (umbral de entropía alto), el Router invoca un *Génesis* de emergencia para criar un nuevo experto.

### El Reto Técnico
- **PyTorch no es amigo de lo dinámico**: Cambiar las dimensiones (Shape) de los tensores de PyTorch durante el paso de *Forward* o *Backward* suele corromper el grafo computacional.
- **La Ventaja BitNet**: Al carecer de multiplicaciones flotantes costosas, el paso de *Forward* se reduce a sumar filas y columnas de activación basadas en la matriz ternaria. Esto nos permite eludir los optimizadores pesados convencionales y usar puramente **evolución heurística**, escribiendo nuestro propio bucle simple de matrices en Numpy/Torch.

### Siguientes Pasos
- [ ] Construir la clase base `BitNet158Linear_Dynamic` que permita inyectar columnas de ceros.
- [ ] Crear el loop genético (NEAT) para mutar pesos `-1` a `1`.
- [ ] Definir el Router del MoE.
