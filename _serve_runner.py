"""Load .env.local then start the local service (mirrors start.ps1)."""
import os, sys
from pathlib import Path
env_file = Path(__file__).parent / ".env.local"
if env_file.is_file():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())
from opensourceguard.cli import main
sys.exit(main(["serve", "--repo", ".", "--port", "8788"]))
