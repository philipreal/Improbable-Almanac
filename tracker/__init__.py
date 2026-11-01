"""The Improbable Almanac: finds rare and strange sports events."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "site" / "data"
CONFIG_DIR = ROOT / "config"
SEED_DIR = ROOT / "seed"
CACHE_DIR = ROOT / ".cache"
