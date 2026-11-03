# Keep the locked PPO benchmark unchanged while one bounded offline trial runs.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Python,
      [string]$PlanPath='runs/standalone-rl/offline_returns_plan.json')
$ErrorActionPreference='Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
. "$PSScriptRoot/rl_process_identity.ps1"
[System.Diagnostics.Process]::GetCurrentProcess().PriorityClass='BelowNormal'
$rlPlan=Get-Content $PlanPath -Raw | ConvertFrom-Json
$rlControl='runs/standalone-rl/offline-return-control'
$null=New-Item -ItemType Directory -Path $rlControl -Force
$rlChangedAllocation=$false
function Event([string]$Name,$Detail){
    [ordered]@{utc=[DateTime]::UtcNow.ToString('o');event=$Name;detail=$Detail} |
        ConvertTo-Json -Compress -Depth 14 | Add-Content "$rlControl/events.jsonl" -Encoding utf8
}
function Live([string]$Run){
    $rlPath="runs/standalone-rl/$Run/process.json"
    if(-not(Test-Path $rlPath)){return $false}
    $rlInfo=Get-Content $rlPath -Raw | ConvertFrom-Json
    $rlP=Get-Process -Id $rlInfo.pid -ErrorAction SilentlyContinue
    if(-not $rlP){return $false}
    return [Math]::Abs(($rlP.StartTime.ToUniversalTime()-(Convert-RlRecordedStartToUtc $rlInfo.started_utc)).TotalSeconds) -lt 30
}
function Finished([string]$Run){
    $rlPath="runs/standalone-rl/$Run/test_results.json"
    if(-not(Test-Path $rlPath)){return $false}
    $rlReport=Get-Content $rlPath -Raw | ConvertFrom-Json
    return ($rlReport.PSObject.Properties.Name -contains 'reliably_beats_frozen_engine') -and @($rlReport.results.PSObject.Properties).Count -eq 4
}
function Stop-Owned([string]$Run,[string]$Entry,[int]$MaxWorkers){
    if(-not(Live $Run)){return}
    $rlInfo=Get-Content "runs/standalone-rl/$Run/process.json" -Raw | ConvertFrom-Json
    $rlP=Get-CimInstance Win32_Process -Filter "ProcessId = $($rlInfo.pid)"
    if($rlP.CommandLine -notlike "*$Entry*--run $Run*"){throw 'Owned process command mismatch.'}
    $rlChildren=@(Get-CimInstance Win32_Process -Filter "ParentProcessId = $($rlInfo.pid)" | Where-Object Name -eq 'python.exe')
    if($rlChildren.Count -gt $MaxWorkers){throw 'Unexpected owned worker count.'}
    Event 'owned_stop' @{run=$Run;pid=$rlInfo.pid;workers=@($rlChildren.ProcessId)}
    $rlChildren | ForEach-Object{Stop-Process -Id $_.ProcessId -Force}
    Stop-Process -Id $rlInfo.pid -Force
}
function Resume-Main([int]$Workers){
    if(Finished 'mc-ppo-v3'){return}
    & "$PSScriptRoot/run_standalone_rl.ps1" -Run 'mc-ppo-v3' -Python $Python -EntryScript scripts/monte_carlo_rl.py -Command test -TrainingArguments @(
        '--workers',"$Workers",'--pairings','1200','--budget-deadline',"$($rlPlan.budget_deadline_unix)") | Out-Null
    Event 'main_test_resumed' @{workers=$Workers;record=(Get-Content runs/standalone-rl/mc-ppo-v3/process.json -Raw | ConvertFrom-Json)}
}
function Restore-Main{
    if(Finished 'mc-ppo-v3'){return}
    if([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() -ge $rlPlan.budget_deadline_unix){return}
    Stop-Owned 'mc-ppo-v3' 'monte_carlo_rl.py' 3
    Resume-Main 3
}
function Launch-Trial([string]$Command,[int]$Workers){
    & "$PSScriptRoot/run_standalone_rl.ps1" -Run $rlPlan.run -Python $Python -EntryScript scripts/offline_returns_rl.py -Command $Command -TrainingArguments @(
        '--workers',"$Workers",'--budget-deadline',"$($rlPlan.budget_deadline_unix)",
        '--alpha','0.1','--epochs','4','--max-train-minutes','15','--batch-size','1024',
        '--rate','0.0002','--head-scale','0.1','--test-reserve-hours','5.5',
        '--seed','37001','--validation-pairings','128','--pairings','1200') | Out-Null
    Event 'offline_started' @{command=$Command;workers=$Workers;record=(Get-Content "runs/standalone-rl/$($rlPlan.run)/process.json" -Raw | ConvertFrom-Json)}
}
try{
    Event 'controller_start' @{pid=$PID;plan=$rlPlan}
    if(-not(Test-Path runs/standalone-rl/mc-ppo-v3/lock.json)){throw 'Original benchmark must already be locked.'}
    if([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() -gt $rlPlan.latest_trial_start_unix){throw 'Too late for the registered bounded trial.'}
    & $Python scripts/offline_returns_rl.py prepare --run $rlPlan.run --workers 1 --budget-deadline $rlPlan.budget_deadline_unix
    if($LASTEXITCODE -ne 0){throw 'Offline preparation failed.'}
    if(-not(Finished 'mc-ppo-v3')){
        if(-not(Live 'mc-ppo-v3')){throw 'Original benchmark is not live.'}
        $rlChangedAllocation=$true
        Stop-Owned 'mc-ppo-v3' 'monte_carlo_rl.py' 3
        Resume-Main 2
    }
    Launch-Trial 'train' 1
    $rlTrialEnd=[DateTime]::UtcNow.AddMinutes(90)
    while(Live $rlPlan.run){
        if(Get-Content "runs/standalone-rl/$($rlPlan.run)/run.err" -Raw){throw 'Offline trial reported an error.'}
        if([DateTime]::UtcNow -gt $rlTrialEnd){throw 'Offline training/validation exceeded its outer bound.'}
        Start-Sleep -Seconds 30
    }
    if(Get-Content "runs/standalone-rl/$($rlPlan.run)/run.err" -Raw){throw 'Offline trial failed.'}
    $rlDecision=Get-Content "runs/standalone-rl/$($rlPlan.run)/decision.json" -Raw | ConvertFrom-Json
    Event 'offline_validation_closed' $rlDecision
    if(-not $rlDecision.enter_final){
        if($rlChangedAllocation){Restore-Main}
        $rlChangedAllocation=$false
        Event 'trial_not_promoted' $rlDecision
        exit 0
    }
    if(Finished 'mc-ppo-v3'){
        Launch-Trial 'run' 3
        Event 'qualified_final_started' @{workers=3}
        $rlChangedAllocation=$false
        exit 0
    }
    Launch-Trial 'run' 1
    while(Live 'mc-ppo-v3'){
        if(Get-Content runs/standalone-rl/mc-ppo-v3/run.err -Raw){throw 'Original benchmark reported an error.'}
        if(Get-Content "runs/standalone-rl/$($rlPlan.run)/run.err" -Raw){throw 'Offline final evaluation reported an error.'}
        if(-not(Live $rlPlan.run) -and -not(Finished $rlPlan.run)){throw 'Offline final evaluation stopped unexpectedly.'}
        Start-Sleep -Seconds 30
    }
    if(-not(Finished 'mc-ppo-v3')){throw 'Original benchmark stopped without its complete final result.'}
    if((Live $rlPlan.run) -and -not(Finished $rlPlan.run)){
        Stop-Owned $rlPlan.run 'offline_returns_rl.py' 1
        Launch-Trial 'test' 3
    }
    $rlChangedAllocation=$false
    Event 'original_finished_offline_boosted' @{workers=3}
}catch{
    Event 'controller_error' $_.Exception.Message
    Stop-Owned $rlPlan.run 'offline_returns_rl.py' 1
    if($rlChangedAllocation){Restore-Main}
    throw
}
