from __future__ import annotations

import sys

import pytest

from security import dpapi

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")


def test_protect_then_unprotect_roundtrips():
    plaintext = b"sk-real-secret-value"
    ciphertext = dpapi.protect(plaintext)
    assert ciphertext != plaintext
    assert dpapi.unprotect(ciphertext) == plaintext


def test_ciphertext_does_not_contain_plaintext():
    plaintext = b"a-very-recognizable-secret-string"
    ciphertext = dpapi.protect(plaintext)
    assert plaintext not in ciphertext


def test_unprotect_rejects_corrupted_ciphertext():
    ciphertext = bytearray(dpapi.protect(b"sk-real-secret"))
    ciphertext[-1] ^= 0xFF
    with pytest.raises(OSError):
        dpapi.unprotect(bytes(ciphertext))
