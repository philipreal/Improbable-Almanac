"""Curated 'how rare is this' facts, keyed by event type (seed/rarity_facts.yaml)."""
import yaml

from .. import SEED_DIR


def load_facts() -> dict:
    path = SEED_DIR / "rarity_facts.yaml"
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {k: v for k, v in data.items() if isinstance(v, dict)}
