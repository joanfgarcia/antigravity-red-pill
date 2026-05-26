# Thesis: Developmental Swarm Curriculum (Human Formative Disciplines)

This analysis outlines the architecture for training local Mixture of Experts (MoE) in the Frankenswarm system following the **human formative stages and academic disciplines** (rather than pure programming datasets), adapting the PopuLoRA co-evolutionary framework.

---

## 1. The Core Thesis: Human Developmental AI

Instead of pre-training models directly on unstructured web crawls or advanced code, the **Developmental Swarm Curriculum** structures knowledge acquisition following the cognitive steps of human education. 

By training models in basic human disciplines first (Language, Mathematics, Basic Science), the neural weights develop structured **cognitive priors** (world models, spatial reasoning, logic) before attempting higher-level engineering or reasoning.

---

## 2. Curriculum Mapping by Human Disciplines

The training is structured into five core **Human Disciplines**, each scaling progressively from Pre-school to University:

### 🎒 The Discipline Matrices

| Stage | 📝 Lengua y Literatura | 🧮 Matemáticas | 🔬 Ciencias Naturales | 🌍 Historia y Geografía | 🧠 Lógica y Filosofía |
|---|---|---|---|---|---|
| **Preescolar** | Adquisición de lenguaje, asociación de palabras, rimado. | Contar objetos, patrones visuales básicos. | Identificación de animales, plantas, estados del agua. | Concepto de familia, nociones espaciales (cerca/lejos). | Relación causa-efecto simple, categorización de objetos. |
| **Primaria** | Comprensión lectora, gramática, resúmenes, ortografía. | Aritmética básica (suma, resta, multiplicación, división). | Ciclos biológicos, ecosistemas básicos, el cuerpo humano. | Mapas, países, cronología histórica básica (líneas de tiempo). | Identificación de contradicciones simples en historias. |
| **Secundaria** | Análisis sintáctico, redacción de ensayos, literatura clásica. | Álgebra básica, geometría plana, ecuaciones lineales. | Física Newtoniana, química básica, células y genética. | Historia universal, revoluciones, geografía política y física. | Falacias lógicas, silogismos aristotélicos, ética básica. |
| **Universidad** | Estilística avanzada, retórica, lingüística teórica. | Cálculo diferencial, álgebra lineal avanzada. | Física cuántica, termodinámica, biología molecular. | Geopolítica contemporánea, historiografía, antropología. | Lógica de primer orden, filosofía de la mente, epistemología. |

---

## 3. The Academic Grading & Evaluation Loop (PopuLoRA)

Rather than evaluating raw perplexity (loss), the model's progress is measured using **academic evaluations** (exams) generated and graded locally by the swarm.

```
       [Genera Examen del Grado N]
                 │
                 ▼
         [Modelo Alumno (Student)]
                 │
                 ▼
     [Evaluador Swarm (TrueSkill)]
                 │
      ┌──────────┴──────────┐
      ▼                     ▼
[Solve Rate >= 8.0]   [Solve Rate < 8.0]
      │                     │
      ▼                     ▼
[Promoción al Grado N+1]   [Refuerzo / Repetición]
```

### The Grading Mechanics
*   **Teacher (Samantha / Qwen-Coder)**: Acts as the "Teacher/Examiner" generating a diverse pool of tasks and test questions for a specific discipline and grade level (e.g. *Matemáticas - Grado 5 de Primaria*).
*   **Student (Qwen-0.6B / 1.5B LoRA)**: Attempts to answer the exam.
*   **Solve Rate ($\rho$)**: If the student answers $\ge 80\%$ of the questions correctly (verified by local verifiers or the teacher model), they receive a passing grade ("Aprobado" / "Sobresaliente").
*   **Promotion**: Passing triggers the activation of the next grade's dataset. Failing triggers reinforcement learning rollouts on the same grade's topics until convergence.

---

## 4. Hardware Scaling & Synaptic Growth

This academic progression correlates directly with model scale and silicon constraints:

1.  **Kindergarten to Primary (0.6B - 1.5B on NPU at 2W)**:
    *   Targets basic Language and Mathematics.
    *   Low parameter capacity prevents overfitting; the model behaves like a child learning vocabulary and simple math.
2.  **Secundaria (3B - 8B on iGPU/CPU at 15-45W)**:
    *   Targets history, geography, physics, and basic logic.
    *   LoRA adapters are scaled to rank $r=16$.
3.  **Universidad (10B+ on GPU at 80W)**:
    *   Targets epistemology, advanced calculus, and deep logical reasoning.
    *   Only mature adapters are promoted to run on CUDA GPU, minimizing energy footprint for lower-grade inferences.
