
import os
import red_pill.config as cfg

def update_env(updates: dict):
    """Updates the .env file with new key-value pairs."""
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if not os.path.exists(env_path):
        # Create it if it doesn't exist
        with open(env_path, "w") as f:
            for k, v in updates.items():
                f.write(f"{k}={v}\n")
        return

    # Read existing
    with open(env_path, "r") as f:
        lines = f.readlines()

    new_lines = []
    keys_updated = set()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        
        if "=" in stripped:
            key = stripped.split("=")[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}\n")
                keys_updated.add(key)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    # Append new keys
    for key, value in updates.items():
        if key not in keys_updated:
            new_lines.append(f"{key}={value}\n")

    with open(env_path, "w") as f:
        f.writelines(new_lines)

if __name__ == "__main__":
    # Example usage
    import sys
    if len(sys.argv) > 1:
        # Simple CLI for the script: update_env.py KEY=VALUE
        pairs = {}
        for arg in sys.argv[1:]:
            if "=" in arg:
                k, v = arg.split("=", 1)
                pairs[k] = v
        if pairs:
            update_env(pairs)
