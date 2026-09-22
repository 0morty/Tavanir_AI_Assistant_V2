from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

_DEFAULT_CACHE_DIR = Path(".cache") / "references"

# SHA-256 hex digest (what ReferenceDetails.hash() produces).
_SAFE_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ReferenceCache:
    """File-backed storage of validated reference templates (§17).

    Templates are keyed by the property-**shape** hash produced by
    :meth:`ReferenceDetails.hash`; a cached template therefore serves any
    Reference with the same property shape, and the actual values are
    substituted per instance by the caller (see
    :mod:`src.application.reference.template_filler`).

    Entries live at ``<cache_dir>/<hash>.txt``. Writes go through a temp file
    and ``os.replace`` so a crash never leaves a partial entry behind, and the
    directory is created on demand.
    """

    def __init__(self, cache_dir: str | Path = _DEFAULT_CACHE_DIR) -> None:
        self._cache_dir = Path(cache_dir)

    def load(self, shape_hash: str) -> str | None:
        """Return the cached template for ``shape_hash``, or ``None`` on miss."""
        try:
            return self._path_for(shape_hash).read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    def save(self, shape_hash: str, template: str) -> None:
        """Persist ``template`` for ``shape_hash`` atomically."""
        path = self._path_for(shape_hash)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=path.parent, prefix=f"{shape_hash}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(template)
            os.replace(tmp_path, path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
            raise

    def _path_for(self, shape_hash: str) -> Path:
        if _SAFE_HASH_PATTERN.fullmatch(shape_hash) is None:
            raise ValueError(
                f"Invalid reference shape hash {shape_hash!r}: expected a "
                "64-character SHA-256 hex digest."
            )
        return self._cache_dir / f"{shape_hash}.txt"