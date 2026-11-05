# Launch a resumable RL experiment in the background at BelowNormal priority.
# Example: ./scripts/run_standalone_rl.ps1 -Run first -Python python.exe `
#   -TrainingArguments @('--hours', '36', '--workers', '3')
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]*$')]
    [string]$Run,
    [string]$Python = '',
    [string]$EntryScript = 'scripts/standalone_rl.py',
    [ValidateSet('prepare', 'train', 'run', 'lock', 'test', 'bench', 'validate')]
    [string]$Command = 'run',
    [string[]]$TrainingArguments = @()
)

$ErrorActionPreference = 'Stop'
$rlWorkspace = Split-Path -Parent $PSScriptRoot
if (-not $Python) {
    $rlCommand = Get-Command python, python3 -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($rlCommand) {
        $Python = $rlCommand.Source
    } else {
        $Python = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    }
}
$rlExecutable = (Get-Command $Python -ErrorAction Stop).Source
$rlEntry = (Resolve-Path -LiteralPath (Join-Path $rlWorkspace $EntryScript)).Path
if (-not $rlEntry.StartsWith($rlWorkspace + [System.IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) `
        -or [System.IO.Path]::GetExtension($rlEntry) -ne '.py') {
    throw 'EntryScript must be a Python file inside this repository.'
}
$rlFolder = Join-Path $rlWorkspace "runs\standalone-rl\$Run"
$rlProcessFile = Join-Path $rlFolder 'process.json'
if (Test-Path -LiteralPath $rlProcessFile) {
    $rlPrior = Get-Content -LiteralPath $rlProcessFile -Raw | ConvertFrom-Json
    if ($rlPrior.pid -and (Get-Process -Id $rlPrior.pid -ErrorAction SilentlyContinue)) {
        throw "Recorded process $($rlPrior.pid) is still live; no duplicate experiment was launched."
    }
}
if ($TrainingArguments -contains '--run') {
    throw 'Pass the run name through -Run only.'
}
$null = New-Item -ItemType Directory -Path $rlFolder -Force
$rlArguments = @('-u', $rlEntry, $Command, '--run', $Run) + $TrainingArguments
# Start-Process joins the argument array. Quote literal arguments containing spaces;
# none of these strings is passed to a command shell.
$rlQuotedArguments = foreach ($rlArgument in $rlArguments) {
    if ($rlArgument.Contains('"')) { throw 'Arguments containing a literal quote are unsupported.' }
    if ($rlArgument -match '\s') { '"' + $rlArgument + '"' } else { $rlArgument }
}
$rlLauncher = [System.Diagnostics.Process]::GetCurrentProcess()
$rlOriginalPriority = $rlLauncher.PriorityClass
try {
    # Lower the launcher before creation so the Python process starts at the
    # intended priority, including on systems where the old ctypes helper fails.
    $rlLauncher.PriorityClass = [System.Diagnostics.ProcessPriorityClass]::BelowNormal
    $rlProcess = Start-Process -FilePath $rlExecutable -ArgumentList $rlQuotedArguments `
        -WorkingDirectory $rlWorkspace -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $rlFolder 'run.out') `
        -RedirectStandardError (Join-Path $rlFolder 'run.err') -PassThru
    if (-not $rlProcess.HasExited) {
        $rlProcess.PriorityClass = [System.Diagnostics.ProcessPriorityClass]::BelowNormal
    }
} finally {
    $rlLauncher.PriorityClass = $rlOriginalPriority
}
[ordered]@{
    pid = $rlProcess.Id
    executable = $rlExecutable
    arguments = $rlArguments
    started_utc = [DateTime]::UtcNow.ToString('o')
    requested_priority = 'BelowNormal'
} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $rlProcessFile -Encoding utf8
[pscustomobject]@{Pid = $rlProcess.Id; RunFolder = $rlFolder; RequestedPriority = 'BelowNormal'}
