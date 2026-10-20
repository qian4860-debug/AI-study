param([string]$Python=(Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'))
$ErrorActionPreference='Stop'
if(-not(Test-Path -LiteralPath $Python)){throw "Python not found; pass -Python with the installed runtime path"}
& $Python (Join-Path $PSScriptRoot 'verify_step007.py')
if($LASTEXITCODE -ne 0){throw 'RTL verification failed'}
& (Join-Path $PSScriptRoot 'run_synthesis.ps1') *> (Join-Path $PSScriptRoot 'synthesis_console.log')
if($LASTEXITCODE -ne 0){throw 'Synthesis failed'}
foreach($s7Action in @('--finalize','--seal','--check')){
 & $Python (Join-Path $PSScriptRoot 'verify_step007.py') $s7Action
 if($LASTEXITCODE -ne 0){throw "Final gate failed: $s7Action"}
}
Write-Output 'PASS STEP007 complete'
