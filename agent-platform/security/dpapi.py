"""Windows DPAPI wrapper -- the real `encrypt`/`decrypt` CredentialBroker is
built to accept.

Per the Fas 1 threat model (§3.1.1): "Use OS-level key storage where
available (Windows DPAPI...) so the master key is bound to the operator's
login session and not a static file next to the encrypted store." DPAPI's
`CryptProtectData` derives its key from the current Windows user's login
credentials -- there is no key file to lose, back up separately, or leak;
only the same OS user account (this operator's login) can ever decrypt.

Implemented via ctypes against crypt32.dll -- stdlib only, no pywin32
dependency, consistent with the "no unjustified new dependency" rule. This
module is Windows-only by design (DPAPI is a Windows API); `CredentialBroker`
itself is platform-agnostic and takes these as injected callables so a
future non-Windows deployment supplies its own OS-keychain equivalent
instead of this module.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import sys

if sys.platform != "win32":  # pragma: no cover - exercised only on Windows
    def protect(data: bytes) -> bytes:
        raise NotImplementedError("DPAPI is only available on Windows")

    def unprotect(data: bytes) -> bytes:
        raise NotImplementedError("DPAPI is only available on Windows")
else:

    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.windll.crypt32
    _kernel32 = ctypes.windll.kernel32

    def _blob_from_bytes(data: bytes) -> _DATA_BLOB:
        buf = ctypes.create_string_buffer(data, len(data))
        return _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    def _bytes_from_blob(blob: "_DATA_BLOB") -> bytes:
        try:
            return ctypes.string_at(blob.pbData, blob.cbData)
        finally:
            _kernel32.LocalFree(blob.pbData)

    def protect(data: bytes) -> bytes:
        """Encrypt `data` bound to the current Windows user's login session."""
        in_blob = _blob_from_bytes(data)
        out_blob = _DATA_BLOB()
        ok = _crypt32.CryptProtectData(
            ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
        )
        if not ok:
            raise OSError(f"CryptProtectData failed: {ctypes.GetLastError()}")
        return _bytes_from_blob(out_blob)

    def unprotect(data: bytes) -> bytes:
        """Decrypt `data` previously produced by protect(). Fails if the
        current login session cannot derive the original key (e.g. a
        different Windows user, or corrupted ciphertext) -- this is the
        fail-closed behavior CredentialBroker relies on."""
        in_blob = _blob_from_bytes(data)
        out_blob = _DATA_BLOB()
        ok = _crypt32.CryptUnprotectData(
            ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
        )
        if not ok:
            raise OSError(f"CryptUnprotectData failed: {ctypes.GetLastError()}")
        return _bytes_from_blob(out_blob)
