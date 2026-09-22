from contextlib import contextmanager
from pathlib import Path
from tempfile import mkdtemp

from src.application.reference import ReferenceCache


@contextmanager
def raises(exc_type):
    try:
        yield
    except exc_type:
        return
    raise AssertionError(f"{exc_type.__name__} was not raised")


_HASH_A = "f" * 64
_HASH_B = "e" * 64


def make_cache() -> tuple[ReferenceCache, Path]:
    cache_dir = Path(mkdtemp(prefix="reference-cache-test-"))
    return ReferenceCache(cache_dir), cache_dir


def test_load_missing_hash_returns_none():
    cache, _ = make_cache()
    assert cache.load(_HASH_A) is None


def test_save_then_load_roundtrip():
    cache, _ = make_cache()

    cache.save(_HASH_A, "On page [page], it is stated:")

    assert cache.load(_HASH_A) == "On page [page], it is stated:"


def test_save_creates_file_named_after_hash():
    cache, cache_dir = make_cache()

    cache.save(_HASH_A, "template")

    entry = cache_dir / f"{_HASH_A}.txt"
    assert entry.is_file()
    assert entry.read_text(encoding="utf-8") == "template"


def test_save_creates_parent_directories():
    cache_dir = Path(mkdtemp(prefix="reference-cache-test-"))
    cache = ReferenceCache(cache_dir / "nested" / "deep")

    cache.save(_HASH_A, "template")

    assert (cache_dir / "nested" / "deep" / f"{_HASH_A}.txt").is_file()


def test_overwrite_replaces_existing_entry():
    cache, _ = make_cache()

    cache.save(_HASH_A, "first")
    cache.save(_HASH_A, "second")

    assert cache.load(_HASH_A) == "second"


def test_distinct_hashes_are_independent():
    cache, _ = make_cache()

    cache.save(_HASH_A, "template A")

    assert cache.load(_HASH_A) == "template A"
    assert cache.load(_HASH_B) is None


def test_rejects_non_hex_hash_on_save():
    cache, _ = make_cache()

    with raises(ValueError):
        cache.save("../.git/config", "template")


def test_rejects_non_hex_hash_on_load():
    cache, _ = make_cache()

    with raises(ValueError):
        cache.load("../../secrets/passwords")


def test_rejects_undersized_hash():
    cache, _ = make_cache()

    with raises(ValueError):
        cache.save("short", "template")


def test_default_cache_dir_is_cache_references():
    cache = ReferenceCache()
    assert cache._cache_dir == Path(".cache") / "references"