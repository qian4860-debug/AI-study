$ErrorActionPreference='Stop'
$pipeBin=if($env:VIVADO_BIN){$env:VIVADO_BIN}else{'D:\vivado\2025.1\Vivado\bin'}
$pipeTemp=Join-Path ([System.IO.Path]::GetTempPath()) ('quant_pipeline_'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path (Join-Path $pipeTemp 'build') -Force | Out-Null
foreach($pipeName in @('requant_i8.v','mlp2_top.v','synthesize.tcl')){Copy-Item -LiteralPath (Join-Path $PSScriptRoot $pipeName) -Destination $pipeTemp}
foreach($pipeName in @('dot_banked_core.v')){Copy-Item -LiteralPath (Join-Path $PSScriptRoot ('..\..\step004\'+$pipeName)) -Destination $pipeTemp}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot '..\..\step005\fc_int8_top.v') -Destination $pipeTemp
Copy-Item -LiteralPath (Join-Path $PSScriptRoot '..\..\step004\bank_ram.v') -Destination (Join-Path $pipeTemp 'bank_ram_block.v')
Copy-Item -LiteralPath (Join-Path $PSScriptRoot '..\step005\bank_ram.v') -Destination (Join-Path $pipeTemp 'bank_ram_distributed.v')
Push-Location -LiteralPath (Join-Path $pipeTemp 'build')
try{
 & (Join-Path $pipeBin 'vivado.bat') -mode batch -source ../synthesize.tcl -notrace
 $pipeExit=$LASTEXITCODE
 Copy-Item -LiteralPath (Join-Path $pipeTemp 'build\vivado.log') -Destination (Join-Path $PSScriptRoot 'synthesis_process.log')
 if($pipeExit -ne 0){throw "Vivado failed: inspect $pipeTemp"}
 Get-ChildItem -LiteralPath $pipeTemp -File | Where-Object {$_.Extension -eq '.rpt' -or $_.Name -eq 'synthesis_results.json'} | Copy-Item -Destination $PSScriptRoot
 Write-Output "Reports saved; temporary project $pipeTemp"
}finally{Pop-Location}
