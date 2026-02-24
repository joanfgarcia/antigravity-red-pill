try:
    from llama_cpp import Llama
    import llama_cpp
    print(f"llama-cpp-python version: {llama_cpp.__version__}")
    # Try to initialize a tiny dummy model or just check for CUDA
    # In newer versions, we can check for the backend
    try:
        # This is a hacky way to check if CUDA is compiled in
        import ctypes
        import os
        # Try to find if the shared library has cuda symbols would be hard
        # Better: try to init a model with n_gpu_layers=1 and catch the output
        print("Attempting to check CUDA availability via Llama init...")
        # We don't even need a real model file for a simple check if we just check the output
    except Exception as e:
        print(f"Error during check: {e}")
except ImportError:
    print("llama-cpp-python not installed")
