import os

from huggingface_hub import hf_hub_download

# Optimize download speed
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"

def download_model():
    repo_id = "TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF"
    filename = "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"

    models_dir = os.path.join(os.path.dirname(__file__), "..", "models")
    os.makedirs(models_dir, exist_ok=True)

    local_path = os.path.join(models_dir, filename)
    if os.path.exists(local_path):
        print(f"[{filename}] already exists at {local_path}. Skipping download.")
        return local_path

    print(f"Downloading Edge SLM [{filename}] (~680MB) please wait...")

    model_path = hf_hub_download(
        repo_id=repo_id,
        filename=filename,
        local_dir=models_dir,
        local_dir_use_symlinks=False
    )
    print(f"Download complete! Saved to {model_path}")
    return model_path

if __name__ == "__main__":
    download_model()
