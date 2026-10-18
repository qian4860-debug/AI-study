$ErrorActionPreference='Stop'
$s7Bin=if($env:VIVADO_BIN){$env:VIVADO_BIN}else{'D:\vivado\2025.1\Vivado\bin'}
$s7Base=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$s7Temp=Join-Path ([System.IO.Path]::GetTempPath()) ('step007_'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path (Join-Path $s7Temp 'build') -Force | Out-Null
$s7Sources=@()
foreach($s7Name in @('sync_ram_style.v','fc_shared.v','mlp2_top.v','synthesize.tcl')){
 $s7Path=Join-Path $PSScriptRoot $s7Name
 Copy-Item -LiteralPath $s7Path -Destination $s7Temp
 $s7Sources+=$s7Path
}
foreach($s7Relative in @('step004\dot_banked_core.v','optimization\step006_pipelined\requant_i8.v')){
 $s7Path=Join-Path $s7Base $s7Relative
 Copy-Item -LiteralPath $s7Path -Destination $s7Temp
 $s7Sources+=$s7Path
}
$s7Sources+=(Join-Path $PSScriptRoot 'run_synthesis.ps1')
$s7Hashes=[ordered]@{}
foreach($s7Path in $s7Sources){$s7Hashes[$s7Path.Substring($s7Base.Length+1)]=(Get-FileHash -LiteralPath $s7Path -Algorithm SHA256).Hash.ToLowerInvariant()}
Push-Location -LiteralPath (Join-Path $s7Temp 'build')
try{
 & (Join-Path $s7Bin 'vivado.bat') -mode batch -source ../synthesize.tcl -notrace
 $s7Exit=$LASTEXITCODE
 Copy-Item -LiteralPath (Join-Path $s7Temp 'build\vivado.log') -Destination (Join-Path $PSScriptRoot 'synthesis_process.log')
 if($s7Exit -ne 0){throw "Vivado failed: inspect $s7Temp"}
 Get-ChildItem -LiteralPath $s7Temp -File -Filter *.rpt | Copy-Item -Destination $PSScriptRoot
 $s7Result=Get-Content -LiteralPath (Join-Path $s7Temp 'synthesis_results.json') -Raw | ConvertFrom-Json
 $s7Result | Add-Member -NotePropertyName source_sha256 -NotePropertyValue $s7Hashes
 $s7Result | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'synthesis_results.json') -Encoding utf8
 Write-Output "Reports saved to $PSScriptRoot; temporary project $s7Temp"
}finally{Pop-Location}
