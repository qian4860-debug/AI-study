$ErrorActionPreference='Stop'
$optBin=if($env:VIVADO_BIN){$env:VIVADO_BIN}else{'D:\vivado\2025.1\Vivado\bin'}
$optTemp=Join-Path ([System.IO.Path]::GetTempPath()) ('memory_optimization_'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path (Join-Path $optTemp 'build') -Force | Out-Null
foreach($optStep in @('step003','step004','step005')){
 New-Item -ItemType Directory -Path (Join-Path $optTemp $optStep) -Force | Out-Null
 Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot $optStep) -Filter *.v | Copy-Item -Destination (Join-Path $optTemp $optStep)
}
foreach($optStep in @('baseline','step006')){New-Item -ItemType Directory -Path (Join-Path $optTemp $optStep) -Force | Out-Null}
foreach($optFile in @('dot_banked_core.v','bank_ram.v')){Copy-Item -LiteralPath (Join-Path $PSScriptRoot ('..\step004\'+$optFile)) -Destination (Join-Path $optTemp 'baseline')}
foreach($optFile in @('requant_i8.v','mlp2_top.v')){Copy-Item -LiteralPath (Join-Path $PSScriptRoot ('..\step006\'+$optFile)) -Destination (Join-Path $optTemp 'step006')}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'synthesize.tcl') -Destination $optTemp
Push-Location -LiteralPath (Join-Path $optTemp 'build')
try{
 & (Join-Path $optBin 'vivado.bat') -mode batch -source ../synthesize.tcl -notrace
 $optExit=$LASTEXITCODE
 Copy-Item -LiteralPath (Join-Path $optTemp 'build\vivado.log') -Destination (Join-Path $PSScriptRoot 'synthesis_process.log')
 if($optExit -ne 0){throw "Vivado failed: inspect $optTemp"}
 Get-ChildItem -LiteralPath $optTemp -File | Where-Object {$_.Extension -eq '.rpt' -or $_.Name -eq 'synthesis_results.json'} | Copy-Item -Destination $PSScriptRoot
 Write-Output "Reports saved; temporary project $optTemp"
}finally{Pop-Location}
