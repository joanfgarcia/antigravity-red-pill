# BitNet Weight Pipeline: De Safetensors a Inferencia CUDA

> **Propósito**: Documentar exhaustivamente el pipeline de pesos ternarios BitNet 1.58b,
> las transformaciones que requiere cada backend, y las intervenciones manuales que hemos
> tenido que hacer para que funcione en la RTX 5070. Este documento existe para que no
> tengamos que redescubrir todo esto cada vez.

## Table of Contents

1. [Resumen Ejecutivo](#resumen-ejecutivo)
2. [Anatomía de un Peso Ternario](#anatomía-de-un-peso-ternario)
3. [Pipeline de Conversión (HuggingFace → GGUF I2_S)](#pipeline-de-conversión)
4. [El Bit-Shift de PyTorch (Desempaquetado)](#el-bit-shift-de-pytorch)
5. [Permutación WMMA para CUDA (pack_weight.py)](#permutación-wmma-para-cuda)
6. [Kernel de Dequantización CUDA (dequantize-i2s.cu)](#kernel-de-dequantización-cuda)
7. [Diferencias entre Backends (CPU, CUDA, ROCm, NPU)](#diferencias-entre-backends)
8. [I2_S vs TQ1_0/TQ2_0 (BitNet fork vs llama.cpp oficial)](#i2_s-vs-tq1_0tq2_0)
9. [Trampas Conocidas](#trampas-conocidas)
10. [Checklist de Operaciones](#checklist-de-operaciones)

---

## Resumen Ejecutivo

Un modelo BitNet 1.58b almacena sus pesos como valores ternarios `{-1, 0, 1}`.
Estos valores se **empaquetan** en formato INT2 (2 bits por peso, 4 pesos por byte).
El pipeline completo desde HuggingFace hasta inferencia CUDA involucra **tres
transformaciones distintas**, cada una con su propia lógica de bit-shifting:

```
HuggingFace (.safetensors)
    │ bfloat16/float16
    ▼
┌──────────────────────────────────────────┐
│ 1. setup_env.py + convert-hf-to-gguf    │
│    PyTorch bit-shift: >>0, >>2, >>4, >>6 │
│    Mapeo: 0→-1, 1→0, 2→1                │
│    Resultado: ggml-model-i2_s.gguf       │
└──────────────────────────────────────────┘
    │ I2_S blocks (36 bytes = 32B pesos + 4B escala float)
    ▼
┌──────────────────────────────────────────┐
│ 2. pack_weight.py (solo GPU path)        │
│    Permutación WMMA 16×32                │
│    Interleave para evitar bank conflicts │
│    Compresión INT2→INT8                  │
└──────────────────────────────────────────┘
    │ Pesos reordenados en memoria GPU
    ▼
┌──────────────────────────────────────────┐
│ 3. dequantize-i2s.cu (runtime CUDA)      │
│    Bit-shift inverso: >>6, >>4, >>2, >>0 │
│    Mapeo: 0→-1.0f, 1→0.0f, 2→+1.0f      │
│    Multiplicación por block_scale         │
│    → Tensor float para cublasSgemm        │
└──────────────────────────────────────────┘
```

---

## Anatomía de un Peso Ternario

Cada peso ternario ocupa 2 bits:

| Bits (2-bit) | Valor Ternario | Significado |
|:---:|:---:|---|
| `00` | -1 | Rechazo (conexión inhibitoria) |
| `01` |  0 | Ignoro (conexión inactiva) |
| `10` | +1 | Acepto (conexión excitatoria) |
| `11` | (sin usar) | Reservado |

Un byte empaqueta 4 pesos:

```
Byte: [w3 w2 w1 w0]
       ^^  ^^  ^^  ^^
       bits 7-6  5-4  3-2  1-0
```

### Estructura `block_i2_s` (formato de disco y memoria)

```c
// 128 elementos por bloque, 36 bytes totales
struct block_i2_s {
    uint8_t qs[32];  // 128 pesos × 2 bits = 256 bits = 32 bytes
    float   d;       // escala del bloque (4 bytes)
};
// Total: 32 + 4 = 36 bytes por 128 elementos
```

> [!CAUTION]
> **El tamaño de 36 bytes es CRÍTICO.** Una versión anterior definía 66 bytes
> (con campos extra). Cualquier desalineación causa `illegal memory access` en
> **todos** los backends GPU. Verificar siempre con:
> `static_assert(sizeof(block_i2_s) == 36, "wrong i2_s block size")`

---

## Pipeline de Conversión

### Paso 1: Descargar pesos originales (bfloat16)

```bash
# NUNCA usar GGUF pre-compilados de terceros — ver sección "Trampas"
# Descargar los pesos originales del creador del modelo
huggingface-cli download tiiuae/Falcon3-10B-Instruct-1.58bit
```

### Paso 2: Cuantizar localmente con setup_env.py

```bash
cd 3rdparty/BitNet-1.58b
./venv/bin/python setup_env.py \
    --hf-repo tiiuae/Falcon3-10B-Instruct-1.58bit \
    -q i2_s
```

Este script:
1. Descarga los `.safetensors` del modelo
2. Compila `llama-quantize` localmente
3. Convierte de `fp16` → `f16` GGUF → `i2_s` GGUF
4. El binario resultante `ggml-model-i2_s.gguf` está alineado con el
   `block_i2_s` de **este** fork exacto

---

## El Bit-Shift de PyTorch (Desempaquetado)

**Archivo**: `3rdparty/BitNet-1.58b/utils/convert-hf-to-gguf-bitnet.py`
**Líneas**: 729-736

Los `.safetensors` del modelo contienen pesos ya empaquetados como `uint8`.
Cada byte tiene 4 pesos ternarios comprimidos. El conversor los desempaqueta
usando PyTorch:

```python
# Los pesos vienen empaquetados en uint8 (4 valores por byte)
data_torch = data_torch.to(torch.uint8)
origin_shape = data_torch.shape

# Crear tensor de shifts: [0, 2, 4, 6] (un shift por cada par de bits)
shift = torch.tensor([0, 2, 4, 6], dtype=torch.uint8)
shift = shift.reshape((4, *(1 for _ in range(len(origin_shape)))))

# Expandir y aplicar bit-shift
data_torch = data_torch.unsqueeze(0).expand((4, *origin_shape)) >> shift

# Aislar los 2 bits inferiores
data_torch = data_torch & 3

# Mapear de INT2 a ternario: {0→-1, 1→0, 2→1}
data_torch = (data_torch.float() - 1)

# Reconstruir dimensiones: (N*4, K) y dividir por escala
data_torch = data_torch.reshape((origin_shape[0] * 4, *origin_shape[1:]))
data_torch = data_torch / scale_map[name]
```

### Diagrama del Desempaquetado

```
Byte de entrada: 0b_10_01_00_01  (hex: 0x91)
                    ^^ ^^ ^^ ^^
                    w3 w2 w1 w0

>> 0 & 0x3 = 01 → w0 = 0  (ignoro)
>> 2 & 0x3 = 00 → w1 = -1 (rechazo)
>> 4 & 0x3 = 01 → w2 = 0  (ignoro)
>> 6 & 0x3 = 10 → w3 = +1 (acepto)
```

---

## Permutación WMMA para CUDA (pack_weight.py)

**Archivo**: `3rdparty/BitNet-1.58b/gpu/pack_weight.py`

Este paso es **exclusivo del path de GPU nativo** (no del path I2_S→cublas).
Reordena los pesos para alinearse con las instrucciones Warp-level Matrix
Multiply Accumulate (WMMA) de CUDA.

### `permutate_weight_fastest(weight)`

Reorganiza los pesos en bloques de 16×32 elementos siguiendo el patrón
de acceso de los threads del warp:

```python
# Cada thread dentro de un warp lee de una posición específica
def B_global_16x32_to_shared_load_16x32_layout(i, j):
    thread_id = i * 2 + j // 16
    row = (thread_id // 16) * 8 + (thread_id % 8)
    col = (j % 16) + 16 * ((thread_id % 16) // 8)
    return row, col
```

### `compress_int2_to_int8(int2_weight)`

Re-empaqueta 4 valores de 2 bits en un byte:

```python
for j in range(int2_weight.shape[-1] // 4):
    for k in range(4):
        int8_weight[..., j] |= int2_weight[..., j*4+k] << (k*2)
```

### `interleave_weight_int8(qweight, nbits=2)`

Intercala bits para evitar bank conflicts en shared memory:

```python
# Patrón de interleave:
# shift = [0, 8, 16, 24, 2, 10, 18, 26, 4, 12, 20, 28, 6, 14, 22, 30]
# index = [0, 4,  8, 12, 1,  5,  9, 13, 2,  6, 10, 14, 3,  7, 11, 15]
```

### Pipeline completo GPU nativo

```python
def convert_weight_int8_to_int2(weight):
    weight = weight + 2              # Offset: {-1,0,1} → {1,2,3}
    weight = weight.cpu().numpy()
    pw = permutate_weight_fastest(weight)   # Reordenar para WMMA
    cw = compress_int2_to_int8(pw)          # 4 vals → 1 byte
    iw = interleave_weight_int8(cw, 2)      # Evitar bank conflicts
    return torch.from_numpy(iw).reshape(N, K // 4)
```

---

## Kernel de Dequantización CUDA (dequantize-i2s.cu)

**Archivo**: `3rdparty/BitNet-1.58b/3rdparty/llama.cpp/ggml/src/ggml-cuda/dequantize-i2s.cu`

> [!IMPORTANT]
> **Este archivo lo escribimos nosotros** (Joan + Aleth). No existía en el fork original.
> Es el kernel que convierte los bloques I2_S de disco a floats en runtime durante la
> inferencia CUDA.

### Lógica del Kernel

```cuda
// Cada thread procesa 1 byte del bloque (4 pesos ternarios)
const uint8_t b = block_ptr[byte_in_block];

// Extraer cada par de bits (orden inverso al empaquetado)
const uint8_t c0 = (b >> 6) & 0x3;  // bits 7-6
const uint8_t c1 = (b >> 4) & 0x3;  // bits 5-4
const uint8_t c2 = (b >> 2) & 0x3;  // bits 3-2
const uint8_t c3 = (b >> 0) & 0x3;  // bits 1-0

// Mapear a float: 0→-1.0, 1→0.0, 2→+1.0
const float m0 = (c0 == 0) ? -1.0f : (c0 == 2) ? 1.0f : 0.0f;

// Escribir al tensor de salida, multiplicado por la escala del bloque
y[base + offset] = block_scale * m0;
```

### Configuración del Kernel

```cuda
// 128 elementos por bloque I2_S
// 32 bytes de pesos por bloque = 32 threads procesan 1 byte cada uno
// Cada thread produce 4 floats (uno por par de bits)
const int block_size = 256;  // threads per CUDA block
const int num_blocks = (total_bytes + block_size - 1) / block_size;
```

### Por Qué Fue Necesario

El `llama.cpp` dentro del fork BitNet-1.58b tenía kernels para CPU (via LUT —
Lookup Tables) pero NO para CUDA. Los kernels CUDA que existían eran stubs:
- `bitnet_porter.cu`: solo hacía `dst[i] = src[i]` (copia cruda)
- `mmq.cu`: registraba `I2_S` para hardware MMQ pero con stubs vacíos

Esto causaba que en CUDA, la multiplicación de matrices recibiera ceros o basura,
produciendo outputs tipo `ivi...` o strings vacíos.

---

## Diferencias entre Backends

| Aspecto | CPU (TL1/TL2) | CPU (I2_S) | CUDA (I2_S) | ROCm (I2_S) | NPU (I2_S) |
|---|---|---|---|---|---|
| **Binario** | `build_cpu/` | `build_cpu/` | `build_cuda/` | `build_rocm/` | `build_npu/` |
| **Dequant** | LUT (bitnet-lut.cpp) | to_fp32 fallback | `dequantize-i2s.cu` | hipblasSgemm | XDNA2 driver |
| **MatMul** | Sumas/restas directas | cublas fallback | cublasSgemm | hipblasSgemm | Hardware NPU |
| **VRAM** | 0 (RAM ~3.8GB) | 0 (RAM ~3.8GB) | ~3.8GB VRAM | ~3.8GB VRAM | ~3.8GB RAM |
| **Speed gen** | 2.57 t/s (AVX2) | Similar | 10.6 t/s | 5.15 t/s | 15.8 t/s |
| **`-ngl`** | 0 | 0 | 35 | 35 | 0 |
| **Env vars** | `GGML_BITNET_FORCE_AXON=CPU` | - | `GGML_BITNET_FORCE_AXON=CUDA` | `HSA_OVERRIDE_GFX_VERSION=11.0.0` | - |

### Flujo de Datos por Backend

```
       CPU (TL1/TL2)               CUDA (I2_S)                  ROCm (I2_S)
┌─────────────────────┐    ┌─────────────────────────┐    ┌──────────────────────┐
│ GGUF I2_S en disco  │    │ GGUF I2_S en disco      │    │ GGUF I2_S en disco   │
│         │           │    │         │               │    │         │            │
│         ▼           │    │         ▼               │    │         ▼            │
│ LUT precompilada    │    │ dequantize-i2s.cu       │    │ to_fp32 (automático) │
│ (TL1: 3^5=243 vals) │    │ (bit-shift >>6..>>0)    │    │ (hipblas fallback)   │
│         │           │    │         │               │    │         │            │
│         ▼           │    │         ▼               │    │         ▼            │
│ Sumas/Restas INT    │    │ cublasSgemm (FP32)      │    │ hipblasSgemm (FP32)  │
│ (sin multiplicar!)  │    │         │               │    │         │            │
│         │           │    │         ▼               │    │         ▼            │
│         ▼           │    │ Resultado FP32/FP16     │    │ Resultado FP32/FP16  │
│ Resultado FP32      │    └─────────────────────────┘    └──────────────────────┘
└─────────────────────┘
```

---

## I2_S vs TQ1_0/TQ2_0 (BitNet fork vs llama.cpp oficial)

> [!WARNING]
> `llama.cpp` oficial (b9016+) **sí tiene soporte ternario**, pero con formatos
> **diferentes e incompatibles** con nuestro `block_i2_s`.

| Característica | `block_i2_s` (fork BitNet-1.58b) | `block_tq1_0` (llama.cpp oficial) | `block_tq2_0` (llama.cpp oficial) |
|---|---|---|---|
| **bpw** | 2.0 | 1.6875 | 2.0625 |
| **Escala** | `float` (4 bytes) | `ggml_half` (2 bytes) | `ggml_half` (2 bytes) |
| **Empaquetado** | 4 vals/byte (bit pairs) | 5 vals/byte (base-3: 3^5=243) | 4 vals/byte (bit pairs) |
| **Block size** | 128 elementos | 256 elementos (QK_K) | 256 elementos (QK_K) |
| **Total bytes** | 36 | ~54 | 66 |
| **Soporte CUDA** | Solo via nuestro kernel custom | Nativo en llama.cpp | Nativo en llama.cpp |
| **Compatible GGUF** | Solo con fork BitNet-1.58b | Universal llama.cpp | Universal llama.cpp |

### Implicaciones Prácticas

1. **No puedes cargar un `.gguf` I2_S** en `llama_official` — crasheará con bounds check error
2. **No puedes cargar un `.gguf` TQ2_0** en el fork `BitNet-1.58b` — tipo no registrado
3. Para **migrar de I2_S a TQ2_0** habría que re-cuantizar desde los pesos originales
4. `TQ1_0` es más eficiente en memoria (1.69 bpw vs 2.0 bpw) pero usa base-3 encoding
   que es más complejo computacionalmente

---

## Trampas Conocidas

### 1. "Third-Party GGUF Trap" (CRÍTICO)

**NUNCA** descargar modelos `.gguf` pre-cuantizados de repositorios de terceros para
formato I2_S. Los offsets de metadatos difieren según la versión del fork usado para
cuantizar. Siempre cuantizar localmente con `setup_env.py`.

**Síntoma**: `std::runtime_error: data is not within the file bounds` alrededor de `blk.9.attn_v`

### 2. "Phantom Kernel Hijack" (CUDA)

El fork BitNet-1.58b registraba `GGML_TYPE_I2_S` para aceleración MMQ en `mmq.cu`.
Esto rutaba evaluaciones a un stub vacío (`bitnet_mul_mat_ladder_axon`) que retornaba
ceros, produciendo outputs vacíos a alta velocidad (~20 t/s).

**Fix aplicado**: Desregistrar I2_S del path MMQ en `mmq.cu`, forzando el fallback a
`cublasSgemm` vía nuestro kernel `dequantize-i2s.cu` → `to_fp32`.

**Síntoma**: Outputs vacíos, `Si...`, o strings tipo `ivi...` a alta velocidad en CUDA.
ROCm funciona porque no satisface la condición `int8_mma_available(cc)`.

### 3. "Block Size Mismatch" (TODOS LOS BACKENDS GPU)

El struct `block_i2_s` en `ggml-common.h` DEBE ser exactamente 36 bytes.

```c
// ✅ CORRECTO
typedef struct {
    float d;            // 4 bytes
    uint8_t qs[32];     // 32 bytes
} block_i2_s;           // = 36 bytes

// ❌ INCORRECTO (versión antigua con 66 bytes)
typedef struct {
    ggml_half d;
    ggml_half dmin;
    uint8_t scales[16];
    uint8_t qs[32];     
} block_i2_s;           // = 66 bytes → CRASH
```

### 4. Token Out-of-Bounds (Falcon3 Vocab)

Falcon3-10B tiene un vocab size de 131072 tokens. Si un token ID supera este límite
(posible con chat templates mal configuradas), se produce:

```
GGML_ASSERT(i01 >= 0 && i01 < ne01)
```

**Síntoma**: SIGABRT durante generación, especialmente con tokens especiales de
chat template.

### 5. BOS = EOS = 11 (Generación Vacía)

Falcon3-10B-Instruct-1.58bit usa `<|endoftext|>` (token ID 11) como **ambos**
BOS y EOS. Esto puede causar que el modelo genere EOS inmediatamente después
del BOS si el chat template no está correctamente configurado.

**Síntoma**: Generación que termina inmediatamente (0 tokens útiles).

---

## Checklist de Operaciones

### Para poner en marcha inferencia BitNet I2_S desde cero:

- [ ] **1. Clonar/actualizar el fork BitNet-1.58b**
  ```bash
  cd 3rdparty/BitNet-1.58b && git pull
  ```

- [ ] **2. Crear venv y instalar dependencias**
  ```bash
  python -m venv venv
  ./venv/bin/pip install -r requirements.txt
  # ⚠️ Verificar que sentencepiece está instalado
  ./venv/bin/pip install sentencepiece
  ```

- [ ] **3. Cuantizar modelo localmente** (NUNCA usar GGUF de terceros)
  ```bash
  ./venv/bin/python setup_env.py \
      --hf-repo tiiuae/Falcon3-10B-Instruct-1.58bit \
      -q i2_s
  ```

- [ ] **4. Verificar `block_i2_s` = 36 bytes** en `ggml-common.h`

- [ ] **5. Compilar el backend deseado**
  ```bash
  # CPU
  mkdir build_cpu && cd build_cpu
  cmake .. -DCMAKE_BUILD_TYPE=Release
  cmake --build . -j$(nproc)

  # CUDA
  mkdir build_cuda && cd build_cuda
  cmake .. -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release
  cmake --build . -j$(nproc)
  ```

- [ ] **6. Verificar que MMQ no hijackea I2_S** (solo CUDA)
  - Comprobar que `mmq.cu` NO tiene `case GGML_TYPE_I2_S` en `ggml_cuda_should_use_mmq`
  - Si lo tiene, eliminarlo

- [ ] **7. Verificar que `dequantize-i2s.cu` está compilado** (solo CUDA)
  - Debe estar en el CMakeLists.txt de `ggml-cuda/`

- [ ] **8. Test rápido**
  ```bash
  # CPU
  GGML_BITNET_FORCE_AXON=CPU ./build_cpu/bin/llama-cli \
      -m models/Falcon3-10B-Instruct-1.58bit/ggml-model-i2_s.gguf \
      -p "Hello" -n 32 -ngl 0

  # CUDA
  GGML_BITNET_FORCE_AXON=CUDA ./build_cuda/bin/llama-cli \
      -m models/Falcon3-10B-Instruct-1.58bit/ggml-model-i2_s.gguf \
      -p "Hello" -n 32 -ngl 35
  ```

- [ ] **9. Benchmark completo**
  ```bash
  python scripts/bitnet_sovereign_bench.py --flavor CUDA
  # Esperar >15 t/s generación, coherencia gramatical
  ```

---

## Archivos Clave (Mapa de Referencia Rápida)

| Archivo | Rol |
|---|---|
| `3rdparty/BitNet-1.58b/setup_env.py` | Script maestro de cuantización |
| `3rdparty/BitNet-1.58b/utils/convert-hf-to-gguf-bitnet.py` | Conversor HF→GGUF con bit-shift PyTorch (L729-736) |
| `3rdparty/BitNet-1.58b/gpu/pack_weight.py` | Permutación WMMA + interleave para CUDA nativo |
| `3rdparty/BitNet-1.58b/gpu/convert_checkpoint.py` | Conversor de checkpoints TorchScale con cuantización INT8→INT2 |
| `3rdparty/BitNet-1.58b/3rdparty/llama.cpp/ggml/src/ggml-common.h` | Definición de `block_i2_s` (DEBE ser 36 bytes) |
| `3rdparty/BitNet-1.58b/3rdparty/llama.cpp/ggml/src/ggml-cuda/dequantize-i2s.cu` | **Nuestro** kernel CUDA de dequantización |
| `3rdparty/BitNet-1.58b/3rdparty/llama.cpp/ggml/src/ggml-cuda/dequantize-i2s.cuh` | **Nuestro** header del kernel |
| `3rdparty/BitNet-1.58b/3rdparty/llama.cpp/ggml/src/ggml-cuda/mmq.cu` | MMQ hooks (I2_S DESREGISTRADO) |
| `3rdparty/BitNet-1.58b/3rdparty/llama.cpp/ggml/src/ggml-cuda/bitnet_porter.cu` | Porter CUDA (restaurado con lógica real) |
| `docs/TECHNICAL/BITNET_REMEDIATION_RUNBOOK.md` | Historial de incidentes y fixes |
| `docs/TECHNICAL/INFERENCE_PLUGINS.md` | Documentación de los 5 backends/flavors |
| `scripts/bitnet_sovereign_bench.py` | Benchmark multi-flavor (server mode) |
| `scripts/test_all_bunker_flavors.py` | Smoke test CLI rápido |

---

*Documento creado por Aleth — v7.1.0 — 2026-05-22*
*Para que nunca más tengamos que redescubrir cómo funciona esto.*
