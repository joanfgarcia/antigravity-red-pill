#!/bin/bash
# Red Pill Protocol: Radeon Activation Sequence (v5.0)
# This script prepares the environment for ROCm/HIP acceleration on Strix Point architectures.

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}--- Starting Radeon Activation Sequence ---${NC}"

# 1. Verification of sysfs access
if [ -f "/sys/class/drm/card2/device/gpu_busy_percent" ]; then
    echo -e "${GREEN}✓ Hardware detected and accessible via sysfs.${NC}"
else
    echo -e "${RED}✗ Hardware path not found. Ensure amdgpu drivers are active.${NC}"
fi

# 2. Dependency Check (Missing ROCm User-space Libraries)
echo -e "${BLUE}Checking for required ROCm libraries...${NC}"
MISSING_LIBS=()
LIBS=("libamdhip64-6" "libhipblas2" "libmiopen-hip1" "libhipfft0" "librocm-smi64-7")

for lib in "${LIBS[@]}"; do
    if ! dpkg -l | grep -q "$lib"; then
        MISSING_LIBS+=("$lib")
    fi
done

if [ ${#MISSING_LIBS[@]} -eq 0 ]; then
    echo -e "${GREEN}✓ All ROCm libraries detected.${NC}"
else
    echo -e "${RED}⚠ Missing libraries detected: ${MISSING_LIBS[*]}${NC}"
    echo -e "Please run the following command to complete the activation:"
    echo -e "${BLUE}sudo apt-get update && sudo apt-get install ${MISSING_LIBS[*]}${NC}"
fi

# 3. Environment Configuration
ENV_FILE=".env"
if [ ! -f "$ENV_FILE" ]; then touch "$ENV_FILE"; fi

if ! grep -q "HSA_OVERRIDE_GFX_VERSION" "$ENV_FILE"; then
    echo "HSA_OVERRIDE_GFX_VERSION=11.5.0" >> "$ENV_FILE"
    echo -e "${GREEN}✓ Strix Point GFX Override (11.5.0) added to .env${NC}"
fi

# 4. ONNX Runtime ROCm check
if ! uv pip list | grep -q "onnxruntime-rocm"; then
    echo -e "${BLUE}Installing onnxruntime-rocm for iGPU embedding offloading...${NC}"
    uv pip uninstall onnxruntime 2>/dev/null || true
    uv pip install onnxruntime-rocm
fi

echo -e "${GREEN}--- Activation Sequence Complete ---${NC}"
echo -e "1. Run the 'sudo apt' command above if libraries were missing."
echo -e "2. Restart your terminal or source the .env file."
echo -e "3. Run 'uv run red-pill status' to verify telemetry."
echo -e "4. Run 'uv run red-pill daemon' to start the ROCm-accelerated sidecar."
