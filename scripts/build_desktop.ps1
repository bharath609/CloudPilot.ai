# Build the CloudPilot AI Windows desktop installer.
#
# Usage (from the repository root):
#   powershell -ExecutionPolicy Bypass -File scripts/build_desktop.ps1
#
# Optional:
#   -PythonExe C:\Python314\python.exe    interpreter used to create the embedded runtime
#
# Requirements: Windows x64, Python 3.12+, Node.js 20+.

param(
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$frontend = Join-Path $root "frontend"
$runtime = Join-Path $frontend "pyrt"

function Resolve-Python {
    if ($PythonExe) { return $PythonExe }
    foreach ($candidate in @("python", "py")) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd) {
            $exe = & $cmd.Source -c "import sys; print(sys.executable)" 2>$null
            if ($exe) { return $exe.Trim() }
        }
    }
    throw "Python 3.12+ was not found. Pass -PythonExe <path to python.exe>."
}

$python = Resolve-Python
Write-Host "Using Python: $python"

# 1. Embedded Python runtime (relocatable CPython layout + only the API deps).
if (-not (Test-Path (Join-Path $runtime "python.exe"))) {
    Write-Host "Creating embedded Python runtime at $runtime"
    $pyHome = & $python -c "import sys; print(sys.base_prefix)"
    $pyHome = $pyHome.Trim()

    New-Item -ItemType Directory -Force $runtime | Out-Null
    foreach ($file in @("python.exe", "pythonw.exe", "python3.dll", "python314.dll", "vcruntime140.dll", "vcruntime140_1.dll")) {
        $src = Join-Path $pyHome $file
        if (Test-Path $src) { Copy-Item $src $runtime }
    }

    robocopy (Join-Path $pyHome "DLLs") (Join-Path $runtime "DLLs") /E /NFL /NDL /NJH /NJS /NP | Out-Null
    robocopy (Join-Path $pyHome "Lib") (Join-Path $runtime "Lib") /E `
        /XD (Join-Path $pyHome "Lib\site-packages") `
        (Join-Path $pyHome "Lib\test") (Join-Path $pyHome "Lib\idlelib") `
        (Join-Path $pyHome "Lib\ensurepip") (Join-Path $pyHome "Lib\lib2to3") `
        (Join-Path $pyHome "Lib\tkinter") (Join-Path $pyHome "Lib\turtledemo") `
        /NFL /NDL /NJH /NJS /NP | Out-Null

    & $python -m pip install --target (Join-Path $runtime "Lib\site-packages") --no-compile --no-warn-script-location fastapi uvicorn
} else {
    Write-Host "Embedded Python runtime already present"
}

# 2. Frontend build.
Push-Location $frontend
try {
    if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
        Write-Host "Installing npm dependencies"
        npm install
    }
    Write-Host "Building the SPA"
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "vite build failed" }

    # 3. Installer (Electron + backend + SPA + Python runtime).
    Write-Host "Packaging the Windows installer"
    npx electron-builder --win nsis
    if ($LASTEXITCODE -ne 0) { throw "electron-builder failed" }
} finally {
    Pop-Location
}

$output = Join-Path $frontend "dist-electron"
Write-Host ""
Write-Host "Done. Installer(s) in: $output"
Get-ChildItem $output -Filter "*.exe" | ForEach-Object {
    Write-Host ("  {0}  ({1:N1} MB)" -f $_.Name, ($_.Length / 1MB))
}
