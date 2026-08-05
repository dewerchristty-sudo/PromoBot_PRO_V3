from __future__ import annotations

import ctypes
import os
import threading
from ctypes import wintypes


class HunterProcessLock:
    """Mutex do sistema operacional que limita o Hunter a um processo."""

    DEFAULT_NAME = "Global\\PromoBot_PRO_V3_PromotionHunter"
    WAIT_OBJECT_0 = 0x00000000
    WAIT_ABANDONED = 0x00000080
    WAIT_TIMEOUT = 0x00000102
    _state_lock = threading.Lock()
    _owned_names: set[str] = set()

    def __init__(self, name: str | None = None) -> None:
        if os.name != "nt":
            raise RuntimeError("HunterProcessLock requer Windows")
        self.name = str(name or self.DEFAULT_NAME)
        self._handle = None
        self._owned = False

    @staticmethod
    def _kernel32():
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = (
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        )
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.ReleaseMutex.argtypes = (wintypes.HANDLE,)
        kernel32.ReleaseMutex.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        return kernel32

    @property
    def owned(self) -> bool:
        return self._owned

    def acquire(self) -> bool:
        if self._owned:
            return True
        with self._state_lock:
            if self.name in self._owned_names:
                return False
        kernel32 = self._kernel32()
        handle = kernel32.CreateMutexW(None, False, self.name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        result = kernel32.WaitForSingleObject(handle, 0)
        if result in (self.WAIT_OBJECT_0, self.WAIT_ABANDONED):
            self._handle = handle
            self._owned = True
            with self._state_lock:
                self._owned_names.add(self.name)
            return True
        kernel32.CloseHandle(handle)
        if result == self.WAIT_TIMEOUT:
            return False
        raise ctypes.WinError(ctypes.get_last_error())

    def release(self) -> None:
        if not self._handle:
            return
        kernel32 = self._kernel32()
        handle = self._handle
        owned = self._owned
        self._handle = None
        self._owned = False
        if owned:
            with self._state_lock:
                self._owned_names.discard(self.name)
        try:
            if owned and not kernel32.ReleaseMutex(handle):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            kernel32.CloseHandle(handle)

    @classmethod
    def is_locked(cls, name: str | None = None) -> bool:
        probe = cls(name)
        if probe.acquire():
            probe.release()
            return False
        return True

    def __enter__(self):
        return self.acquire()

    def __exit__(self, exc_type, exc_value, traceback):
        self.release()
        return False
