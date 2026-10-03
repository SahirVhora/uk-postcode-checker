"""Area Pack pipeline: builds a local area-intelligence database from official open data."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "pipeline" / "cache"
DB_PATH = REPO_ROOT / "data" / "local" / "area.db"
PACK_DIR = REPO_ROOT / "data" / "area-pack"
SEED_DIR = REPO_ROOT / "data" / "seed"
CONFIG_DIR = REPO_ROOT / "config"


class SourceFormatChanged(RuntimeError):
    """Raised when an official source no longer looks the way the parser expects."""


class ManualInputNeeded(RuntimeError):
    """Raised when a source cannot run without something only the user can provide."""
