# BitNet & llama.cpp — mapa de fuentes y receta de recreación

> Para un agente o un operador que tenga que **recrear** los distintos motores de
> inferencia (llama.cpp oficial, el fork BitNet y sus sabores CPU/CUDA/Vulkan) en
> esta máquina u otra. El *porqué* del formato ternario y los kernels está en
> [BITNET_WEIGHT_PIPELINE.md](./BITNET_WEIGHT_PIPELINE.md); aquí está **qué se
> construye, desde qué commit y cómo se verifica**.

## 1. Regla base: la fuente viaja, los binarios no

| Capa | Dónde vive | Por qué |
|---|---|---|
| **Pin** (commit) | git, en `.gitmodules` | Reproducible: dos máquinas compilan la misma fuente |
| **Build** (`build*/`) | **solo la máquina** | Depende de arquitectura CUDA, driver, toolkit y SO. Ignorado en el fork |
| **Pesos** (`.gguf`) | **solo la máquina** | Se cuantizan en local con `setup_env.py`; nunca GGUF de terceros |

Un pin **debe cumplir dos cosas**: (a) existir en la rama declarada por el
`.gitmodules`, y (b) **compilar**. El fallo histórico fue (b): el commit incluía
`bitnet_porter.cu` sin los dos headers que incluye.

## 2. Mapa de fuentes (lo que hay que recrear)

| Pieza | Repo / rama | Para qué sirve | Produce |
|---|---|---|---|
| `3rdparty/llama_official` | `ggerganov/llama.cpp` (upstream) | Modelos GGUF **generales** (Q4_K_M, Q8_0, …): chat, bake-offs, `llama_cli_runner` | `build/bin/llama-cli`, `build/bin/llama-server` |
| `3rdparty/BitNet-1.58b` | `joanfgarcia/BitNet-1.58b` `main` | Modelos **ternarios I2_S** (Falcon3-1.58bit, BitNet b1.58) + `setup_env.py` para cuantizar | `build_{cpu,cuda,vulkan}/bin/llama-*` |
| ↳ `3rdparty/llama.cpp` (anidado) | `joanfgarcia/llama.cpp` rama `sovereign-i2s` | Los kernels I2_S (`dequantize-i2s.cu`, `bitnet_porter.cu/.cuh`, `ggml/gpu/bitnet_kernels/`) | (se compila dentro de BitNet) |
| `3rdparty/bitnet_cuda_fork` | `joanfgarcia/bitnet_cuda` `main` | **Legado**: no lo referencia ningún módulo del kernel | — |

Regla práctica: **I2_S → BitNet-1.58b. Todo lo demás → llama_official.** Un `.gguf`
I2_S cargado en `llama_official` revienta con bounds check (ver Trampas del pipeline).

## 3. Verificar que el árbol está completo (antes de nada)

```bash
bash scripts/bitnet_build.sh --check     # BitNet + su llama.cpp anidado
git submodule status                    # '-' delante = no inicializado
```

`--check` imprime la cadena de pins:

```
sharing → BitNet → llama.cpp
```

Si falla, el propio script dice qué comando lanzar. Nunca compiles "a ver si
sale": el árbol incompleto falla a mitad y deja un build a medias indistinguible
de uno bueno.

## 4. Receta A — reconstruir todo desde cero en una máquina

```bash
# 1. Fuente en los pins exactos (incluye el llama.cpp anidado de BitNet)
git clone --recurse-submodules <repo> && cd sharing
git submodule update --init --recursive

# 2. Motores
bash scripts/bitnet_build.sh cuda        # o: cpu | vulkan   (BitNet, un sabor)
bash scripts/llama_official_build.sh     # llama.cpp general (CUDA por defecto)

# 3. Verificar
bash scripts/bitnet_build.sh --check
ls 3rdparty/BitNet-1.58b/build_cuda/bin/llama-server \
   3rdparty/llama_official/build/bin/llama-cli
```

**Criterio de hecho**: los dos binarios existen y `--check` sale en verde. El
runtime ya los resuelve solo (`core/paths.py:resolve_llama_binary`, `providers.py`).

Solo se compila el sabor que la máquina soporta. `npu` no existe en este fork y
el script lo rechaza en vez de producir un build de CPU con nombre de NPU.

## 5. Receta B — recrear un sabor concreto

| Sabor | Comando | Flag cmake | Binario |
|---|---|---|---|
| CPU | `bash scripts/bitnet_build.sh cpu` | (ninguno) | `build_cpu/bin/llama-server` |
| CUDA | `bash scripts/bitnet_build.sh cuda` | `-DGGML_CUDA=ON` | `build_cuda/bin/llama-server` |
| Vulkan | `bash scripts/bitnet_build.sh vulkan` | `-DGGML_VULKAN=ON` | `build_vulkan/bin/llama-server` |
| ROCm | `bash scripts/bitnet_build.sh rocm` | `-DGGML_HIPBLAS=ON` | `build_rocm/…` (**experimental**, no medido) |

Para forzar un backend en runtime: `GGML_BITNET_FORCE_AXON=CPU|CUDA|VULKAN`.
Medición: `python scripts/bitnet_sovereign_bench.py --flavor CUDA` (acepta
`CPU`, `CUDA`, `VULKAN`, `ROCm`).

## 6. Receta C — recrear tras mover el upstream

Cuando `microsoft/BitNet` o `ggerganov/llama.cpp` avanzan y hay que rehacer el
fork sin perder los parches propios:

```bash
# 1. ¿Qué commits son nuestros? (los que el fork añade al upstream)
cd 3rdparty/BitNet-1.58b
git fetch origin                       # microsoft/BitNet
git log --oneline origin/main..main    # los nuestros

# 2. Traer el upstream CONSERVANDO los nuestros (merge, nunca rebase de main)
git switch main
git merge origin/main
# conflictos: se resuelven aquí. Los ficheros del kernel I2_S son los que suelen caer.

# 3. Lo mismo en el llama.cpp anidado
cd 3rdparty/llama.cpp
git fetch origin                       # Eddie-Wang1120/llama.cpp (upstream del fork)
git switch sovereign-i2s
git merge origin/master

# 4. Compilar y medir  (el árbol debe compilar ANTES de mover el pin)
cd ../../.. && bash scripts/bitnet_build.sh --check
bash scripts/bitnet_build.sh cuda
python scripts/bitnet_sovereign_bench.py --flavor CUDA

# 5. Publicar y repinear (en este orden: si no, el pin apunta a un commit
#    que solo existe en tu disco)
git -C 3rdparty/BitNet-1.58b/3rdparty/llama.cpp push fork sovereign-i2s
git -C 3rdparty/BitNet-1.58b add 3rdparty/llama.cpp && \
git -C 3rdparty/BitNet-1.58b commit -m "chore: pin de llama.cpp a <commit>" && \
git -C 3rdparty/BitNet-1.58b push fork main
git add 3rdparty/BitNet-1.58b && git commit -m "chore(bitnet): pin a <commit>"
```

Si prefieres una **serie limpia de parches** en vez de un merge (histórico más
fácil de auditar), en el paso 2 usa `git switch -c update-<fecha> origin/main` +
`git cherry-pick <nuestros commits>`, y al final lleva esa rama a `main` con un
merge normal antes de publicar. Lo que **no** se hace es reescribir `main`.

**Comprobación de que el pin es reproducible** (hazla siempre después del paso 5):

```bash
# ¿el commit del pin está en la rama remota declarada?
git -C 3rdparty/BitNet-1.58b rev-parse HEAD
git ls-remote https://github.com/joanfgarcia/BitNet-1.58b.git refs/heads/main
```

Si los dos hashes no coinciden, el pin **no** es reproducible: otra máquina no
podrá hacer `submodule update`. Es exactamente el fallo que se corrigió el
2026-11-03 (el `.gitmodules` del fork apuntaba a un upstream donde el pin no
existía).

## 7. Qué NO hacer

- **No versionar `build_*/`** (el fork llegó a tener 3.210 ficheros, el 98 % del repo).
  Rebuild = árbol sucio permanentemente.
- **No mover un pin a un commit sin publicar** ni cambiar el `.gitmodules` a un
  upstream que no contiene el pin.
- **No usar GGUF de terceros** para modelos ternarios: se cuantizan en local.
- **No inventar sabores**: si un backend no existe en el fork, se dice.
- **No tocar `3rdparty/` a mano**: se cambia el pin, se compila y se verifica.

## 8. Archivos clave

| Ruta | Qué es |
|---|---|
| `scripts/bitnet_build.sh` | Compila un sabor de BitNet tras verificar el árbol (`--check`, `--list`) |
| `scripts/llama_official_build.sh` | Compila el llama.cpp general (`build/`) |
| `scripts/bitnet_sovereign_bench.py` | Medición por sabor (`--flavor CPU/CUDA/VULKAN/ROCm`) |
| `3rdparty/BitNet-1.58b/setup_env.py` | Cuantización local (HF → GGUF I2_S) |
| `.gitmodules` | La cadena de pins (lo único que hay que mantener al día) |
