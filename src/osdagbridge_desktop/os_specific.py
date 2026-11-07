# Everything in OsdagBridge-Desktop that differs between Windows, macOS and Linux, in one place: debugging a platform starts here.
# Kept free of Qt: the main module imports it first, in every process the app starts.
import os
import sys


def register_conda_dll_directories():
    """Add the active conda environment's native DLL folders to the Windows DLL
    search path before numpy/scipy/openseespy are imported.

    A conda-constructor-installed app launched from its shortcut does not
    "activate" the environment, so ``<prefix>/Library/bin`` (MKL/OpenBLAS, Qt,
    etc.) is not on the DLL search path. Native extensions then crash the whole
    process with ``ERROR_MOD_NOT_FOUND`` (``0xc06d007f``) the first time they
    delay-load a backend DLL — e.g. ``numpy.linalg.lstsq`` during grillage
    meshing, which silently closes the window and hangs the loader. No-op on
    non-Windows and in already-activated environments.
    """
    if os.name != "nt":
        return
    prefix = sys.prefix
    candidates = [
        os.path.join(prefix, "Library", "bin"),
        os.path.join(prefix, "Library", "mingw-w64", "bin"),
        os.path.join(prefix, "Library", "usr", "bin"),
        os.path.join(prefix, "DLLs"),
        prefix,
    ]
    path_entries = os.environ.get("PATH", "").split(os.pathsep)
    for path in candidates:
        if not os.path.isdir(path):
            continue
        try:
            os.add_dll_directory(path)
        except (OSError, AttributeError):
            pass
        if path not in path_entries:
            os.environ["PATH"] = path + os.pathsep + os.environ.get("PATH", "")
            path_entries.insert(0, path)



def ensure_std_streams():
    """Guarantee sys.stdout/sys.stderr are writable.

    When launched as a gui-script, Windows runs this under pythonw.exe, which
    has no console: sys.stdout/sys.stderr are None. The desktop app prints a lot
    of debug output, and the first print() against None raises AttributeError
    and kills the app silently. Redirect the missing stream(s) to a log file
    (falling back to os.devnull) so the GUI can launch without a console window.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        import tempfile
        log_path = os.path.join(tempfile.gettempdir(), "osdagbridge.log")
        stream = open(log_path, "a", buffering=1, encoding="utf-8")
    except Exception:
        stream = open(os.devnull, "w")
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream



def set_windows_app_id():
    """Give the app its own Windows taskbar identity so the taskbar shows the
    OsdagBridge icon instead of the generic Python/pythonw icon. Must run before
    the main window is shown. No-op on non-Windows."""
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "Osdag.OsdagBridge.Desktop.1"
        )
    except Exception:
        pass


# Open a file with the system's default application.
def open_with_default_app(path):
    import subprocess
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.run(["open", path], check=False)
    else:
        subprocess.run(["xdg-open", path], check=False)


# Linux: Qt often fails to use the system cursor theme, so the app draws its own cursors.
def qt_misses_system_cursors():
    return sys.platform.startswith("linux")


# Linux has trouble with GUI windows in a child process, so the loading popup stays in this process there.
def popup_in_child_process():
    return not sys.platform.startswith("linux")
