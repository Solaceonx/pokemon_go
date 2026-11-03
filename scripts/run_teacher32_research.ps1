# Launch one already declared research trial. No waiting queue and no concurrent numerical worker.
param([Parameter(Mandatory=$true)][ValidateSet('teacher32-v1')][string]$Run,
      [switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$dqnRoot = (Get-Content (Join-Path $PSScriptRoot '../workspace_root.txt') -Raw).Trim()
Set-Location -LiteralPath $dqnRoot
$dqnPython = 'C:\Users\lionl\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$dqnGlobalDeadline = [DateTime]::Parse('2026-11-03T22:40:49Z').ToUniversalTime()
$dqnRunPath = Join-Path $dqnRoot ('runs/double-dqn/' + $Run)
$dqnRuntime = Join-Path $dqnRoot ('.dqn-cache/harness/' + $Run)
$dqnScript = Join-Path $dqnRuntime 'scripts/dqn_teacher32_trial.py'

# Refuse a start while either handle in this experiment's active pointer still exists. Never touch it.
$dqnActive = Get-Content .dqn-cache/active_experiment.json -Raw | ConvertFrom-Json
foreach ($dqnId in @($dqnActive.worker_pid,$dqnActive.controller_pid)) {
    if ($dqnId -and (Get-Process -Id $dqnId -ErrorAction SilentlyContinue)) {
        if ($CheckOnly) { @{eligible=$false;reason='Existing experiment process remains live';pid=$dqnId} | ConvertTo-Json; exit 0 }
        throw ('Existing experiment process remains live: ' + $dqnId)
    }
}
if (Test-Path runs/double-dqn/final_test_lock.json) { throw 'Final policy is already locked' }
if (Test-Path (Join-Path $dqnRunPath 'result.json')) { throw 'This trial already completed; review its evidence' }
if ([DateTime]::UtcNow -ge $dqnGlobalDeadline) { throw 'Original overall deadline reached' }
$dqnParents = @('relational-v1','residual-v1','calibration-v1')
foreach ($dqnParent in $dqnParents) {
    $dqnResult = Get-Content ('runs/double-dqn/' + $dqnParent + '/result.json') -Raw | ConvertFrom-Json
    if ($dqnResult.confirmation.pairs -ne 128 -or $dqnResult.confirmation.samples -ne 32 -or
        $dqnResult.confirmation.split -ne 'validation' -or $null -eq $dqnResult.confirmation.lower95) {
        throw ('Missing complete parent confirmation: ' + $dqnParent)
    }
    if ($dqnResult.confirmation.lower95 -gt 0.5) { throw ('Review promising parent for final evidence: ' + $dqnParent) }
}
$dqnManifestPath = Join-Path $dqnRuntime 'source_manifest.json'
$dqnManifest = Get-Content $dqnManifestPath -Raw | ConvertFrom-Json
$dqnReceipt = Get-Content (Join-Path $dqnRunPath 'source_manifest.json') -Raw | ConvertFrom-Json
if (@($dqnManifest.psobject.Properties).Count -ne @($dqnReceipt.psobject.Properties).Count) { throw 'Source receipt size mismatch' }
foreach ($dqnEntry in $dqnManifest.psobject.Properties) {
    if ($dqnReceipt.($dqnEntry.Name) -ne $dqnEntry.Value -or
        (Get-FileHash (Join-Path $dqnRuntime $dqnEntry.Name)).Hash.ToLowerInvariant() -ne $dqnEntry.Value) {
        throw ('Immutable source mismatch: ' + $dqnEntry.Name)
    }
}
$dqnLaunchPath = Join-Path $dqnRunPath 'launch.json'
$dqnPriorLaunch = if (Test-Path $dqnLaunchPath) { Get-Content $dqnLaunchPath -Raw | ConvertFrom-Json } else { $null }
$dqnLimit = [DateTime]::UtcNow.AddHours(6)
if ($dqnGlobalDeadline -lt $dqnLimit) { $dqnLimit = $dqnGlobalDeadline }
if ($dqnPriorLaunch) {
    $dqnOriginalLimit = ([DateTime]$dqnPriorLaunch.allocated_deadline_utc).ToUniversalTime()
    if ($dqnOriginalLimit -lt $dqnLimit) { $dqnLimit = $dqnOriginalLimit }
}
if (Test-Path (Join-Path $dqnRunPath 'state.json')) {
    $dqnSavedState = Get-Content (Join-Path $dqnRunPath 'state.json') -Raw | ConvertFrom-Json
    $dqnSavedLimit = [DateTime]::UnixEpoch.AddSeconds([double]$dqnSavedState.deadline_unix)
    if ($dqnSavedLimit -lt $dqnLimit) { $dqnLimit = $dqnSavedLimit }
}
if ([DateTime]::UtcNow -ge $dqnLimit) { throw 'Original trial allocation reached; no extension' }
if ($CheckOnly) { @{eligible=$true;run=$Run;deadline_utc=$dqnLimit.ToString('o')} | ConvertTo-Json; exit 0 }
$dqnAttempt = if ($dqnPriorLaunch) { [int]$dqnPriorLaunch.attempt + 1 } else { 1 }
$dqnOut = 'runs/' + $Run + '-attempt-' + $dqnAttempt + '.out'
$dqnErr = 'runs/' + $Run + '-attempt-' + $dqnAttempt + '.err'
$dqnWorker = Start-Process -FilePath $dqnPython -ArgumentList @('-u',('"' + $dqnScript + '"')) `
    -WorkingDirectory $dqnRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $dqnOut -RedirectStandardError $dqnErr
$dqnStarted = $dqnWorker.StartTime.ToUniversalTime()
$dqnIdentity = [ordered]@{run=$Run;phase='research_running';controller_pid=$PID;worker_pid=$dqnWorker.Id;
    worker_started_utc=$dqnStarted.ToString('o');runtime=$dqnRuntime;attempt=$dqnAttempt;
    allocated_deadline_utc=$dqnLimit.ToString('o');absolute_deadline_utc=$dqnGlobalDeadline.ToString('o');
    stdout=$dqnOut;stderr=$dqnErr;source_manifest_sha256=(Get-FileHash $dqnManifestPath).Hash.ToLowerInvariant()}

function Save-Identity {
    $dqnIdentity | ConvertTo-Json | Set-Content ($dqnLaunchPath + '.tmp')
    Move-Item -LiteralPath ($dqnLaunchPath + '.tmp') -Destination $dqnLaunchPath -Force
    Copy-Item $dqnLaunchPath .dqn-cache/active_experiment.json -Force
    Copy-Item $dqnLaunchPath .dqn-cache/next_experiment.json -Force
}
Save-Identity
try {
    while (-not $dqnWorker.HasExited) {
        if ([DateTime]::UtcNow -ge $dqnLimit) {
            $dqnInfo = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $dqnWorker.Id)
            $dqnLive = Get-Process -Id $dqnWorker.Id -ErrorAction SilentlyContinue
            if ($dqnInfo -and $dqnLive -and $dqnLive.StartTime.ToUniversalTime() -eq $dqnStarted -and
                $dqnInfo.CommandLine.Contains($dqnScript)) { Stop-Process -InputObject $dqnLive -Force }
            throw 'Original allocated deadline reached; checkpoints and journals retained'
        }
        Start-Sleep -Seconds 5
        $dqnWorker.Refresh()
    }
    $dqnResult = Get-Content (Join-Path $dqnRunPath 'result.json') -Raw | ConvertFrom-Json
    if ($dqnResult.confirmation.pairs -ne 128 -or $dqnResult.confirmation.samples -ne 32) {
        throw 'Missing complete selected-setting confirmation; inspect preserved logs'
    }
    $dqnIdentity.phase = 'research_complete'
    $dqnIdentity.worker_pid = $null
    Save-Identity
} catch {
    $dqnIdentity.phase = 'needs_attention'
    $dqnIdentity['error'] = $_.Exception.Message
    Save-Identity
    throw
}
