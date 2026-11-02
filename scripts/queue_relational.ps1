# A serial successor: apply the registered CF allocation rule, finish its confirmation, then try the encoder.
# This script is itself snapshotted before launch. It never imports or modifies a live runtime.
$ErrorActionPreference = 'Stop'
$dqnRoot = (Get-Content -LiteralPath (Join-Path $PSScriptRoot '../workspace_root.txt') -Raw).Trim()
$dqnPython = 'C:\Users\lionl\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$dqnBundle = Split-Path $PSScriptRoot -Parent
$dqnDeadline = [DateTime]::Parse('2026-11-03T22:40:49Z').ToUniversalTime()
$dqnWorker = $null
$dqnRun = 'counterfactual-v4'
Set-Location -LiteralPath $dqnRoot

function Save-QueueState($phase, $status) {
    $dqnData = [ordered]@{ phase=$phase; status=$status; controller_pid=$PID;
        worker_pid=$(if ($dqnWorker) { $dqnWorker.Id } else { $null }); run=$dqnRun;
        runtime=$dqnBundle; updated_utc=[DateTime]::UtcNow.ToString('o');
        deadline_utc=$dqnDeadline.ToString('o') }
    $dqnData | ConvertTo-Json | Set-Content -LiteralPath .dqn-cache/relational_queue_state.json.tmp
    Move-Item -LiteralPath .dqn-cache/relational_queue_state.json.tmp -Destination .dqn-cache/relational_queue_state.json -Force
    Copy-Item -LiteralPath .dqn-cache/relational_queue_state.json -Destination .dqn-cache/next_experiment.json -Force
    if ($phase -ne 'waiting_for_cf') {
        Copy-Item -LiteralPath .dqn-cache/relational_queue_state.json -Destination .dqn-cache/active_experiment.json -Force
    }
}

function Get-VerifiedPredecessor($identity) {
    $dqnInfo = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $identity.pid)
    if (-not $dqnInfo) { return $null }
    # ConvertFrom-Json can parse ISO strings as DateTime; compare instants, not string display formats.
    if ($dqnInfo.CreationDate.ToUniversalTime() -ne ([DateTime]$identity.started_utc).ToUniversalTime() -or
        $dqnInfo.CommandLine -notlike ('*' + $identity.command_contains + '*')) {
        throw ('Predecessor PID identity changed: ' + $identity.pid)
    }
    return Get-Process -Id $identity.pid
}

function Run-Child($runName, $scriptName, $resultPath, $limit) {
    if ([DateTime]::UtcNow -ge $limit) { throw 'Original allocated deadline reached' }
    $script:dqnRun = $runName
    $script:dqnWorker = Start-Process -FilePath $dqnPython -ArgumentList @('-u',(Join-Path $dqnBundle $scriptName)) `
        -WorkingDirectory $dqnRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput ('runs/' + $runName + '-followup.out') `
        -RedirectStandardError ('runs/' + $runName + '-followup.err')
    $dqnStarted = $dqnWorker.StartTime.ToUniversalTime()
    Save-QueueState 'serial_followup' 'running'
    while (-not $dqnWorker.HasExited) {
        if ([DateTime]::UtcNow -ge $limit) {
            $dqnInfo = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $dqnWorker.Id)
            $dqnLiveProcess = Get-Process -Id $dqnWorker.Id -ErrorAction SilentlyContinue
            if ($dqnInfo -and $dqnLiveProcess -and $dqnLiveProcess.StartTime.ToUniversalTime() -eq $dqnStarted -and
                $dqnInfo.CommandLine.Contains((Join-Path $dqnBundle $scriptName))) {
                Stop-Process -InputObject $dqnLiveProcess -Force
            }
            throw 'Allocated deadline reached; checkpoints and raw logs retained'
        }
        Start-Sleep -Seconds 5
        $dqnWorker.Refresh()
    }
    if (-not (Test-Path -LiteralPath $resultPath)) { throw ('Missing completed result: ' + $resultPath) }
    $script:dqnWorker = $null
}

try {
    $dqnManifest = Get-Content -LiteralPath (Join-Path $dqnBundle 'source_manifest.json') -Raw | ConvertFrom-Json
    foreach ($dqnEntry in $dqnManifest.psobject.Properties) {
        if ((Get-FileHash -LiteralPath (Join-Path $dqnBundle $dqnEntry.Name)).Hash.ToLowerInvariant() -ne $dqnEntry.Value) {
            throw ('Runtime source changed: ' + $dqnEntry.Name)
        }
    }
    $dqnQueuePlan = Get-Content -LiteralPath runs/double-dqn/relational-v1/queue_plan.json -Raw | ConvertFrom-Json
    $dqnPriorWorker = Get-VerifiedPredecessor $dqnQueuePlan.predecessor_worker
    $dqnPriorController = Get-VerifiedPredecessor $dqnQueuePlan.predecessor_controller
    Save-QueueState 'waiting_for_cf' 'waiting'
    while ($dqnPriorWorker -and -not $dqnPriorWorker.HasExited) {
        if ([DateTime]::UtcNow -ge $dqnDeadline) { throw 'Original deadline reached while waiting for CF' }
        $dqnState = Get-Content -LiteralPath runs/double-dqn/counterfactual-v4/state.json -Raw | ConvertFrom-Json
        $dqnRounds = @(Get-Content -LiteralPath runs/double-dqn/counterfactual-v4/rounds.jsonl | ForEach-Object { $_ | ConvertFrom-Json })
        $dqnAllocation = Get-Content -LiteralPath runs/double-dqn/counterfactual-v4/allocation_plan.json -Raw | ConvertFrom-Json
        if ($dqnState.round -ge 3 -and $dqnRounds.Count -ge 3 -and $dqnState.best_checkpoint -eq 'initial.npz' -and
            -not ($dqnRounds | Where-Object { $_.score -gt $dqnAllocation.control_score })) {
            $dqnCurrentIdentity = Get-VerifiedPredecessor $dqnQueuePlan.predecessor_worker
            if ($dqnCurrentIdentity) {
                'Registered adaptive allocation rule after three non-improving complete candidates; preserve checkpoints.' |
                    Set-Content -LiteralPath runs/double-dqn/counterfactual-v4/STOP
            }
        }
        Start-Sleep -Seconds 10
        $dqnPriorWorker.Refresh()
    }
    while ($dqnPriorController -and -not $dqnPriorController.HasExited) {
        if ([DateTime]::UtcNow -ge $dqnDeadline) { throw 'Original deadline reached while waiting for prior controller' }
        Start-Sleep -Seconds 5
        $dqnPriorController.Refresh()
    }
    $dqnPriorResult = Get-Content -LiteralPath runs/double-dqn/counterfactual-v4/result.json -Raw | ConvertFrom-Json
    $dqnConfirmation = $dqnPriorResult.confirmation
    if (-not $dqnConfirmation) {
        $dqnRun = 'cf-confirmation'
        Run-Child 'cf-confirmation' 'scripts/dqn_cf_confirm.py' `
            'runs/double-dqn/counterfactual-v4/allocation_confirmation.json' `
            ([DateTimeOffset]::FromUnixTimeSeconds(1793681913).UtcDateTime)
        $dqnConfirmation = (Get-Content -LiteralPath runs/double-dqn/counterfactual-v4/allocation_confirmation.json -Raw | ConvertFrom-Json).confirmation
    }
    if ($dqnConfirmation.lower95 -gt 0.5) {
        Save-QueueState 'review_cf_for_final_lock' 'awaiting_evidence_review'
        exit 0
    }
    Run-Child 'relational-v1' 'scripts/dqn_relational_trial.py' 'runs/double-dqn/relational-v1/result.json' $dqnDeadline
    Save-QueueState 'relational_result_ready' 'complete'
} catch {
    Save-QueueState 'needs_attention' $_.Exception.Message
    throw
}
