# Finish the registered capacity validations, then use all three workers for
# the stronger validated policy. All training/evaluation sources stay unchanged.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Python,
    [double]$BudgetDeadline = 1793756530
)
$ErrorActionPreference = 'Stop'
$rlRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $rlRoot
. "$PSScriptRoot/rl_process_identity.ps1"
foreach ($rlVariable in @('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS')) {
    [Environment]::SetEnvironmentVariable($rlVariable, '1', 'Process')
}
[System.Diagnostics.Process]::GetCurrentProcess().PriorityClass = [System.Diagnostics.ProcessPriorityClass]::BelowNormal
$rlControl = Join-Path $rlRoot 'runs\standalone-rl\capacity-control'
$null = New-Item -ItemType Directory -Path $rlControl -Force
function Write-ControlEvent([string]$EventName, $Detail) {
    [ordered]@{utc=[DateTime]::UtcNow.ToString('o');event=$EventName;detail=$Detail} |
        ConvertTo-Json -Compress -Depth 12 | Add-Content -LiteralPath (Join-Path $rlControl 'events.jsonl') -Encoding utf8
}
function Assert-Time {
    if ([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() -ge $BudgetDeadline - 12*3600) {
        throw 'No time remains for another training/validation phase plus the final-test reserve.'
    }
}
function Test-JobLive([string]$Run) {
    $rlRecord = Get-Content -LiteralPath "runs/standalone-rl/$Run/process.json" -Raw | ConvertFrom-Json
    $rlProcess = Get-Process -Id $rlRecord.pid -ErrorAction SilentlyContinue
    if (-not $rlProcess) { return $false }
    $rlExpected = Convert-RlRecordedStartToUtc $rlRecord.started_utc
    if ([Math]::Abs(($rlProcess.StartTime.ToUniversalTime() - $rlExpected).TotalSeconds) -gt 30) {
        throw "Recorded PID for $Run was reused; no process will be stopped."
    }
    return $true
}
function Wait-Validation([string]$Run) {
    while (Test-JobLive $Run) {
        Assert-Time
        if (Get-Content -LiteralPath "runs/standalone-rl/$Run/run.err" -Raw) { throw "$Run reported an error." }
        Start-Sleep -Seconds 30
    }
    if (Get-Content -LiteralPath "runs/standalone-rl/$Run/run.err" -Raw) { throw "$Run reported an error." }
    $rlState = Get-Content -LiteralPath "runs/standalone-rl/$Run/state.json" -Raw | ConvertFrom-Json
    $rlLast = Get-Content -LiteralPath "runs/standalone-rl/$Run/experiments.jsonl" -Tail 1 | ConvertFrom-Json
    if ($rlState.round -ne 0 -or $rlState.phase -ne 'ppo' -or $rlLast.event -ne 'training_stopped') {
        throw "$Run did not finish its validation-only plan."
    }
    foreach ($rlMode in @('stochastic','greedy')) {
        $rlSummary = Get-Content -LiteralPath "runs/standalone-rl/$Run/validation_summary_00000_$rlMode.json" -Raw | ConvertFrom-Json
        if ($rlSummary.pairings -ne 128 -or $rlSummary.header.samples -ne 32) { throw 'Incomplete validation.' }
    }
    Write-ControlEvent 'validation_complete' $Run
}
function Launch-Job([string]$Run, [string]$Entry, [string]$Command, [string[]]$Arguments) {
    Assert-Time
    Write-ControlEvent 'launch' @{run=$Run;entry=$Entry;command=$Command;arguments=$Arguments}
    & "$PSScriptRoot/run_standalone_rl.ps1" -Run $Run -Python $Python -EntryScript $Entry -Command $Command -TrainingArguments $Arguments | Out-Null
}
try {
    Write-ControlEvent 'controller_start' @{pid=$PID;deadline=$BudgetDeadline}
    Wait-Validation 'mc-wide4'
    Assert-Time
    & $Python scripts/monte_carlo_rl.py prepare --run mc-wide16 --ref 59836c86f4c9ccf7e8d35ef7c94268e64c1a4ba9 `
        --start runs/standalone-rl/engine-bc-wide-v1/candidate_epoch_00016.npz --seed 37001 --hidden 512 `
        --bootstrap-games 0 --validation-pairings 128 --budget-deadline $BudgetDeadline
    if ($LASTEXITCODE -ne 0) { throw 'Second capacity candidate preparation failed.' }
    Launch-Job 'mc-wide16' 'scripts/monte_carlo_rl.py' 'train' @('--bootstrap-games','0','--max-rounds','0',
        '--hidden','512','--workers','1','--hours','2','--validation-pairings','128','--pairings','1200',
        '--budget-deadline',"$BudgetDeadline")
    Wait-Validation 'mc-wide16'

    # Resume from a completed journal entry, with at most one in-flight batch
    # discarded. Verify the exact owned process and its children before stopping.
    $rlBefore = Get-Content runs/standalone-rl/mc-ppo-v3/state.json -Raw | ConvertFrom-Json
    do {
        Assert-Time
        if (-not (Test-JobLive 'mc-ppo-v3')) { throw 'PPO is terminal; inspect it before any restart.' }
        Start-Sleep -Seconds 15
        $rlCurrent = Get-Content runs/standalone-rl/mc-ppo-v3/state.json -Raw | ConvertFrom-Json
    } while ($rlCurrent.round -le $rlBefore.round)
    if ($rlCurrent.phase -ne 'ppo' -or (Test-Path runs/standalone-rl/mc-ppo-v3/lock.json)) { throw 'PPO is already locked.' }
    $rlInfo = Get-Content runs/standalone-rl/mc-ppo-v3/process.json -Raw | ConvertFrom-Json
    $rlMain = Get-CimInstance Win32_Process -Filter "ProcessId = $($rlInfo.pid)"
    if (-not $rlMain -or $rlMain.CommandLine -notlike '*monte_carlo_rl.py*--run mc-ppo-v3*') {
        throw 'Owned PPO process was not verified.'
    }
    $rlChildren = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $($rlInfo.pid)" | Where-Object Name -eq 'python.exe')
    if ($rlChildren.Count -gt 3) { throw 'Unexpected PPO child count.' }
    Write-ControlEvent 'checkpoint_handoff' @{run='mc-ppo-v3';pid=$rlInfo.pid;state=$rlCurrent;children=@($rlChildren.ProcessId)}
    $rlChildren | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    Stop-Process -Id $rlInfo.pid -Force

    & $Python scripts/select_capacity_candidate.py --baseline mc-ppo-v3 --candidates mc-wide4 mc-wide16 `
        --output (Join-Path $rlControl 'decision.json')
    if ($LASTEXITCODE -ne 0) { throw 'Capacity decision failed; no training restart attempted.' }
    $rlDecision = Get-Content (Join-Path $rlControl 'decision.json') -Raw | ConvertFrom-Json
    $rlSelected = $rlDecision.selected.run
    if ($rlSelected -notin @('mc-ppo-v3','mc-wide4','mc-wide16')) { throw 'Unexpected selected run.' }

    $rlPlanning = Get-Content runs/standalone-rl/planning-confirm-c100/validation_summary.json -Raw | ConvertFrom-Json
    if ($rlPlanning.ci95[0] -gt 0.5 -and $rlPlanning.score -gt $rlDecision.selected.score) {
        & $Python scripts/evaluate_planning_rl.py lock --run planning-confirm-c100 --workers 3 --samples 4 --confidence 1.0 `
            --seed 8221690905823504610 --validation-pairings 128 --pairings 1200 --budget-deadline $BudgetDeadline
        if ($LASTEXITCODE -ne 0) { throw 'Planning lock failed.' }
        Launch-Job 'planning-confirm-c100' 'scripts/evaluate_planning_rl.py' 'test' @('--workers','3','--samples','4',
            '--confidence','1.0','--seed','8221690905823504610','--validation-pairings','128','--pairings','1200',
            '--budget-deadline',"$BudgetDeadline")
        Write-ControlEvent 'planning_final_started' $null
    } else {
        $rlRate = if ($rlSelected -eq 'mc-ppo-v3') { '0.0002' } else { '0.00005' }
        Launch-Job $rlSelected 'scripts/monte_carlo_rl.py' 'run' @('--bootstrap-games','0','--workers','3',
            '--hours','36','--train-samples','32','--curriculum-rounds','0','--anchor','0.01','--demo-weight','0.1',
            '--rate',$rlRate,'--validation-every','8','--validation-pairings','128','--pairings','1200',
            '--test-reserve-hours','12','--budget-deadline',"$BudgetDeadline")
        Write-ControlEvent 'three_worker_training_resumed' $rlSelected
    }
} catch {
    Write-ControlEvent 'controller_error' $_.Exception.Message
    throw
}
