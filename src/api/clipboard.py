"""Copie dans le presse-papiers Windows via l'API Win32 (fiable même si la fenêtre web bloque la copie)."""
import ctypes
from ctypes import wintypes

CF_UNICODETEXT, GMEM_MOVEABLE = 13, 0x0002
user32, kernel32 = ctypes.WinDLL("user32"), ctypes.WinDLL("kernel32")
user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = wintypes.LPVOID
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]


def copy(text):
    data = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(data)
    if not user32.OpenClipboard(None):
        raise OSError("Presse-papiers occupé par une autre application")
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        ctypes.memmove(kernel32.GlobalLock(handle), data, size)
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):  # Windows devient propriétaire de la mémoire
            raise OSError("Échec de la copie")
    finally:
        user32.CloseClipboard()
