param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$dqnRoot = [IO.Path]::GetFullPath((Get-Location).Path)
$dqnRun = Join-Path $dqnRoot 'runs/double-dqn/continue-v1'
$dqnPlanPath = Join-Path $dqnRun 'plan.json'
if ((Get-FileHash -LiteralPath $dqnPlanPath).Hash.ToLowerInvariant() -ne '157f94a88e075598524518a2f1a9bc3cb7f0c1e6e1f2c2f4d5b0a8bc49b5d1f3') { throw 'Registered plan changed' }
$dqnPlan = Get-Content -LiteralPath $dqnPlanPath -Raw | ConvertFrom-Json
$dqnDeadline = [DateTimeOffset]::FromUnixTimeSeconds([long]$dqnPlan.absolute_deadline_unix).UtcDateTime
$dqnActivation = Get-Content -LiteralPath (Join-Path $dqnRun 'activation.json') -Raw | ConvertFrom-Json
$dqnRuntime = Join-Path $dqnRoot $dqnActivation.runtime
$dqnManifestPath = Join-Path $dqnRuntime 'source_manifest.json'
if ((Get-FileHash -LiteralPath $dqnManifestPath).Hash.ToLowerInvariant() -ne $dqnActivation.source_manifest_sha256) { throw 'Runtime manifest changed' }
$dqnManifest = Get-Content -LiteralPath $dqnManifestPath -Raw | ConvertFrom-Json
foreach ($dqnEntry in $dqnManifest.psobject.Properties) {
    if ((Get-FileHash -LiteralPath (Join-Path $dqnRuntime $dqnEntry.Name)).Hash.ToLowerInvariant() -ne $dqnEntry.Value) { throw ('Runtime changed: ' + $dqnEntry.Name) }
}
if ((Get-FileHash -LiteralPath $PSCommandPath).Hash.ToLowerInvariant() -ne $dqnActivation.guard_sha256) { throw 'Guard source changed' }
$dqnPython = 'C:\Users\lionl\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$dqnScript = Join-Path $dqnRuntime 'scripts/dqn_continue.py'
$dqnLaunchPath = Join-Path $dqnRun 'launch.json'
$dqnStatePath = Join-Path $dqnRun 'controller_state.json'

function Write-DqnJson($dqnPath, $dqnValue) {
    $dqnTempPath = $dqnPath + '.tmp'
    $dqnValue | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $dqnTempPath -Encoding utf8
    Move-Item -LiteralPath $dqnTempPath -Destination $dqnPath -Force
}
function Test-DqnIdentity($dqnProcess, $dqnExpected) {
    return ($dqnProcess -and $dqnProcess.Path -eq $dqnPython -and
        [math]::Abs(($dqnProcess.StartTime.ToUniversalTime() - ([DateTime]$dqnExpected.worker_started_utc).ToUniversalTime()).TotalSeconds) -lt 1)
}

$dqnLease = [IO.File]::Open((Join-Path $dqnRun 'controller.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
try {
    $dqnPrior = if (Test-Path -LiteralPath $dqnLaunchPath) { Get-Content -LiteralPath $dqnLaunchPath -Raw | ConvertFrom-Json } else { $null }
    $dqnAttach = $null
    if ($dqnPrior -and $dqnPrior.worker_pid) {
        $dqnExisting = Get-Process -Id $dqnPrior.worker_pid -ErrorAction SilentlyContinue
        if (Test-DqnIdentity $dqnExisting $dqnPrior) {
            if ($dqnPrior.runtime -ne $dqnRuntime) { throw 'Live worker belongs to another runtime' }
            $dqnAttach = $dqnExisting
        }
    }
    if (Test-Path -LiteralPath (Join-Path $dqnRun 'verdict.json')) { Write-Output 'Completed benchmark already exists; no worker launched'; exit 0 }
    if ([DateTime]::UtcNow -ge $dqnDeadline -or (Test-Path -LiteralPath (Join-Path $dqnRun 'STOP'))) {
        if (!$CheckOnly -and (Test-DqnIdentity $dqnAttach $dqnPrior)) { Stop-Process -Id $dqnAttach.Id -ErrorAction Stop }
        throw 'Authorized deadline or STOP reached; no restart or extension'
    }
    if ($CheckOnly) { @{eligible=$true; numerical_start=$false; attach_existing_worker=[bool]$dqnAttach; deadline_utc=$dqnDeadline.ToString('o'); runtime=$dqnRuntime} | ConvertTo-Json; exit 0 }
    $dqnAttempt = if ($dqnPrior) { [int]$dqnPrior.attempt } else { 0 }
    $dqnControllerStarted = (Get-Process -Id $PID).StartTime.ToUniversalTime().ToString('o')
    for ($dqnRetry = 0; $dqnRetry -lt 3; $dqnRetry++) {
        if ([DateTime]::UtcNow -ge $dqnDeadline -or (Test-Path -LiteralPath (Join-Path $dqnRun 'STOP'))) { throw 'Deadline or STOP; no worker start' }
        if ($dqnAttach) {
            $dqnWorker = $dqnAttach
            $dqnOut = $dqnPrior.stdout
            $dqnErr = $dqnPrior.stderr
            $dqnAttach = $null
        } else {
            $dqnAttempt++
            $dqnOut = 'runs/continue-v1-worker-attempt-' + $dqnAttempt + '.out'
            $dqnErr = 'runs/continue-v1-worker-attempt-' + $dqnAttempt + '.err'
            $dqnWorker = Start-Process -FilePath $dqnPython -ArgumentList @('-u', ('"' + $dqnScript + '"')) -WorkingDirectory $dqnRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $dqnOut -RedirectStandardError $dqnErr
        }
        $dqnWorkerStarted = $dqnWorker.StartTime.ToUniversalTime().ToString('o')
        $dqnLaunch = [ordered]@{attempt=$dqnAttempt; worker_pid=$dqnWorker.Id; worker_started_utc=$dqnWorkerStarted; controller_pid=$PID; controller_started_utc=$dqnControllerStarted; runtime=$dqnRuntime; deadline_utc=$dqnDeadline.ToString('o'); stdout=$dqnOut; stderr=$dqnErr}
        Write-DqnJson $dqnLaunchPath $dqnLaunch
        $dqnActual = Get-Process -Id $dqnWorker.Id -ErrorAction Stop
        if (!(Test-DqnIdentity $dqnActual $dqnLaunch)) { throw 'New worker identity mismatch' }
        $dqnActual.PriorityClass = [Diagnostics.ProcessPriorityClass]::BelowNormal
        if ($dqnActual.PriorityClass -ne [Diagnostics.ProcessPriorityClass]::BelowNormal) { throw 'Worker priority was not lowered' }
        $dqnState = [ordered]@{phase='running'; controller_pid=$PID; controller_started_utc=$dqnControllerStarted; worker_pid=$dqnWorker.Id; worker_started_utc=$dqnWorkerStarted; attempt=$dqnAttempt; deadline_utc=$dqnDeadline.ToString('o'); priority='BelowNormal'; stdout=$dqnOut; stderr=$dqnErr; updated_utc=[DateTime]::UtcNow.ToString('o')}
        Write-DqnJson $dqnStatePath $dqnState
        $dqnStopped = $false
        while (!$dqnWorker.WaitForExit(5000)) {
            if ([DateTime]::UtcNow -ge $dqnDeadline -or (Test-Path -LiteralPath (Join-Path $dqnRun 'STOP'))) {
                $dqnActual = Get-Process -Id $dqnWorker.Id -ErrorAction SilentlyContinue
                if (Test-DqnIdentity $dqnActual $dqnLaunch) { Stop-Process -Id $dqnActual.Id -ErrorAction Stop }
                $dqnStopped = $true
                $dqnWorker.WaitForExit()
                break
            }
        }
        $dqnState.worker_pid = $null
        $dqnState.updated_utc = [DateTime]::UtcNow.ToString('o')
        $dqnState['exit_code'] = $dqnWorker.ExitCode
        if (Test-Path -LiteralPath (Join-Path $dqnRun 'verdict.json')) {
            $dqnState.phase = 'complete'
            Write-DqnJson $dqnStatePath $dqnState
            exit 0
        }
        if ($dqnStopped) {
            $dqnState.phase = 'stopped_with_checkpoints'
            Write-DqnJson $dqnStatePath $dqnState
            exit 2
        }
        $dqnState.phase = 'worker_exited_before_verdict'
        Write-DqnJson $dqnStatePath $dqnState
        Write-Output ('Worker attempt ' + $dqnAttempt + ' exited; logs retained. Same checkpoints and deadlines will resume.')
        Start-Sleep -Seconds 10
    }
    throw 'Three serial attempts failed; inspect preserved stderr before recovery'
} finally {
    $dqnLease.Dispose()
}
