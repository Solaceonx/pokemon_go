# Temporarily allocate one of three workers to a fixed rollout-model screen.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Python,
    [string]$PlanPath='runs/standalone-rl/greedy_rollout_plan.json'
)
$ErrorActionPreference='Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
. "$PSScriptRoot/rl_process_identity.ps1"
[System.Diagnostics.Process]::GetCurrentProcess().PriorityClass='BelowNormal'
$rlPlan=Get-Content $PlanPath -Raw | ConvertFrom-Json
$rlControl='runs/standalone-rl/greedy-rollout-control'
$null=New-Item -ItemType Directory -Path $rlControl -Force
function Event([string]$Name,$Detail) {
    [ordered]@{utc=[DateTime]::UtcNow.ToString('o');event=$Name;detail=$Detail} |
        ConvertTo-Json -Compress -Depth 10 | Add-Content "$rlControl/events.jsonl" -Encoding utf8
}
function Job-Live([string]$Run) {
    $rlPath="runs/standalone-rl/$Run/process.json"
    if(-not(Test-Path $rlPath)){return $false}
    $rlRecord=Get-Content $rlPath -Raw | ConvertFrom-Json
    $rlProcess=Get-Process -Id $rlRecord.pid -ErrorAction SilentlyContinue
    if(-not $rlProcess){return $false}
    return [Math]::Abs(($rlProcess.StartTime.ToUniversalTime() - (Convert-RlRecordedStartToUtc $rlRecord.started_utc)).TotalSeconds) -lt 30
}
function Stop-OwnedTrial([string]$Run) {
    if(-not(Job-Live $Run)){return}
    $rlRecord=Get-Content "runs/standalone-rl/$Run/process.json" -Raw | ConvertFrom-Json
    $rlProcess=Get-CimInstance Win32_Process -Filter "ProcessId = $($rlRecord.pid)"
    if($rlProcess.CommandLine -notlike "*evaluate_greedy_rollouts_rl.py*--run $Run*"){throw 'Trial identity mismatch; no process stopped.'}
    $rlChildren=@(Get-CimInstance Win32_Process -Filter "ParentProcessId = $($rlRecord.pid)" | Where-Object Name -eq 'python.exe')
    if($rlChildren.Count -gt 1){throw 'Unexpected trial worker count.'}
    $rlChildren | ForEach-Object{Stop-Process -Id $_.ProcessId -Force}
    Stop-Process -Id $rlRecord.pid -Force
    Event 'owned_trial_stopped' $Run
}
function Run-Validation([string]$Run,[string]$Seed,[int]$Pairings) {
    if([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() -ge $rlPlan.budget_deadline_unix - 12*3600){throw 'Final-test reserve reached.'}
    $rlMain=Get-Content runs/standalone-rl/mc-ppo-v3/process.json -Raw | ConvertFrom-Json
    for($rlAttempt=0;$rlAttempt -lt 30;$rlAttempt++){
        $rlWorkers=@(Get-CimInstance Win32_Process -Filter "ParentProcessId = $($rlMain.pid)" | Where-Object Name -eq 'python.exe')
        if($rlWorkers.Count -eq 2){break}
        if($rlWorkers.Count -gt 2 -or -not(Get-Process -Id $rlMain.pid -ErrorAction SilentlyContinue)){throw 'Unexpected main PPO allocation.'}
        Start-Sleep -Seconds 1
    }
    if($rlWorkers.Count -ne 2){throw 'Expected exactly two main PPO workers before allocating the third.'}
    $rlArgs=@('--start',$rlPlan.own_policy,'--opponent-policy',$rlPlan.opponent_policy,
        '--ref',$rlPlan.frozen_commit,'--seed',$Seed,'--samples',"$($rlPlan.planning.samples)",
        '--confidence',"$($rlPlan.planning.confidence)",'--validation-pairings',"$Pairings",'--pairings','1200',
        '--workers','1','--budget-deadline',"$($rlPlan.budget_deadline_unix)")
    Event 'prepare' @{run=$Run;arguments=$rlArgs}
    & $Python scripts/evaluate_greedy_rollouts_rl.py prepare --run $Run @rlArgs
    if($LASTEXITCODE -ne 0){throw "$Run preparation failed."}
    & "$PSScriptRoot/run_standalone_rl.ps1" -Run $Run -Python $Python -EntryScript scripts/evaluate_greedy_rollouts_rl.py -Command validate -TrainingArguments $rlArgs | Out-Null
    while(Job-Live $Run){
        if(Get-Content "runs/standalone-rl/$Run/run.err" -Raw){throw "$Run reported an error."}
        if([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() -ge $rlPlan.budget_deadline_unix - 12*3600){throw 'Final-test reserve reached.'}
        Start-Sleep -Seconds 30
    }
    if(Get-Content "runs/standalone-rl/$Run/run.err" -Raw){throw "$Run reported an error."}
    $rlResult=Get-Content "runs/standalone-rl/$Run/validation_summary.json" -Raw | ConvertFrom-Json
    if($rlResult.pairings -ne $Pairings -or $rlResult.header.samples -ne 32){throw 'Incomplete full-engine validation.'}
    Event 'validation_complete' @{run=$Run;pairings=$Pairings}
}
try {
    Event 'controller_start' @{pid=$PID;deadline=$rlPlan.budget_deadline_unix}
    & "$PSScriptRoot/finish_capacity_trial.ps1" -Python $Python -BudgetDeadline $rlPlan.budget_deadline_unix -ResumeWorkers 2
    Run-Validation $rlPlan.pipeline_run "$($rlPlan.seed)" 2
    Run-Validation $rlPlan.screen_run "$($rlPlan.seed)" $rlPlan.screen_pairings
    & $Python scripts/decide_greedy_rollouts.py --plan $PlanPath --stage screen
    if($LASTEXITCODE -ne 0){throw 'Screen decision failed.'}
    $rlDecision=Get-Content "runs/standalone-rl/$($rlPlan.screen_run)/decision.json" -Raw | ConvertFrom-Json
    Event 'screen_decision' $rlDecision
    if($rlDecision.advance){
        Run-Validation $rlPlan.confirmation_run "$($rlPlan.confirmation_seed)" $rlPlan.confirmation_pairings
        & $Python scripts/decide_greedy_rollouts.py --plan $PlanPath --stage confirmation
        if($LASTEXITCODE -ne 0){throw 'Confirmation decision failed.'}
        Event 'confirmation_complete' $rlPlan.confirmation_run
    }
} catch {
    Event 'controller_error' $_.Exception.Message
    throw
} finally {
    # A failure must not strand a fourth worker or leave the main allocation reduced.
    foreach($rlRun in @($rlPlan.pipeline_run,$rlPlan.screen_run,$rlPlan.confirmation_run)){Stop-OwnedTrial $rlRun}
    & "$PSScriptRoot/finish_capacity_trial.ps1" -Python $Python -BudgetDeadline $rlPlan.budget_deadline_unix -ResumeWorkers 3
    Event 'three_worker_main_resumed' $null
}
