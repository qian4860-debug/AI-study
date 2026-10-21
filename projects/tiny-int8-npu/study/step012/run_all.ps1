param([string]$Python = '', [switch]$Regenerate)
$ErrorActionPreference = 'Stop'
if (-not $Python) {
    $bundledPython = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
    if (Test-Path -LiteralPath $bundledPython) { $Python = $bundledPython }
    else { $Python = 'python' }
}
$env:PYTHONIOENCODING = 'utf-8'
if ($Regenerate) {
    & $Python (Join-Path $PSScriptRoot 'verify_step012.py') --regenerate
} else {
    & $Python (Join-Path $PSScriptRoot 'verify_step012.py')
}
if ($LASTEXITCODE -ne 0) { throw 'Step012 calibration/RTL validation failed' }
