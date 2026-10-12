# PyInstaller spec: one console binary (`dbx-discovery`) that is the whole tool.
#
#   pyinstaller --noconfirm --clean packaging/dbx_premig.spec      (or: make build)
#
# Entry point is the root discovery.py. Every data file read through dbx_premig/resources.py
# must be listed in `datas`; a missing entry is the classic failure (the binary starts, then
# dies on its first discovery). build.sh / build.ps1 smoke-test the built binary to catch it.
# UPX is off (antivirus false positives, slower start-up). db/ and api/ are excluded.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT))
from dbx_premig.version import APP_VERSION  # noqa: E402

PKG = ROOT / "dbx_premig"
datas = [
    (str(PKG / "catalog" / "data"), "dbx_premig/catalog/data"),
    (str(PKG / "excel" / "assets"), "dbx_premig/excel/assets"),
]
hiddenimports = [
    m for m in collect_submodules("dbx_premig")
    if not m.startswith(("dbx_premig.db", "dbx_premig.api"))
] + ["openpyxl.cell._writer", "pydantic.deprecated.decorator"]

icon = ROOT / "packaging" / ("app.ico" if sys.platform.startswith("win") else "app.png")

a = Analysis(
    [str(ROOT / "discovery.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["dbx_premig.db", "dbx_premig.api", "tkinter", "pytest", "IPython", "numpy",
              "pandas", "matplotlib", "cairosvg"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="dbx-discovery",
    console=True,
    upx=False,
    icon=str(icon) if icon.exists() else None,
    version=str(ROOT / "packaging" / "file_version_info.txt") if sys.platform.startswith("win") else None,
)
