$ErrorActionPreference='Stop'
$step005Bin=if($env:VIVADO_BIN){$env:VIVADO_BIN}else{'D:\vivado\2025.1\Vivado\bin'}
$step005Exe=Join-Path $step005Bin 'vivado.bat'
if(-not(Test-Path -LiteralPath $step005Exe)){throw "Missing Vivado: $step005Exe"}
$step005Temp=Join-Path ([System.IO.Path]::GetTempPath()) ('fc_step005_'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path (Join-Path $step005Temp 'build') -Force | Out-Null
foreach($step005Name in @('fc_int8_top.v','synthesize.tcl')){
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $step005Name) -Destination $step005Temp
}
foreach($step005Name in @('dot_banked_core.v','bank_ram.v')){
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot ('..\step004\'+$step005Name)) -Destination $step005Temp
}
Push-Location -LiteralPath (Join-Path $step005Temp 'build')
try{
    & $step005Exe -mode batch -source ../synthesize.tcl -notrace
    $step005Exit=$LASTEXITCODE
    Copy-Item -LiteralPath (Join-Path $step005Temp 'build\vivado.log') -Destination (Join-Path $PSScriptRoot 'synthesis_process.log')
    if($step005Exit -ne 0){throw "Vivado exit=$step005Exit; inspect $step005Temp"}
    foreach($step005Name in @('synthesis_results.json','synthesis_utilization.rpt','synthesis_timing.rpt')){
        Copy-Item -LiteralPath (Join-Path $step005Temp $step005Name) -Destination $PSScriptRoot
    }
    Write-Output "Reports saved to $PSScriptRoot; temporary files retained in $step005Temp"
}finally{Pop-Location}
