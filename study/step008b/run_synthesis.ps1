$ErrorActionPreference='Stop'
$bBin=if($env:VIVADO_BIN){$env:VIVADO_BIN}else{'D:\vivado\2025.1\Vivado\bin'}
$bBase=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$bTemp=Join-Path ([System.IO.Path]::GetTempPath()) ('step008b_'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path (Join-Path $bTemp 'build') -Force | Out-Null
$bSources=@()
foreach($bName in @('dot_tile_core.v','fc_shared.v','synthesize.tcl')){
 $bPath=Join-Path $PSScriptRoot $bName;Copy-Item -LiteralPath $bPath -Destination $bTemp;$bSources+=$bPath
}
foreach($bRelative in @('optimization\step006_pipelined\requant_i8.v','step007\sync_ram_style.v','step007\mlp2_top.v')){
 $bPath=Join-Path $bBase $bRelative;Copy-Item -LiteralPath $bPath -Destination $bTemp;$bSources+=$bPath
}
$bSources+=(Join-Path $PSScriptRoot 'run_synthesis.ps1');$bHashes=[ordered]@{}
foreach($bPath in $bSources){$bHashes[$bPath.Substring($bBase.Length+1)]=(Get-FileHash -LiteralPath $bPath -Algorithm SHA256).Hash.ToLowerInvariant()}
Push-Location -LiteralPath (Join-Path $bTemp 'build')
try{
 & (Join-Path $bBin 'vivado.bat') -mode batch -source ../synthesize.tcl -notrace
 $bExit=$LASTEXITCODE
 Copy-Item -LiteralPath (Join-Path $bTemp 'build\vivado.log') -Destination (Join-Path $PSScriptRoot 'synthesis_process.log')
 if($bExit -ne 0){throw "Vivado failed: inspect $bTemp"}
 Get-ChildItem -LiteralPath $bTemp -File -Filter *.rpt | Copy-Item -Destination $PSScriptRoot
 $bResult=Get-Content -LiteralPath (Join-Path $bTemp 'synthesis_results.json') -Raw | ConvertFrom-Json
 $bResult | Add-Member -NotePropertyName source_sha256 -NotePropertyValue $bHashes
 [System.IO.File]::WriteAllText((Join-Path $PSScriptRoot 'synthesis_results.json'),($bResult | ConvertTo-Json -Depth 12),[System.Text.UTF8Encoding]::new($false))
 Write-Output "Reports saved; temporary project $bTemp"
}finally{Pop-Location}
