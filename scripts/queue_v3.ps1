$ErrorActionPreference = 'Stop'
$dqnRoot = Split-Path $PSScriptRoot -Parent
$dqnPython = 'C:\Users\lionl\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$dqnDeadline = [DateTime]::Parse('2026-11-03T22:40:49Z').ToUniversalTime()
Set-Location -LiteralPath $dqnRoot

function Save-DqnState($phase, $workerPid, $status) {
    [pscustomobject]@{ phase=$phase; controller_pid=$PID; worker_pid=$workerPid; status=$status;
        updated_utc=[DateTime]::UtcNow.ToString('o'); run='search-v3';
        stdout='runs/search-v3.out'; stderr='runs/search-v3.err';
        runtime='.dqn-cache/harness/v3'; result='runs/double-dqn/search-v3/result.json'
    } | ConvertTo-Json | Set-Content -LiteralPath .dqn-cache/active_experiment.json
}

try {
    Save-DqnState 'controlled_refinement' $null 'waiting'
    while (-not (Test-Path -LiteralPath runs/double-dqn/refine-v3/result.json)) {
        if ([DateTime]::UtcNow -ge $dqnDeadline) { throw 'Budget deadline reached before the next experiment' }
        Start-Sleep -Seconds 15
    }
    Save-DqnState 'preflight_checks' $null 'running'
    & $dqnPython -m unittest discover tests > runs/v3-tests.out 2>&1
    if ($LASTEXITCODE -ne 0) { throw 'Unit tests failed; see runs/v3-tests.out' }
    & $dqnPython scripts/check_pvpoke.py > runs/v3-pvpoke.out 2>&1
    if ($LASTEXITCODE -ne 0) { throw 'PvPoke checks failed; see runs/v3-pvpoke.out' }
    $dqnWorker = Start-Process -FilePath $dqnPython -ArgumentList @('-u',
        '.dqn-cache/harness/v3/scripts/rl_search_trial.py','--run','search-v3',
        '--pairs','64','--confirm-pairs','128','--samples','8','16') `
        -WorkingDirectory $dqnRoot -WindowStyle Hidden `
        -RedirectStandardOutput runs/search-v3.out -RedirectStandardError runs/search-v3.err -PassThru
    Save-DqnState 'independent_full_game_search' $dqnWorker.Id 'running'
    while (-not $dqnWorker.HasExited) {
        if ([DateTime]::UtcNow -ge $dqnDeadline) {
            Stop-Process -Id $dqnWorker.Id -Force
            throw 'Budget deadline reached; partial evaluation logs retained'
        }
        Start-Sleep -Seconds 5
        $dqnWorker.Refresh()
    }
    if ($dqnWorker.ExitCode -ne 0) { throw ('Search trial exited ' + $dqnWorker.ExitCode) }
    Save-DqnState 'search_result_ready' $null 'complete'
} catch {
    Save-DqnState 'needs_attention' $null $_.Exception.Message
    throw
}
