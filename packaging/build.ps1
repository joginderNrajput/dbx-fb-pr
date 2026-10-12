# Build dbx-discovery.exe on Windows (PyInstaller cannot cross-compile) and smoke-test it.
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$py = if ($env:PYTHON) { $env:PYTHON } else { "python" }

& $py -m PyInstaller --noconfirm --clean --distpath dist --workpath build\pyinstaller packaging\dbx_premig.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$bin = "dist\dbx-discovery.exe"
$smoke = "build\smoke"
if (Test-Path $smoke) { Remove-Item -Recurse -Force $smoke }
New-Item -ItemType Directory -Force $smoke | Out-Null

& $bin version; if ($LASTEXITCODE -ne 0) { throw "version failed" }
& $bin catalog-info; if ($LASTEXITCODE -ne 0) { throw "catalog-info failed" }
& $bin discover --input tests\fixtures\mini\snapshot.json --out $smoke --name live.xlsx
if ($LASTEXITCODE -ne 0) { throw "live fixture discovery failed" }
& $bin discover --input tests\fixtures\mini\notebooks --out $smoke --name offline.xlsx
if ($LASTEXITCODE -ne 0) { throw "offline discovery failed" }
& $py packaging\verify_workbook.py "$smoke\live.xlsx" --min-assets 40
& $py packaging\verify_workbook.py "$smoke\offline.xlsx" --min-assets 5
& $bin assess --input "$smoke\live.xlsx" --out $smoke --name assessment.xlsx
if ($LASTEXITCODE -ne 0) { throw "assessment failed" }
& $py packaging\verify_workbook.py "$smoke\assessment.xlsx" --kind assessment --min-assets 40
if ($LASTEXITCODE -ne 0) { throw "workbook verification failed" }
Write-Host "OK: $bin"
