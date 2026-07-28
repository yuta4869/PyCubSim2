from __future__ import annotations

import ctypes
import sys
import tkinter as tk
from pathlib import Path


APP_ICON_PATH = (
    Path(__file__).resolve().parents[1] / "assets" / "PyCubSim2-app-icon.png"
)


def configure_application_icon(
    root: tk.Tk,
    icon_path: str | Path = APP_ICON_PATH,
) -> tuple[tk.PhotoImage | None, bool]:
    path = Path(icon_path)
    if not path.is_file():
        return None, False

    photo = tk.PhotoImage(master=root, file=str(path))
    root.iconphoto(True, photo)

    dock_configured = False
    if sys.platform == "darwin":
        try:
            _set_macos_dock_icon(path)
            dock_configured = True
        except Exception:
            # Tk still keeps the window icon if a nonstandard Python build
            # cannot access the Objective-C runtime.
            dock_configured = False
    return photo, dock_configured


def _set_macos_dock_icon(icon_path: Path) -> None:
    objc = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
    _appkit = ctypes.CDLL(
        "/System/Library/Frameworks/AppKit.framework/AppKit"
    )

    objc.objc_getClass.argtypes = (ctypes.c_char_p,)
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = (ctypes.c_char_p,)
    objc.sel_registerName.restype = ctypes.c_void_p

    message_address = ctypes.cast(
        objc.objc_msgSend, ctypes.c_void_p
    ).value
    if message_address is None:
        raise RuntimeError("Could not resolve objc_msgSend.")

    pointer = ctypes.c_void_p
    send_no_args = ctypes.CFUNCTYPE(pointer, pointer, pointer)(
        message_address
    )
    send_pointer = ctypes.CFUNCTYPE(
        pointer, pointer, pointer, pointer
    )(message_address)
    send_string = ctypes.CFUNCTYPE(
        pointer, pointer, pointer, ctypes.c_char_p
    )(message_address)
    send_void_pointer = ctypes.CFUNCTYPE(
        None, pointer, pointer, pointer
    )(message_address)

    def objc_class(name: bytes) -> int:
        value = objc.objc_getClass(name)
        if not value:
            raise RuntimeError(f"Objective-C class not found: {name!r}")
        return value

    def selector(name: bytes) -> int:
        value = objc.sel_registerName(name)
        if not value:
            raise RuntimeError(f"Objective-C selector not found: {name!r}")
        return value

    application = send_no_args(
        objc_class(b"NSApplication"),
        selector(b"sharedApplication"),
    )
    path_string = send_string(
        objc_class(b"NSString"),
        selector(b"stringWithUTF8String:"),
        str(icon_path).encode("utf-8"),
    )
    image = send_pointer(
        send_no_args(objc_class(b"NSImage"), selector(b"alloc")),
        selector(b"initWithContentsOfFile:"),
        path_string,
    )
    if not application or not image:
        raise RuntimeError("Could not create the macOS application icon.")
    send_void_pointer(
        application,
        selector(b"setApplicationIconImage:"),
        image,
    )
