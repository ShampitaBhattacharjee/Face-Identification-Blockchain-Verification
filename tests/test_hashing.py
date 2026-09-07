import numpy as np
import pytest

from faceid.hashing import embedding_hash, normalise_hex, sha256_bytes, to_bytes32


def test_embedding_hash_is_stable_under_float_noise():
    base = np.linspace(-0.5, 0.5, 128)
    noisy = base + 1e-9
    assert embedding_hash(base) == embedding_hash(noisy)


def test_embedding_hash_changes_for_different_face():
    a = np.linspace(-0.5, 0.5, 128)
    b = a.copy()
    b[3] += 0.01
    assert embedding_hash(a) != embedding_hash(b)


def test_to_bytes32_accepts_prefixed_and_unprefixed():
    digest = sha256_bytes(b"hello")
    assert to_bytes32(digest) == to_bytes32("0x" + digest)
    assert len(to_bytes32(digest)) == 32


def test_to_bytes32_rejects_wrong_length():
    with pytest.raises(ValueError):
        to_bytes32("abcd")


def test_normalise_hex():
    assert normalise_hex("0xABC") == "abc"
    assert normalise_hex(" abc ") == "abc"
