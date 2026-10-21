param([string]$Python = '', [switch]$Retrain)
$ErrorActionPreference = 'Stop'
if (-not $Python) {
    $bundledPython = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
    if (Test-Path -LiteralPath $bundledPython) { $Python = $bundledPython }
    else { $Python = 'python' }
}
$env:PYTHONIOENCODING = 'utf-8'
& $Python (Join-Path $PSScriptRoot '../step010/verify_har.py') --check
if ($LASTEXITCODE -ne 0) { throw 'Frozen step010 changed' }
$unitOutput = & $Python (Join-Path $PSScriptRoot 'test_step011.py') 2>&1
$unitExit = $LASTEXITCODE
$unitOutput | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'unit_tests.log') -Encoding utf8
$unitOutput | Write-Output
if ($unitExit -ne 0) { throw 'Step011 contract tests failed' }
if ($Retrain) {
    & $Python (Join-Path $PSScriptRoot 'train_compare.py')
    if ($LASTEXITCODE -ne 0) { throw 'Step011 CV/refit failed' }
}
& $Python (Join-Path $PSScriptRoot 'verify_step011.py')
if ($LASTEXITCODE -ne 0) { throw 'Step011 measurement failed' }
& $Python (Join-Path $PSScriptRoot 'report.py')
if ($LASTEXITCODE -ne 0) { throw 'Step011 report failed' }
& $Python (Join-Path $PSScriptRoot 'verify_step011.py') --seal
if ($LASTEXITCODE -ne 0) { throw 'Step011 seal failed' }
& $Python (Join-Path $PSScriptRoot 'verify_step011.py') --check
if ($LASTEXITCODE -ne 0) { throw 'Step011 check failed' }
