# Use an ASCII temporary working path, retaining the generated reports here.
$ErrorActionPreference = 'Stop'
$step002Bin = if ($env:VIVADO_BIN) { $env:VIVADO_BIN } else { 'D:\vivado\2025.1\Vivado\bin' }
$step002Exe = Join-Path $step002Bin 'vivado.bat'
if (-not (Test-Path -LiteralPath $step002Exe)) { throw "Missing Vivado: $step002Exe" }
$step002Temp = Join-Path ([System.IO.Path]::GetTempPath()) ('dot_step002_' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path (Join-Path $step002Temp 'build') -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'dot_serial_cfg.v'), (Join-Path $PSScriptRoot 'synthesize.tcl') -Destination $step002Temp
Push-Location -LiteralPath (Join-Path $step002Temp 'build')
try {
    & $step002Exe -mode batch -source ../synthesize.tcl -notrace
    $step002Exit = $LASTEXITCODE
    Copy-Item -LiteralPath (Join-Path $step002Temp 'build\vivado.log') -Destination (Join-Path $PSScriptRoot 'synthesis_process.log')
    if ($step002Exit -ne 0) { throw "Vivado exited with $step002Exit; working files retained in $step002Temp" }
    Copy-Item -LiteralPath (Join-Path $step002Temp 'synthesis_results.json'), (Join-Path $step002Temp 'synthesis_utilization.rpt'), (Join-Path $step002Temp 'synthesis_timing.rpt') -Destination $PSScriptRoot
    Write-Output "Reports saved to $PSScriptRoot; working files retained in $step002Temp"
} finally {
    Pop-Location
}
