# RUNBOOK: BitNet CUDA Remediation (RTX 5070)

## Contexto Técnico
El sistema BitNet 1.58b utiliza una representación ternaria de pesos. En la RTX 5070, la inferencia estaba produciendo ruido incoherente debido a que los kernels de dequantización específicos para la arquitectura de GPU estaban en estado de placeholder (vaciados durante una limpieza anterior o mala sincronización de rama).

## El Fallo: "The Silent Placeholder"
En `3rdparty/BitNet-1.58b/3rdparty/llama.cpp/ggml/src/ggml-cuda.cu`:
- El kernel `k_bitnet_porter` solo realizaba una copia de bytes: `dst[i] = src[i]`.
- Al no dequantizar los valores ternarios empaquetados, la multiplicación de matrices (GEMM) recibía basura lógica, resultando en el output `ivi...`.

## Remediación Aplicada
1. **Restauración del Porter**: Se implementa la lógica de dequantización real en `bitnet_cuda_porter_axon` para mapear los pares de bits `00, 01, 10` a los valores flotantes `-1.0, 0.0, 1.0` multiplicados por el `block_scale`.
2. **Forzado de Backend**: Se ajusta `providers.py` y el entorno de build para que `GGML_BITNET_FORCE_AXON=CUDA` sea la ruta por defecto en hardware NVIDIA.
3. **Sincronización de Tipos**: Se asegura que `block_i2_s` mantenga el tamaño de 36 bytes (32 bytes de pesos + 4 bytes de escala float) para alinearse con el formato de disco de los modelos Falcon 3 V2.

## Cómo verificar la estabilidad
Ejecutar el benchmark soberano:
```bash
python scripts/bitnet_sovereign_bench.py --flavor CUDA
```
El reporte debe mostrar > 15 t/s y coherencia gramatical en la RTX 5070.
