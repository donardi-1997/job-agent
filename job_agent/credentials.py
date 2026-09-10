from __future__ import annotations

import base64
import ctypes
import os
import sqlite3
from ctypes import wintypes
from pathlib import Path
from typing import Protocol

from job_agent.storage import DEFAULT_DB_PATH


SERVICE_NAME = "computrabajo"


class SecretProtector(Protocol):
	name: str

	def protect(self, value: str) -> str: ...

	def unprotect(self, value: str) -> str: ...


class WindowsDPAPIProtector:
	"""Protect secrets with Windows DPAPI, scoped to the current Windows user."""

	name = "Windows DPAPI"
	_CRYPTPROTECT_UI_FORBIDDEN = 0x1

	class _DATA_BLOB(ctypes.Structure):
		_fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

	@classmethod
	def _to_blob(cls, payload: bytes) -> tuple[_DATA_BLOB, object]:
		buffer = (ctypes.c_ubyte * len(payload)).from_buffer_copy(payload)
		blob = cls._DATA_BLOB(len(payload), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
		return blob, buffer

	@classmethod
	def _windows_apis(cls):
		if os.name != "nt":
			raise RuntimeError("Windows DPAPI is only available on Windows.")
		crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
		kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
		crypt32.CryptProtectData.argtypes = [
			ctypes.POINTER(cls._DATA_BLOB),
			wintypes.LPCWSTR,
			ctypes.POINTER(cls._DATA_BLOB),
			ctypes.c_void_p,
			ctypes.c_void_p,
			wintypes.DWORD,
			ctypes.POINTER(cls._DATA_BLOB),
		]
		crypt32.CryptProtectData.restype = wintypes.BOOL
		crypt32.CryptUnprotectData.argtypes = [
			ctypes.POINTER(cls._DATA_BLOB),
			ctypes.POINTER(wintypes.LPWSTR),
			ctypes.POINTER(cls._DATA_BLOB),
			ctypes.c_void_p,
			ctypes.c_void_p,
			wintypes.DWORD,
			ctypes.POINTER(cls._DATA_BLOB),
		]
		crypt32.CryptUnprotectData.restype = wintypes.BOOL
		kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
		kernel32.LocalFree.restype = wintypes.HLOCAL
		return crypt32, kernel32

	@classmethod
	def _protect_bytes(cls, payload: bytes) -> bytes:
		crypt32, kernel32 = cls._windows_apis()
		input_blob, input_buffer = cls._to_blob(payload)
		output_blob = cls._DATA_BLOB()
		_ = input_buffer
		ok = crypt32.CryptProtectData(
			ctypes.byref(input_blob),
			"Job Agent Computrabajo credentials",
			None,
			None,
			None,
			cls._CRYPTPROTECT_UI_FORBIDDEN,
			ctypes.byref(output_blob),
		)
		if not ok:
			raise OSError(ctypes.get_last_error(), "Windows DPAPI could not protect the credential")
		try:
			return ctypes.string_at(output_blob.pbData, output_blob.cbData)
		finally:
			kernel32.LocalFree(ctypes.cast(output_blob.pbData, wintypes.HLOCAL))

	@classmethod
	def _unprotect_bytes(cls, payload: bytes) -> bytes:
		crypt32, kernel32 = cls._windows_apis()
		input_blob, input_buffer = cls._to_blob(payload)
		output_blob = cls._DATA_BLOB()
		_ = input_buffer
		ok = crypt32.CryptUnprotectData(
			ctypes.byref(input_blob),
			None,
			None,
			None,
			None,
			cls._CRYPTPROTECT_UI_FORBIDDEN,
			ctypes.byref(output_blob),
		)
		if not ok:
			raise OSError(ctypes.get_last_error(), "Windows DPAPI could not decrypt the credential")
		try:
			return ctypes.string_at(output_blob.pbData, output_blob.cbData)
		finally:
			kernel32.LocalFree(ctypes.cast(output_blob.pbData, wintypes.HLOCAL))

	def protect(self, value: str) -> str:
		return base64.b64encode(self._protect_bytes(value.encode("utf-8"))).decode("ascii")

	def unprotect(self, value: str) -> str:
		return self._unprotect_bytes(base64.b64decode(value.encode("ascii"))).decode("utf-8")


class UnsupportedPlatformProtector:
	name = "Unavailable"

	def protect(self, value: str) -> str:
		raise RuntimeError("El guardado seguro de contraseñas está habilitado solo en Windows por ahora.")

	def unprotect(self, value: str) -> str:
		raise RuntimeError("El guardado seguro de contraseñas está habilitado solo en Windows por ahora.")


def default_protector() -> SecretProtector:
	return WindowsDPAPIProtector() if os.name == "nt" else UnsupportedPlatformProtector()


class CredentialStore:
	"""Single-user local credentials; passwords are never returned by dashboard APIs."""

	def __init__(self, path: Path | str = DEFAULT_DB_PATH, protector: SecretProtector | None = None) -> None:
		self.path = Path(path)
		self.path.parent.mkdir(parents=True, exist_ok=True)
		self.protector = protector or default_protector()
		with self._connect() as connection:
			connection.execute(
				"""
				CREATE TABLE IF NOT EXISTS local_credentials (
					service TEXT PRIMARY KEY,
					username TEXT NOT NULL,
					secret_blob TEXT NOT NULL,
					protection TEXT NOT NULL,
					updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
				)
				"""
			)

	def _connect(self) -> sqlite3.Connection:
		connection = sqlite3.connect(self.path)
		connection.row_factory = sqlite3.Row
		return connection

	def save_computrabajo(self, username: str, password: str) -> dict[str, object]:
		clean_username = username.strip()
		if not clean_username:
			raise ValueError("Ingresa tu usuario o correo de Computrabajo.")
		if not password:
			raise ValueError("Ingresa la contraseña de Computrabajo.")
		secret_blob = self.protector.protect(password)
		with self._connect() as connection:
			connection.execute(
				"""
				INSERT INTO local_credentials(service, username, secret_blob, protection, updated_at)
				VALUES(?, ?, ?, ?, CURRENT_TIMESTAMP)
				ON CONFLICT(service) DO UPDATE SET
					username=excluded.username,
					secret_blob=excluded.secret_blob,
					protection=excluded.protection,
					updated_at=CURRENT_TIMESTAMP
				""",
				(SERVICE_NAME, clean_username, secret_blob, self.protector.name),
			)
		return self.computrabajo_status()

	def computrabajo_status(self) -> dict[str, object]:
		with self._connect() as connection:
			row = connection.execute(
				"SELECT username, protection, updated_at FROM local_credentials WHERE service = ?",
				(SERVICE_NAME,),
			).fetchone()
		if not row:
			return {"configured": False, "username": "", "protection": self.protector.name, "updated_at": None}
		return {
			"configured": True,
			"username": str(row["username"]),
			"protection": str(row["protection"]),
			"updated_at": row["updated_at"],
		}

	def load_computrabajo(self) -> tuple[str, str] | None:
		with self._connect() as connection:
			row = connection.execute(
				"SELECT username, secret_blob FROM local_credentials WHERE service = ?",
				(SERVICE_NAME,),
			).fetchone()
		if not row:
			return None
		return str(row["username"]), self.protector.unprotect(str(row["secret_blob"]))

	def clear_computrabajo(self) -> None:
		with self._connect() as connection:
			connection.execute("DELETE FROM local_credentials WHERE service = ?", (SERVICE_NAME,))
