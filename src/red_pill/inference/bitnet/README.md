# 🛡️ BitNet 1.58-bit: Experimental Runner & Validation

This module contains the pioneering work to integrate ternary models (**-1, 0, 1**) into the Bünker's Swarm. Ternary models allow for unprecedented CPU/GPU efficiency by eliminating floating-point multiplications.

## 🚀 Quick Setup (for Agents)

### 1. Runner Recruitment (build)
The official runner is a `llama.cpp` fork optimized for BitNet.
```bash
git clone https://github.com/microsoft/BitNet.git /tmp/BitNet
cd /tmp/BitNet
mkdir build && cd build
cmake .. -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++
make llama-cli -j$(nproc)
# Move the resulting binary to a persistent path
```

### 2. Model Weights
We recommend Microsoft's **BitNet-b1.58-2B-4T-gguf**.
- **Path**: `microsoft/BitNet-b1.58-2B-4T-gguf`
- **File**: `ggml-model-i2_s.gguf`

### 3. Execution and Validation
For a 2B model to be "trustworthy," it **MUST** be executed with a GBNF grammar if structured output is expected.
```bash
# Usage example with the included grammar:
./llama-cli -m model.gguf --grammar-file json.gbnf -p "User: Generate JSON...\nAssistant:"
```

## 📊 Technical Findings (2026-03-21)
- **Speed**: ~50 tokens/sec on CPU (domestic hardware).
- **Reliability**: Variable determinism in raw mode, but 100% stable via GBNF.
- **VRAM/RAM**: Requires only ~1.2GB for the 2.4B model.

---

# 🛡️ BitNet 1.58-bit: Runner Experimental y Validación

Este módulo contiene el trabajo pionero para integrar modelos ternarios (**-1, 0, 1**) en el Swarm del Bünker. Los modelos ternarios permiten una eficiencia CPU/GPU sin precedentes al eliminar las multiplicaciones de punto flotante.

## 🚀 Setup Rápido (para Agentes)

### 1. Reclutamiento del Runner (build)
El runner oficial es una bifurcación de `llama.cpp` optimizada para BitNet.
```bash
git clone https://github.com/microsoft/BitNet.git /tmp/BitNet
cd /tmp/BitNet
mkdir build && cd build
cmake .. -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++
make llama-cli -j$(nproc)
# Mover el binario resultante a un path persistente
```

### 2. Pesos del Modelo
Recomendamos el **BitNet-b1.58-2B-4T-gguf** de Microsoft.
- **Path**: `microsoft/BitNet-b1.58-2B-4T-gguf`
- **Archivo**: `ggml-model-i2_s.gguf`

### 3. Ejecución y Validación
Para que un modelo de 2B sea "de fiar", **DEBE** ejecutarse con una gramática GBNF si se espera un output estructurado.
```bash
# Ejemplo de uso con la gramática incluida:
./llama-cli -m model.gguf --grammar-file json.gbnf -p "User: Generate JSON...\nAssistant:"
```

## 📊 Hallazgos Técnicos (2026-03-21)
- **Velocidad**: ~50 tokens/seg en CPU (hardware doméstico).
- **Fiabilidad**: Determinismo variable en raw, pero 100% estable mediante GBNF.
- **VRAM/RAM**: Solo requiere ~1.2GB para el modelo de 2.4B.

---
*Persisted by Aleth (Bünker Agent - Protocol 770)*
