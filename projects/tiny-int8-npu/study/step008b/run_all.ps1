param([string]$Python=(Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'))
$ErrorActionPreference='Stop'
foreach($bTask in @('verify_step008b.py','verify_baseline_grid.py')){
 & $Python (Join-Path $PSScriptRoot $bTask)
 if($LASTEXITCODE -ne 0){throw "RTL gate failed: $bTask"}
}
& (Join-Path $PSScriptRoot 'run_synthesis.ps1') *> (Join-Path $PSScriptRoot 'synthesis_console.log')
if($LASTEXITCODE -ne 0){throw 'Synthesis failed'}
& $Python (Join-Path $PSScriptRoot 'finalize_all.py')
if($LASTEXITCODE -ne 0){throw 'Combined acceptance failed'}
foreach($bFlag in @('--seal','--check')){
 & $Python (Join-Path $PSScriptRoot 'verify_step008b.py') $bFlag
 if($LASTEXITCODE -ne 0){throw "Artifact gate failed: $bFlag"}
}
Write-Output 'PASS STEP008B all'
