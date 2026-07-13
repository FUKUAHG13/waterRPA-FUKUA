"""User-scoped DPAPI credential storage; workflow files keep names only."""

from __future__ import annotations

import base64
import ctypes
import json
import os
import threading
from ctypes import wintypes

from .config_store import atomic_write_json


CREDENTIAL_FILE_NAME = "credentials.dat"
CREDENTIAL_FORMAT = "fukuaRPA_dpapi_credentials"
MAX_CREDENTIALS = 256
MAX_CREDENTIAL_NAME_LENGTH = 100
MAX_SECRET_BYTES = 1024 * 1024
CRYPTPROTECT_UI_FORBIDDEN = 0x1


class CredentialStoreError(RuntimeError):
    pass


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


crypt32 = ctypes.windll.crypt32
kernel32 = ctypes.windll.kernel32
crypt32.CryptProtectData.argtypes = [
    ctypes.POINTER(DATA_BLOB),
    wintypes.LPCWSTR,
    ctypes.POINTER(DATA_BLOB),
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(DATA_BLOB),
]
crypt32.CryptProtectData.restype = wintypes.BOOL
crypt32.CryptUnprotectData.argtypes = [
    ctypes.POINTER(DATA_BLOB),
    ctypes.POINTER(wintypes.LPWSTR),
    ctypes.POINTER(DATA_BLOB),
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(DATA_BLOB),
]
crypt32.CryptUnprotectData.restype = wintypes.BOOL
kernel32.LocalFree.argtypes = [ctypes.c_void_p]
kernel32.LocalFree.restype = ctypes.c_void_p


def _input_blob(data: bytes) -> tuple[DATA_BLOB, object]:
    buffer = ctypes.create_string_buffer(data)
    return DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def _dpapi_transform(data: bytes, protect: bool) -> bytes:
    source, source_buffer = _input_blob(data)
    result = DATA_BLOB()
    if protect:
        success = crypt32.CryptProtectData(
            ctypes.byref(source),
            "fukuaRPA credential",
            None,
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(result),
        )
    else:
        description = wintypes.LPWSTR()
        success = crypt32.CryptUnprotectData(
            ctypes.byref(source),
            ctypes.byref(description),
            None,
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(result),
        )
        if description:
            kernel32.LocalFree(description)
    if not success:
        raise CredentialStoreError(f"Windows DPAPI 操作失败（错误码 {ctypes.get_last_error()}）")
    _ = source_buffer  # Keep the input allocation alive through the DPAPI call.
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        if result.pbData:
            kernel32.LocalFree(result.pbData)


def protect_secret(secret: str) -> str:
    raw = str(secret).encode("utf-8")
    if len(raw) > MAX_SECRET_BYTES:
        raise CredentialStoreError("秘密内容过长")
    return base64.b64encode(_dpapi_transform(raw, True)).decode("ascii")


def unprotect_secret(encoded: str) -> str:
    try:
        protected = base64.b64decode(str(encoded), validate=True)
        return _dpapi_transform(protected, False).decode("utf-8")
    except CredentialStoreError:
        raise
    except Exception as error:
        raise CredentialStoreError("凭据内容损坏或不属于当前 Windows 用户") from error


def validate_credential_name(name: str) -> str:
    normalized = str(name or "").strip()
    if not normalized or len(normalized) > MAX_CREDENTIAL_NAME_LENGTH:
        raise CredentialStoreError(
            f"凭据名称长度必须为 1 到 {MAX_CREDENTIAL_NAME_LENGTH} 个字符"
        )
    if any(ord(char) < 32 for char in normalized):
        raise CredentialStoreError("凭据名称不能包含控制字符")
    return normalized


class CredentialStore:
    def __init__(self, base_dir: str, protect=protect_secret, unprotect=unprotect_secret):
        self.path = os.path.join(os.path.abspath(base_dir), CREDENTIAL_FILE_NAME)
        self._protect = protect
        self._unprotect = unprotect
        self._lock = threading.RLock()

    def _load_encrypted(self) -> dict[str, str]:
        if not os.path.isfile(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception as error:
            raise CredentialStoreError("凭据库无法读取，文件可能已损坏") from error
        if payload.get("format") != CREDENTIAL_FORMAT or not isinstance(
            payload.get("credentials"), dict
        ):
            raise CredentialStoreError("凭据库格式无效")
        return {
            validate_credential_name(name): str(value)
            for name, value in payload["credentials"].items()
        }

    def _save_encrypted(self, values: dict[str, str]) -> None:
        atomic_write_json(
            self.path,
            {"format": CREDENTIAL_FORMAT, "version": 1, "credentials": values},
        )

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._load_encrypted(), key=str.casefold)

    def get(self, name: str) -> str:
        normalized = validate_credential_name(name)
        with self._lock:
            values = self._load_encrypted()
            if normalized not in values:
                raise CredentialStoreError(f"凭据“{normalized}”不存在")
            return self._unprotect(values[normalized])

    def set(self, name: str, secret: str) -> None:
        normalized = validate_credential_name(name)
        with self._lock:
            values = self._load_encrypted()
            if normalized not in values and len(values) >= MAX_CREDENTIALS:
                raise CredentialStoreError(f"凭据库最多保存 {MAX_CREDENTIALS} 项")
            values[normalized] = self._protect(str(secret))
            self._save_encrypted(values)

    def delete(self, name: str) -> bool:
        normalized = validate_credential_name(name)
        with self._lock:
            values = self._load_encrypted()
            if normalized not in values:
                return False
            del values[normalized]
            self._save_encrypted(values)
            return True
