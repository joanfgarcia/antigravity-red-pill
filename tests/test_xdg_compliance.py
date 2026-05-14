import os
from pathlib import Path

def test_no_legacy_storage_paths():
    """
    Smith Filter: Ensures that no Python file in src/ directly references
    the legacy 'storage' directory. XDG paths (from paths.py) must be used.
    """
    src_dir = Path(__file__).parent.parent / "src"
    
    banned_substrings = [
        '"storage"',
        "'storage'",
        '"storage/',
        "'storage/",
        'os.path.join(APP_ROOT, "storage")',
        'os.path.join(PROJECT_ROOT, "storage")'
    ]
    
    violations = []
    
    for py_file in src_dir.rglob("*.py"):
        try:
            with open(py_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            for i, line in enumerate(lines):
                if any(banned in line for banned in banned_substrings):
                    # Ignorar comentarios si es necesario
                    if not line.strip().startswith("#"):
                        violations.append(f"{py_file.relative_to(src_dir.parent)}:{i+1} -> {line.strip()}")
        except Exception as e:
            pass
            
    assert not violations, f"XDG Compliance violation (legacy 'storage' used):\n" + "\n".join(violations)

if __name__ == "__main__":
    test_no_legacy_storage_paths()
    print("XDG Compliance Test Passed.")
