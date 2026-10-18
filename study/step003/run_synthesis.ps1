$ErrorActionPreference = 'Stop'
$step003Bin = if ($env:VIVADO_BIN) { $env:VIVADO_BIN } else { 'D:\vivado\2025.1\Vivado\bin' }
$step003Exe = Join-Path $step003Bin 'vivado.bat'
if (-not (Test-Path -LiteralPath $step003Exe)) { throw "Missing Vivado: $step003Exe" }
$step003Temp = Join-Path ([System.IO.Path]::GetTempPath()) ('dot_step003_' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path (Join-Path $step003Temp 'build') -Force | Out-Null
foreach ($step003Name in @('dot_serial_mem.v','sync_byte_ram.v','dot_mem_top.v','synthesize.tcl')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $step003Name) -Destination $step003Temp
}
Push-Location -LiteralPath (Join-Path $step003Temp 'build')
try {
    & $step003Exe -mode batch -source ../synthesize.tcl -notrace
    $step003Exit = $LASTEXITCODE
    Copy-Item -LiteralPath (Join-Path $step003Temp 'build\vivado.log') -Destination (Join-Path $PSScriptRoot 'synthesis_process.log')
    if ($step003Exit -ne 0) { throw "Vivado exit=$step003Exit; inspect $step003Temp" }
    foreach ($step003Name in @('synthesis_results.json','synthesis_utilization.rpt','synthesis_timing.rpt')) {
        Copy-Item -LiteralPath (Join-Path $step003Temp $step003Name) -Destination $PSScriptRoot
    }
    Write-Output "Reports saved to $PSScriptRoot; temporary files retained in $step003Temp"
} finally { Pop-Location }
