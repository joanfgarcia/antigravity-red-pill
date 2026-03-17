try:
	import llama_cpp

	print(f"llama-cpp-python version: {llama_cpp.__version__}")
	try:
		print("Attempting to check CUDA availability via Llama init...")
	except Exception as e:
		print(f"Error during check: {e}")
except ImportError:
	print("llama-cpp-python not installed")
