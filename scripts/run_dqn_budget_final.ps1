# Serial final benchmark; own experiment only. Source snapshot and all deadlines are immutable.
param([switch]$CheckOnly)
$ErrorActionPreference='Stop'
$dqnRoot=(Get-Content (Join-Path $PSScriptRoot '../workspace_root.txt') -Raw).Trim()
Set-Location -LiteralPath $dqnRoot
$dqnQueuePath='runs/double-dqn/budget-finalization-v1/queue.json'
$dqnQueue=Get-Content $dqnQueuePath -Raw | ConvertFrom-Json
$dqnDeadline=[DateTime]::Parse('2026-11-03T22:40:49Z').ToUniversalTime()
$dqnCutoff=[DateTime]::Parse('2026-11-03T09:45:00Z').ToUniversalTime()
$dqnStatePath='runs/double-dqn/budget-finalization-v1/controller_state.json'
$dqnRuntime=Join-Path $dqnRoot '.dqn-cache/harness/final-budget-v1'
$dqnScript=Join-Path $dqnRuntime 'scripts/dqn_budget_final.py'
$dqnPython='C:\Users\lionl\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'

function Matching-Process($identity) {
    $process=Get-Process -Id $identity.pid -ErrorAction SilentlyContinue
    if ($process -and ($process.StartTime.ToUniversalTime() -ne ([DateTime]$identity.started_utc).ToUniversalTime() -or
        $process.Path -ne $identity.path)) { throw ('Process identity changed; no action: '+$identity.pid) }
    return $process
}
function Verify-Sources {
    if ((Get-FileHash $PSCommandPath).Hash.ToLowerInvariant() -ne $dqnQueue.guard_sha256) {
        throw 'Immutable final guard changed'
    }
    $manifest=Get-Content (Join-Path $dqnRuntime 'source_manifest.json') -Raw | ConvertFrom-Json
    if ((Get-FileHash (Join-Path $dqnRuntime 'source_manifest.json')).Hash.ToLowerInvariant() -ne $dqnQueue.source_manifest_sha256) {
        throw 'Numerical source manifest changed'
    }
    foreach ($entry in $manifest.psobject.Properties) {
        if ((Get-FileHash (Join-Path $dqnRuntime $entry.Name)).Hash.ToLowerInvariant() -ne $entry.Value) {
            throw ('Immutable numerical source changed: '+$entry.Name)
        }
    }
    if ((Get-FileHash 'runs/double-dqn/budget-finalization-v1/plan.json').Hash.ToLowerInvariant() -ne $dqnQueue.plan_sha256) {
        throw 'Registered budget allocation changed'
    }
}
Verify-Sources
$dqnPredecessorWorker=Matching-Process $dqnQueue.research_worker
$dqnPredecessorGuard=Matching-Process $dqnQueue.research_guard
if ($CheckOnly) {
    @{sources_verified=$true;worker_live=[bool]$dqnPredecessorWorker;guard_live=[bool]$dqnPredecessorGuard;
      numerical_start=$false;research_cutoff=$dqnCutoff.ToString('o');deadline=$dqnDeadline.ToString('o')} | ConvertTo-Json
    exit 0
}
if (Test-Path .dqn-cache/final_controller.json) {
    $previous=Get-Content .dqn-cache/final_controller.json -Raw | ConvertFrom-Json
    if (Get-Process -Id $previous.controller_pid -ErrorAction SilentlyContinue) { throw 'Final controller already live; refuse duplicate' }
    if ($previous.worker_pid -and (Get-Process -Id $previous.worker_pid -ErrorAction SilentlyContinue)) {
        throw 'A prior final worker is still live; inspect its identity and preserve the same checkpoint'
    }
}
$dqnState=if (Test-Path $dqnStatePath) { Get-Content $dqnStatePath -Raw | ConvertFrom-Json -AsHashtable } else {
    @{launch_number=0;phase='waiting_for_teacher32';research_stop_requested=$false}
}
$dqnState.controller_pid=$PID
$dqnState.controller_started_utc=(Get-Process -Id $PID).StartTime.ToUniversalTime().ToString('o')
$dqnState.absolute_deadline_utc=$dqnDeadline.ToString('o')
$dqnState.runtime=$dqnRuntime
function Save-State {
    $dqnState.updated_utc=[DateTime]::UtcNow.ToString('o')
    $dqnState | ConvertTo-Json -Depth 8 | Set-Content ($dqnStatePath+'.tmp')
    Move-Item -LiteralPath ($dqnStatePath+'.tmp') -Destination $dqnStatePath -Force
    Copy-Item -LiteralPath $dqnStatePath -Destination .dqn-cache/final_controller.json -Force
}
Add-Type -TypeDefinition 'using System.Runtime.InteropServices; public static class DqnBudgetAwake { [DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint flags); }'
[DqnBudgetAwake]::SetThreadExecutionState([uint32]2147483649) | Out-Null
try {
    Save-State
    while ($true) {
        if ([DateTime]::UtcNow -ge $dqnDeadline) { throw 'Original overall deadline reached; no start or extension' }
        $dqnPredecessorWorker=Matching-Process $dqnQueue.research_worker
        $dqnPredecessorGuard=Matching-Process $dqnQueue.research_guard
        if (-not $dqnPredecessorWorker -and -not $dqnPredecessorGuard) { break }
        if ([DateTime]::UtcNow -ge $dqnCutoff -and $dqnPredecessorWorker) {
            'Registered research cutoff; preserve checkpoints for the single budget-final benchmark.' |
                Set-Content runs/double-dqn/teacher32-v1/STOP
            # Recheck the exact own process identity immediately before the authorized allocation stop.
            $dqnPredecessorWorker=Matching-Process $dqnQueue.research_worker
            if ($dqnPredecessorWorker) { Stop-Process -InputObject $dqnPredecessorWorker -Force }
            $dqnState.research_stop_requested=$true
            $dqnState.research_stop_reason='Registered09:45UTC cutoff; incomplete teacher result is ineligible'
            Save-State
        }
        $nextBoundary=if ([DateTime]::UtcNow -lt $dqnCutoff) { $dqnCutoff } else { $dqnDeadline }
        Start-Sleep -Milliseconds ([int][Math]::Max(1,[Math]::Min(5000,($nextBoundary-[DateTime]::UtcNow).TotalMilliseconds)))
    }
    foreach ($phase in @('canary','production')) {
        if ([DateTime]::UtcNow -ge $dqnDeadline) { throw 'Original deadline reached before next phase' }
        Verify-Sources
        $dqnState.launch_number=[int]$dqnState.launch_number+1
        $dqnState.phase=$phase
        $dqnOut='runs/budget-final-'+$phase+'-attempt-'+$dqnState.launch_number+'.out'
        $dqnErr='runs/budget-final-'+$phase+'-attempt-'+$dqnState.launch_number+'.err'
        $arguments=@('-u',('"'+$dqnScript+'"'))
        if ($phase -eq 'canary') { $arguments+='--canary' }
        $dqnChild=Start-Process -FilePath $dqnPython -ArgumentList $arguments -WorkingDirectory $dqnRoot `
            -WindowStyle Hidden -PassThru -RedirectStandardOutput $dqnOut -RedirectStandardError $dqnErr
        $dqnIdentity=@{pid=$dqnChild.Id;started_utc=$dqnChild.StartTime.ToUniversalTime().ToString('o');path=$dqnPython}
        $dqnState.worker_pid=$dqnChild.Id
        $dqnState.worker_started_utc=$dqnIdentity.started_utc
        $dqnState.stdout=$dqnOut
        $dqnState.stderr=$dqnErr
        Save-State
        Copy-Item -LiteralPath $dqnStatePath -Destination .dqn-cache/active_experiment.json -Force
        while (-not $dqnChild.HasExited) {
            if ([DateTime]::UtcNow -ge $dqnDeadline -or (Test-Path runs/double-dqn/budget-finalization-v1/STOP)) {
                $dqnLive=Matching-Process $dqnIdentity
                if ($dqnLive) { Stop-Process -InputObject $dqnLive -Force }
                throw 'Original deadline or STOP; partial pairings and locked policy retained'
            }
            Start-Sleep -Milliseconds ([int][Math]::Max(1,[Math]::Min(5000,($dqnDeadline-[DateTime]::UtcNow).TotalMilliseconds)))
            $dqnChild.Refresh()
        }
        if ($dqnChild.ExitCode -ne 0) { throw ('Final '+$phase+' failed; preserve logs and resume same selection: '+$dqnChild.ExitCode) }
        $dqnState.worker_pid=$null
        $dqnState.phase=$phase+'_complete'
        Save-State
    }
    $dqnState.phase='complete'
    Save-State
} catch {
    $dqnState.phase='needs_attention'
    $dqnState.error=$_.Exception.Message
    Save-State
    throw
} finally { [DqnBudgetAwake]::SetThreadExecutionState([uint32]2147483648) | Out-Null }
