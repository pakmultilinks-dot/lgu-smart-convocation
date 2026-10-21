"""Read-only boundary stamp that also works without a production database."""
from hashlib import sha256
from pathlib import Path


def production_stamp(path=None):
    target = Path(path) if path is not None else Path(__file__).resolve().parents[1] / "lgu.db"
    if not target.exists():
        return None
    stat = target.stat()
    return stat.st_size, stat.st_mtime_ns, sha256(target.read_bytes()).hexdigest()
