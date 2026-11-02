# Supersedes the waiting CF-only queue: symmetry augmentation first, then paired-return training if needed.
$ErrorActionPreference = 'Stop'
$dqnRoot = Split-Path $PSScriptRoot -Parent
$dqnPython = 'C:\Users\lionl\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$dqnDeadline = [DateTime]::Parse('2026-11-03T22:40:49Z').ToUniversalTime()
$dqnCurrentRun = 'search-v3'
$dqnCurrentWorker = $null
$dqnCurrentRuntime = '.dqn-cache/harness/v5'
Set-Location -LiteralPath $dqnRoot

function Save-DqnNextState($phase, $status) {
    $dqnData = [pscustomobject]@{ phase=$phase; status=$status; controller_pid=$PID;
        worker_pid=$(if ($dqnCurrentWorker) { $dqnCurrentWorker.Id } else { $null });
        run=$dqnCurrentRun; runtime=$dqnCurrentRuntime;
        stdout=('runs/' + $dqnCurrentRun + '.out'); stderr=('runs/' + $dqnCurrentRun + '.err');
        result=('runs/double-dqn/' + $dqnCurrentRun + '/result.json');
        updated_utc=[DateTime]::UtcNow.ToString('o'); deadline_utc=$dqnDeadline.ToString('o') }
    $dqnData | ConvertTo-Json | Set-Content -LiteralPath .dqn-cache/next_experiment.json
    if ($phase -ne 'waiting_for_search') {
        $dqnData | ConvertTo-Json | Set-Content -LiteralPath .dqn-cache/active_experiment.json
    }
}

function Run-DqnChild($runName, $arguments) {
    if ([DateTime]::UtcNow -ge $dqnDeadline) { throw 'Original computing deadline reached' }
    $script:dqnCurrentRun = $runName
    $script:dqnCurrentWorker = Start-Process -FilePath $dqnPython -ArgumentList $arguments `
        -WorkingDirectory $dqnRoot -WindowStyle Hidden `
        -RedirectStandardOutput ('runs/' + $runName + '.out') `
        -RedirectStandardError ('runs/' + $runName + '.err') -PassThru
    $dqnChildStarted = $dqnCurrentWorker.StartTime.ToUniversalTime()
    Save-DqnNextState 'serial_research' 'running'
    while (-not $dqnCurrentWorker.HasExited) {
        if ([DateTime]::UtcNow -ge $dqnDeadline) {
            $dqnIdentity = Get-Process -Id $dqnCurrentWorker.Id -ErrorAction SilentlyContinue
            if ($dqnIdentity -and $dqnIdentity.StartTime.ToUniversalTime() -eq $dqnChildStarted) {
                Stop-Process -InputObject $dqnIdentity -Force
            }
            throw 'Original deadline reached; saved checkpoints and labels retained'
        }
        Start-Sleep -Seconds 5
        $dqnCurrentWorker.Refresh()
    }
    # The durable result is authoritative even if a detached shell loses its cached exit code.
    if (-not (Test-Path -LiteralPath ('runs/double-dqn/' + $runName + '/result.json'))) {
        throw ('Missing result after ' + $runName + '; inspect its preserved stdout/stderr')
    }
    $script:dqnCurrentWorker = $null
}

try {
    Save-DqnNextState 'waiting_for_search' 'waiting'
    # Bind the specific already-running processes before waiting; never spawn a second search worker.
    $dqnSearchProcesses = @(Get-Process -Id 22260,25888 -ErrorAction SilentlyContinue)
    foreach ($dqnProcess in $dqnSearchProcesses) {
        while (-not $dqnProcess.HasExited) {
            if ([DateTime]::UtcNow -ge $dqnDeadline) { throw 'Original deadline reached while search was running' }
            Start-Sleep -Seconds 5
            $dqnProcess.Refresh()
        }
    }
    $dqnSearch = Get-Content -LiteralPath runs/double-dqn/search-v3/result.json -Raw | ConvertFrom-Json
    if ($dqnSearch.confirmation.lower95 -gt 0.5) {
        Save-DqnNextState 'review_search_for_final_lock' 'awaiting_evidence_review'
        exit 0
    }
    $dqnBundle = Join-Path $dqnRoot '.dqn-cache/harness/v5'
    $dqnManifest = Get-Content -LiteralPath (Join-Path $dqnBundle 'source_manifest.json') -Raw | ConvertFrom-Json
    foreach ($dqnEntry in $dqnManifest.psobject.Properties) {
        $dqnActual = (Get-FileHash -LiteralPath (Join-Path $dqnBundle $dqnEntry.Name) -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($dqnActual -ne $dqnEntry.Value) { throw ('Runtime hash changed: ' + $dqnEntry.Name) }
    }
    Run-DqnChild 'symmetry-v5' @('-u','.dqn-cache/harness/v5/scripts/dqn_symmetry_trial.py',
        '--run','symmetry-v5','--epochs','60','--screen-pairs','64','--confirm-pairs','128','--hours','4')
    $dqnSymmetry = Get-Content -LiteralPath runs/double-dqn/symmetry-v5/result.json -Raw | ConvertFrom-Json
    if ($dqnSymmetry.confirmation.lower95 -gt 0.5) {
        Save-DqnNextState 'review_symmetry_for_final_lock' 'awaiting_evidence_review'
        exit 0
    }
    $dqnCurrentRuntime = '.dqn-cache/harness/v4'
    $dqnBundle = Join-Path $dqnRoot $dqnCurrentRuntime
    $dqnManifest = Get-Content -LiteralPath (Join-Path $dqnBundle 'source_manifest.json') -Raw | ConvertFrom-Json
    foreach ($dqnEntry in $dqnManifest.psobject.Properties) {
        $dqnActual = (Get-FileHash -LiteralPath (Join-Path $dqnBundle $dqnEntry.Name) -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($dqnActual -ne $dqnEntry.Value) { throw ('Runtime hash changed: ' + $dqnEntry.Name) }
    }
    $dqnScript = '.dqn-cache/harness/v4/scripts/counterfactual_rl.py'
    Run-DqnChild 'cf-canary-v4' @('-u',$dqnScript,'--run','cf-canary-v4','--collection-canary',
        '--groups','4','--max-groups','4','--samples','32')
    $dqnCanary = Get-Content -LiteralPath runs/double-dqn/cf-canary-v4/result.json -Raw | ConvertFrom-Json
    if ($dqnCanary.status -ne 'canary_complete' -or $dqnCanary.matched_controls -ne $dqnCanary.groups) {
        throw 'Original-choice frozen-engine replay canary failed; no training started'
    }
    Run-DqnChild 'counterfactual-v4' @('-u',$dqnScript,'--run','counterfactual-v4',
        '--rounds','6','--groups','300','--max-groups','1200','--min-signals','32',
        '--samples','32','--epochs','30','--screen-pairs','64','--confirm-pairs','128','--hours','8')
    Save-DqnNextState 'paired_return_result_ready' 'complete'
} catch {
    Save-DqnNextState 'needs_attention' $_.Exception.Message
    throw
}
