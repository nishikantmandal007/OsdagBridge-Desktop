import sys
import os

# Print a Python traceback instead of a bare core dump on a native crash (stderr may be None).
import faulthandler
try:
    faulthandler.enable()
except Exception:
    pass

# Windows: the conda environment's DLL folders before any native extension loads, and stdout/stderr under pythonw; each process
# the app starts runs these on importing this module.
from osdagbridge_desktop.os_specific import ensure_std_streams, register_conda_dll_directories, set_windows_app_id

register_conda_dll_directories()
ensure_std_streams()

# Everything below the two calls above runs only from main(): setu's analysis process (and each Windows worker) is started with
# spawn, which imports this module again, and must not load Qt, the 3D viewer or the UI, nor set up the database, for nothing.


def _app_icon():
    """Return the OsdagBridge application icon (the same .ico used for the
    desktop / Start Menu shortcut), or an empty QIcon if it can't be found."""
    from PySide6.QtGui import QIcon
    try:
        from importlib.resources import files
        ico = files('osdagbridge_desktop.resources').joinpath('osdagbridge.ico')
        if ico.is_file():
            return QIcon(str(ico))
    except Exception:
        pass
    return QIcon()


# Create Intg_osdag.sqlite if not Exist
def create_sqlite():
    import sqlite3
    import subprocess
    from importlib.resources import files
    import shutil
    
    needs_update = False
    backup_path = None
    sqlitepath = None
    try:
        # Resolve paths directly from core exports instead of importlib.resources.files()
        # to prevent 'OrphanPath' errors during startup.
        from osdagbridge_core import RESOURCE_DIR, DATABASE_PATH, ensure_all_databases
        if ensure_all_databases:
            ensure_all_databases()

        sqlpath = RESOURCE_DIR / 'Intg_osdag.sql'
        sqlitepath = DATABASE_PATH

        if not sqlpath.exists():
            print(f"[ERROR] SQL file not found: {sqlpath}")
            return

        # Determine if we need to create or update
        needs_creation = not sqlitepath.exists()
        needs_update = (sqlitepath.exists() and 
                    (sqlitepath.stat().st_size == 0 or 
                        sqlitepath.stat().st_mtime < sqlpath.stat().st_mtime - 1))

        if not needs_creation and not needs_update:
            # print("[INFO] Database is up to date")
            return

        # Create backup if updating existing database
        backup_path = None
        if needs_update:
            backup_path = sqlitepath.with_suffix('.sqlite.backup')
            shutil.copy2(sqlitepath, backup_path)

        # Create/update database
        target_path = sqlitepath
        if needs_update:
            # Create in temp location first
            target_path = sqlitepath.parent / 'Intg_osdag_temp.sqlite'

        # Try Python sqlite3 first
        try:
            with open(sqlpath, 'r', encoding='utf-8') as sql_file:
                sql_content = sql_file.read()
            
            conn = sqlite3.connect(target_path)
            conn.executescript(sql_content)
            conn.close()
            
            print(f"[INFO] Intg_osdag sqlite database {'created' if needs_creation else 'updated'} using python sqlite3")
            
        except Exception as e:
            print(f"[ERROR] Python sqlite3 failed: {e}, trying command line")
            
            # Fallback to command line
            result = subprocess.run([
                'sqlite3', str(target_path), 
                f'.read {sqlpath}'
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode != 0:
                raise Exception(f"[ERROR] Command line sqlite3 failed: {result.stderr}")
            
            print(f"[INFO] Intg_osdag sqlite database {'created' if needs_creation else 'updated'} using command line")

        # If updating, replace the original
        if needs_update:
            sqlitepath.unlink()
            target_path.rename(sqlitepath)
            if backup_path and backup_path.exists():
                backup_path.unlink()

        # Touch the SQL file to update timestamp
        sqlpath.touch()

    except Exception as e:
        print(f"[ERROR] Database setup failed: {e}")
        
        # Cleanup on failure
        if needs_update and sqlitepath is not None:
            # Restore backup if available
            if backup_path and backup_path.exists():
                if not sqlitepath.exists():
                    shutil.copy2(backup_path, sqlitepath)
                backup_path.unlink()
            
            # Remove temp file
            temp_path = sqlitepath.parent / 'Intg_osdag_temp.sqlite'
            if temp_path.exists():
                temp_path.unlink()



def ensure_osdag_core_db():
    """Build the osdag_core sqlite database if it is missing or empty.

    The installed `osdag` package ships a 0-byte placeholder
    `Intg_osdag.sqlite` alongside the `Intg_osdag.sql` that defines its
    tables (Beams, Angles, Columns, ...), but nothing populates it. When the
    desktop app queries it via osdag_core.Common, every lookup fails with
    "no such table: Beams/Angles". Build the database from the bundled SQL on
    startup so those section tables are always available.
    """
    import sqlite3
    from importlib.resources import files

    try:
        db_dir = files('osdag_core.data.ResourceFiles.Database')
        sqlpath = db_dir.joinpath('Intg_osdag.sql')
        sqlitepath = db_dir.joinpath('Intg_osdag.sqlite')

        if not sqlpath.exists():
            print(f"[ERROR] osdag_core SQL file not found: {sqlpath}")
            return

        # Decide whether the database needs (re)building: missing, empty, or
        # has no tables at all.
        needs_build = True
        if sqlitepath.exists() and sqlitepath.stat().st_size > 0:
            try:
                conn = sqlite3.connect(str(sqlitepath))
                has_tables = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' LIMIT 1"
                ).fetchone()
                conn.close()
                needs_build = has_tables is None
            except Exception:
                needs_build = True

        if not needs_build:
            return

        with open(sqlpath, 'r', encoding='utf-8') as sql_file:
            sql_content = sql_file.read()

        conn = sqlite3.connect(str(sqlitepath))
        conn.executescript(sql_content)
        conn.commit()
        conn.close()
        print("[INFO] osdag_core Intg_osdag sqlite database built from SQL")

    except Exception as e:
        print(f"[ERROR] osdag_core database setup failed: {e}")


def load_stylesheet():
    """Load the global QSS stylesheet from resources."""
    from PySide6.QtCore import QFile, QTextStream
    file = QFile(":/themes/lightstyle.qss")
    if file.open(QFile.ReadOnly | QFile.Text):
        stream = QTextStream(file)
        stylesheet = stream.readAll()
        file.close()
        return stylesheet
    return ""

def main():
    # The databases first, as before: the UI's imports read them
    create_sqlite()
    ensure_osdag_core_db()

    from PySide6.QtWidgets import QApplication
    from osdagbridge_desktop.resources import resources_rc  # noqa: F401  (registers the Qt resources)
    from osdagbridge_desktop.ui.template_page import CustomWindow
    from osdagbridge_core.bridge_types.plate_girder.plategirderbridge import PlateGirderBridge

    # Establish the Windows taskbar identity before the QApplication so the
    # taskbar uses our icon, not the host Python interpreter's.
    set_windows_app_id()

    # Create the Qt application instance
    app = QApplication(sys.argv)

    # Application-wide icon: taskbar, Alt-Tab, and default window icon.
    icon = _app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)

    # Load and apply the global stylesheet
    stylesheet = load_stylesheet()
    if stylesheet:
        app.setStyleSheet(stylesheet)

    window = CustomWindow("OsdagBridge", PlateGirderBridge)
    if not icon.isNull():
        window.setWindowIcon(icon)
    window.showMaximized()
    window.show()

    # Execute the event loop
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
