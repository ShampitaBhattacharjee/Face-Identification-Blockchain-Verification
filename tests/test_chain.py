import pytest

from faceid.chain import (
    MAX_CALLDATA_BYTES,
    ChainError,
    build_calldata_payload,
    decode_calldata_payload,
)
from faceid.hashing import sha256_bytes


def test_calldata_roundtrip():
    img = sha256_bytes(b"img")
    emb = sha256_bytes(b"emb")
    data = build_calldata_payload(img, emb, "https://x.com/a/status/1", "google_lens", {"encoder": "dlib"})
    payload = decode_calldata_payload(data)
    assert payload["imageHash"] == img
    assert payload["embeddingHash"] == emb
    assert payload["postUrl"] == "https://x.com/a/status/1"
    assert payload["encoder"] == "dlib"
    # hex-string form (as returned by eth_getTransactionByHash) decodes too
    assert decode_calldata_payload("0x" + data.hex()) == payload


def test_calldata_rejects_empty_url():
    with pytest.raises(ChainError):
        build_calldata_payload("a" * 64, "b" * 64, "", "p")


def test_calldata_rejects_oversized_payload():
    with pytest.raises(ChainError):
        build_calldata_payload("a" * 64, "b" * 64, "https://x.com/" + "x" * MAX_CALLDATA_BYTES, "p")


def test_decode_rejects_foreign_data():
    with pytest.raises(ChainError):
        decode_calldata_payload(b"not json")
    with pytest.raises(ChainError):
        decode_calldata_payload(b'{"app":"other"}')
