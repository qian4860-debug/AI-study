param([string]$Python = '')
$ErrorActionPreference = 'Stop'
if (-not $Python) {
    $bundledPython = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
    if (Test-Path -LiteralPath $bundledPython) { $Python = $bundledPython }
    else { $Python = 'python' }
}
& $Python (Join-Path $PSScriptRoot 'verify_step009.py')
if ($LASTEXITCODE -ne 0) { throw 'Step009 end-to-end verification failed' }
& $Python (Join-Path $PSScriptRoot 'verify_step009.py') --seal
if ($LASTEXITCODE -ne 0) { throw 'Step009 artifact sealing failed' }
& $Python (Join-Path $PSScriptRoot 'verify_step009.py') --check
if ($LASTEXITCODE -ne 0) { throw 'Step009 artifact check failed' }
