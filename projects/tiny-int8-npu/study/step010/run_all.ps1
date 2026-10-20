param([string]$Python = '', [switch]$Retrain)
$ErrorActionPreference = 'Stop'
if (-not $Python) {
    $bundledPython = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
    if (Test-Path -LiteralPath $bundledPython) { $Python = $bundledPython }
    else { $Python = 'python' }
}
& $Python (Join-Path $PSScriptRoot 'prepare_data.py')
if ($LASTEXITCODE -ne 0) { throw 'HAR dataset hashes failed' }
if ($Retrain) {
    & $Python (Join-Path $PSScriptRoot 'train_har.py')
    if ($LASTEXITCODE -ne 0) { throw 'HAR training failed' }
}
$unitOutput = & $Python (Join-Path $PSScriptRoot 'test_har.py') 2>&1
$unitExit = $LASTEXITCODE
$unitOutput | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'unit_tests.log') -Encoding utf8
$unitOutput | Write-Output
if ($unitExit -ne 0) { throw 'HAR preprocessing/split tests failed' }
& $Python (Join-Path $PSScriptRoot 'verify_har.py')
if ($LASTEXITCODE -ne 0) { throw 'HAR actual RTL/evaluation failed' }
& $Python (Join-Path $PSScriptRoot 'verify_har.py') --seal
if ($LASTEXITCODE -ne 0) { throw 'HAR sealing failed' }
& $Python (Join-Path $PSScriptRoot 'verify_har.py') --check
if ($LASTEXITCODE -ne 0) { throw 'HAR artifact check failed' }
