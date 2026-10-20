$ErrorActionPreference='Stop'
$step004Bin=if($env:VIVADO_BIN){$env:VIVADO_BIN}else{'D:\vivado\2025.1\Vivado\bin'}
$step004Exe=Join-Path $step004Bin 'vivado.bat'
if(-not(Test-Path -LiteralPath $step004Exe)){throw "Missing Vivado: $step004Exe"}
$step004Temp=Join-Path ([System.IO.Path]::GetTempPath()) ('dot_step004_'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path (Join-Path $step004Temp 'build') -Force | Out-Null
foreach($step004Name in @('dot_banked_core.v','bank_ram.v','dot_banked_top.v','synthesize.tcl')){
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $step004Name) -Destination $step004Temp
}
Push-Location -LiteralPath (Join-Path $step004Temp 'build')
try{
    & $step004Exe -mode batch -source ../synthesize.tcl -notrace
    $step004Exit=$LASTEXITCODE
    Copy-Item -LiteralPath (Join-Path $step004Temp 'build\vivado.log') -Destination (Join-Path $PSScriptRoot 'synthesis_process.log')
    if($step004Exit -ne 0){throw "Vivado exit=$step004Exit; inspect $step004Temp"}
    Copy-Item -LiteralPath (Join-Path $step004Temp 'synthesis_results.json') -Destination $PSScriptRoot
    foreach($step004P in @(1,2,4)){
        foreach($step004Prefix in @('util','timing')){
            Copy-Item -LiteralPath (Join-Path $step004Temp ($step004Prefix+'_p'+$step004P+'.rpt')) -Destination $PSScriptRoot
        }
    }
    Write-Output "Reports saved to $PSScriptRoot; temporary files retained in $step004Temp"
}finally{Pop-Location}
