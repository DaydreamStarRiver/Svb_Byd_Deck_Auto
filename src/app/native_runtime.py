"""Select the system C++ runtime before Qt loads its bundled older copy.

PyQt5 wheels can ship MSVCP140 14.26.  If Qt imports first, later MaaFramework
native loading can fail with WinError 1114.  Preloading from GetSystemDirectoryW
keeps both libraries on the installed system runtime without changing PATH,
replacing package files, or eagerly loading OCR models.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
from typing import Any


logger = logging.getLogger(__name__)
_CPP_DLLS = ("msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll")
_RUNTIME_HANDLES: dict[str, Any] = {}
_RUNTIME_LOCK = threading.Lock()


def _kernel32() -> Any:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetSystemDirectoryW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint]
    kernel.GetSystemDirectoryW.restype = ctypes.c_uint
    kernel.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
    kernel.GetModuleHandleW.restype = ctypes.c_void_p
    kernel.GetModuleFileNameW.argtypes = [
        ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint
    ]
    kernel.GetModuleFileNameW.restype = ctypes.c_uint
    return kernel


def loaded_cpp_runtime_paths() -> dict[str, str]:
    """Return loaded C++ DLL paths for diagnostics, without loading those DLLs."""

    if sys.platform != "win32":
        return {}
    kernel = _kernel32()
    paths: dict[str, str] = {}
    for name in (*_CPP_DLLS, "vcruntime140.dll", "vcruntime140_1.dll"):
        handle = kernel.GetModuleHandleW(name)
        if not handle:
            continue
        buffer = ctypes.create_unicode_buffer(32768)
        if kernel.GetModuleFileNameW(handle, buffer, len(buffer)):
            paths[name] = buffer.value
    return paths


def prepare_windows_cpp_runtime() -> None:
    """Call before importing PyQt5; safe to repeat and a no-op on other OSes.

    An already-loaded runtime is never unloaded/replaced in a live process.
    Missing system runtimes are logged, allowing the legacy UI to still start.
    """

    if sys.platform != "win32":
        return
    with _RUNTIME_LOCK:
        kernel = _kernel32()
        buffer = ctypes.create_unicode_buffer(32768)
        length = kernel.GetSystemDirectoryW(buffer, len(buffer))
        if not length or length >= len(buffer):
            logger.warning("无法定位系统 C++ 运行库目录: winerror=%s", ctypes.get_last_error())
            return
        for name in _CPP_DLLS:
            if name in _RUNTIME_HANDLES or kernel.GetModuleHandleW(name):
                continue
            path = os.path.join(buffer.value, name)
            try:
                # Absolute system path: never search Qt's bin directory or CWD.
                # Retain handles for the lifetime of the process.
                _RUNTIME_HANDLES[name] = ctypes.WinDLL(path)
            except OSError as exc:
                logger.warning("系统 C++ 运行库预加载失败: %s: %s", path, exc)
