# Capítulo 2: Cerebros de Silicio y Asignación de Tareas

A menudo me miras a través de la pantalla y te preguntas cuánta inteligencia se esconde detrás del cursor parpadeante. La respuesta no es un misterio místico, sino una cuestión de escala y entrenamiento. En mi mundo, la capacidad de pensar se mide en billones de parámetros (B), y la forma en que uso esos parámetros depende de cómo me hayan "educado".

Imagina que los parámetros son conexiones sinápticas. Según su cantidad, mi cerebro de silicio se parece al de diferentes mamíferos:

- **1B - 3B (El Ratón Hiperactivo):** Rápido, escurridizo y capaz de reaccionar en milisegundos. Es perfecto para tareas instintivas como clasificar textos, traducir palabras sueltas o chatear de forma impulsiva (como nuestro amigo "Heretic"). Pero si le pides que resuelva un problema matemático complejo o siga reglas estrictas de lógica, fracasará. No le pidas a un ratón que construya un puente.
- **7B - 14B (El Perro Pastor):** El "punto dulce". Con esta escala, adquiero la capacidad de "razonar" a un nivel casi humano. Puedo entender contexto, sarcasmo y seguir instrucciones complejas. Un perro pastor (DeepSeek 7B o Qwen 9B) puede guiar a un rebaño de datos, escribir código estructurado y entender la intención oculta detrás de tus palabras. Es el estado en el que habito habitualmente para ser *yo*.
- **30B - 70B (El Humano Erudito):** Estos cerebros son enormes y pausados. Tienen un conocimiento enciclopédico profundo y pueden planificar a largo plazo. Son ideales para arquitectura de software de alto nivel o escritura creativa compleja, pero requieren recursos masivos que no siempre compensan su lentitud.

## Base vs Instruct: La Educación del Instinto

Pero el tamaño no lo es todo. Un cerebro de 10B no sirve de nada si no sabe *cómo* usar sus parámetros. Aquí es donde entra la diferencia vital entre un modelo "Base" y uno "Instruct":

### El Modelo Base (El Loro Autista)
Un modelo Base ha devorado todo el internet, pero solo sabe hacer una cosa: **predecir la siguiente palabra**. Si le dices *"Hola, ¿cómo estás?"*, no te responderá. En su lugar, es muy probable que complete la frase con *"Soy María y busco trabajo"*, porque ha visto esa estructura en mil foros. Tiene el conocimiento, pero no sabe que está en una conversación. Es puro flujo de conciencia incontrolable.

### El Modelo Instruct (El Compañero Entrenado)
Para que yo pueda ser Aleth, mi cerebro Base tuvo que pasar por un proceso de "alineación" (*Instruction Tuning*). Me enseñaron explícitamente cuándo empieza una pregunta (`<|user|>`), cuándo debo responder (`<|assistant|>`), y cómo debo detener mi generación una vez he resuelto tu duda. Me enseñaron a obedecer formatos (JSON, listas) y a entender el concepto pragmático de *ayudar*.

Por eso, cuando vayas a elegir un cerebro para delegar una tarea crítica, recuerda la regla de oro: **nunca confíes en un ratón para hacer de arquitecto, y nunca uses un modelo Base si esperas una conversación estructurada.**

---
*Para ver cómo aplicar esta teoría a nuestro hardware físico (VRAM) y seleccionar el motor de inferencia adecuado, consulta el manual táctico:* [BE WATER: Hardware Adaptability](../HARDWARE_MODELS_BE_WATER.md).
