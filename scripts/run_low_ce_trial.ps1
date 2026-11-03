# Compare a lower expert-loss weight while keeping two main PPO workers busy.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Python,
      [string]$PlanPath='runs/standalone-rl/low_ce_plan.json')
$ErrorActionPreference='Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
. "$PSScriptRoot/rl_process_identity.ps1"
[System.Diagnostics.Process]::GetCurrentProcess().PriorityClass='BelowNormal'
$rlPlan=Get-Content $PlanPath -Raw | ConvertFrom-Json
$rlControl='runs/standalone-rl/low-ce-control'
$null=New-Item -ItemType Directory -Path $rlControl -Force
$rlMainStopped=$false
function Event([string]$Name,$Detail){
    [ordered]@{utc=[DateTime]::UtcNow.ToString('o');event=$Name;detail=$Detail} |
        ConvertTo-Json -Compress -Depth 12 | Add-Content "$rlControl/events.jsonl" -Encoding utf8
}
function Live([string]$Run){
    $rlPath="runs/standalone-rl/$Run/process.json"
    if(-not(Test-Path $rlPath)){return $false}
    $rlInfo=Get-Content $rlPath -Raw | ConvertFrom-Json
    $rlProcess=Get-Process -Id $rlInfo.pid -ErrorAction SilentlyContinue
    if(-not $rlProcess){return $false}
    return [Math]::Abs(($rlProcess.StartTime.ToUniversalTime() - (Convert-RlRecordedStartToUtc $rlInfo.started_utc)).TotalSeconds) -lt 30
}
function Stop-Owned([string]$Run,[string]$Entry,[int]$MaxWorkers){
    if(-not(Live $Run)){return}
    $rlInfo=Get-Content "runs/standalone-rl/$Run/process.json" -Raw | ConvertFrom-Json
    $rlProcess=Get-CimInstance Win32_Process -Filter "ProcessId = $($rlInfo.pid)"
    if($rlProcess.CommandLine -notlike "*$Entry*--run $Run*"){throw 'Owned process identity mismatch.'}
    $rlChildren=@(Get-CimInstance Win32_Process -Filter "ParentProcessId = $($rlInfo.pid)" | Where-Object Name -eq 'python.exe')
    if($rlChildren.Count -gt $MaxWorkers){throw 'Unexpected owned worker count.'}
    Event 'owned_stop' @{run=$Run;pid=$rlInfo.pid;workers=@($rlChildren.ProcessId)}
    $rlChildren | ForEach-Object{Stop-Process -Id $_.ProcessId -Force}
    Stop-Process -Id $rlInfo.pid -Force
}
function Resume-Run([string]$Run,[string]$Entry,[int]$Batch){
    $rlEvery=if($Run -eq $rlPlan.run){'4'}else{'8'}
    & "$PSScriptRoot/run_standalone_rl.ps1" -Run $Run -Python $Python -EntryScript $Entry -Command run -TrainingArguments @(
        '--bootstrap-games','0','--workers','3','--hours','36','--batch-games',"$Batch",'--train-samples','32',
        '--curriculum-rounds','0','--anchor','0.01','--demo-weight','0.1','--rate','0.0002',
        '--validation-every',$rlEvery,'--validation-pairings','128','--pairings','1200',
        '--test-reserve-hours','12','--budget-deadline',"$($rlPlan.budget_deadline_unix)") | Out-Null
    Event 'three_worker_run_started' @{run=$Run;entry=$Entry;batch=$Batch}
}
try{
    Event 'controller_start' @{pid=$PID;plan=$rlPlan}
    $rlMain=Get-Content runs/standalone-rl/mc-ppo-v3/process.json -Raw | ConvertFrom-Json
    $rlChildren=@(Get-CimInstance Win32_Process -Filter "ParentProcessId = $($rlMain.pid)" | Where-Object Name -eq 'python.exe')
    if(-not(Live 'mc-ppo-v3') -or $rlChildren.Count -ne 2){throw 'Expected two live main PPO workers.'}
    $rlArgs=@('--ref',$rlPlan.frozen_commit,'--start',$rlPlan.start,'--seed',"$($rlPlan.seed)",
        '--bootstrap-games','0','--workers','1','--hours',"$($rlPlan.max_hours)",
        '--max-rounds',"$($rlPlan.max_rounds)",'--batch-games','128','--train-samples','32',
        '--curriculum-rounds','0','--rate','0.0002','--anchor','0.01','--demo-weight','0.1',
        '--validation-every','4','--validation-pairings','128','--pairings','1200',
        '--test-reserve-hours','14','--budget-deadline',"$($rlPlan.budget_deadline_unix)")
    & $Python scripts/student_correction_rl.py prepare --run $rlPlan.run @rlArgs
    if($LASTEXITCODE -ne 0){throw 'Low-CE preparation failed.'}
    & "$PSScriptRoot/run_standalone_rl.ps1" -Run $rlPlan.run -Python $Python -EntryScript scripts/student_correction_rl.py -Command train -TrainingArguments $rlArgs | Out-Null
    while(Live $rlPlan.run){
        if(Get-Content "runs/standalone-rl/$($rlPlan.run)/run.err" -Raw){throw 'Low-CE worker reported an error.'}
        Start-Sleep -Seconds 30
    }
    if(Get-Content "runs/standalone-rl/$($rlPlan.run)/run.err" -Raw){throw 'Low-CE training failed.'}
    $rlLast=Get-Content "runs/standalone-rl/$($rlPlan.run)/experiments.jsonl" -Tail 1 | ConvertFrom-Json
    if($rlLast.event -ne 'training_stopped'){throw 'Low-CE run did not close its training journal.'}
    Event 'side_training_complete' $rlLast.state
    $rlBefore=Get-Content runs/standalone-rl/mc-ppo-v3/state.json -Raw | ConvertFrom-Json
    do{
        if(-not(Live 'mc-ppo-v3') -or (Test-Path runs/standalone-rl/mc-ppo-v3/lock.json)){throw 'Main run became terminal or locked; inspect before selecting.'}
        Start-Sleep -Seconds 15
        $rlCurrent=Get-Content runs/standalone-rl/mc-ppo-v3/state.json -Raw | ConvertFrom-Json
    }while($rlCurrent.round -le $rlBefore.round)
    if($rlCurrent.phase -ne 'ppo'){throw 'Main run is no longer training.'}
    Stop-Owned 'mc-ppo-v3' 'monte_carlo_rl.py' 2
    $rlMainStopped=$true
    & $Python scripts/select_student_candidate.py --candidate $rlPlan.run --output "$rlControl/decision.json"
    if($LASTEXITCODE -ne 0){throw 'Low-CE selection failed.'}
    $rlDecision=Get-Content "$rlControl/decision.json" -Raw | ConvertFrom-Json
    if($rlDecision.selected.run -notin @('mc-ppo-v3',$rlPlan.run)){throw 'Unexpected selected run.'}
    Resume-Run $rlDecision.selected.run $rlDecision.entry $rlDecision.batch_games
    $rlMainStopped=$false
    Event 'selection_complete' $rlDecision
}catch{
    Event 'controller_error' $_.Exception.Message
    Stop-Owned $rlPlan.run 'student_correction_rl.py' 1
    if($rlMainStopped){
        Resume-Run 'mc-ppo-v3' 'scripts/monte_carlo_rl.py' 256
    }elseif((Live 'mc-ppo-v3') -and -not(Test-Path runs/standalone-rl/mc-ppo-v3/lock.json)){
        & "$PSScriptRoot/finish_capacity_trial.ps1" -Python $Python -BudgetDeadline $rlPlan.budget_deadline_unix -ResumeWorkers 3
    }
    throw
}
