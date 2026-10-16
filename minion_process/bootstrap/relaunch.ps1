<#
.SYNOPSIS
(Re)launch one agent session of this project with the project-scope settings (project-scope.md PS-3, PS-5).

.DESCRIPTION
Run by the Owner in the session's own pane, after the agent has exited. The plan (working folder,
environment, command line) comes from `minion-process launch-plan`, which reads .minion\sessions.yaml.
The session resumed is -Resume, a new one with -Fresh, otherwise the one recorded at the last launch.
An id given with -Resume is recorded first (provenance owner).

While the agent runs, a background job records into .tmp\sessions\<name>.json the session id herdr
reports (provenance herdr), so the next relaunch needs no id. It records only an observation that:
- is for this pane;
- names this session's tool and the project root;
- carries an id that is new to this launch.

Installed by bootstrap\install.ps1.

.EXAMPLE
& .\.minion\relaunch.ps1 impl
& .\.minion\relaunch.ps1 review -Resume d38a7a9e-4b92-4b3d-b93a-f8a20a35644b
& .\.minion\relaunch.ps1 impl -DryRun
#>
param(
    [Parameter(Mandatory, Position = 0)][string]$Session,
    [string]$Resume,
    [switch]$Fresh,
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$kit = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot 'kit.json') | ConvertFrom-Json
$py = $kit.python

$planArgs = @('-I', '-m', 'minion_process', 'launch-plan', '--root', $root, $Session)
if ($Resume) { $planArgs += @('--resume', $Resume) }
if ($Fresh) { $planArgs += '--fresh' }
$json = (& $py @planArgs) -join "`n"
if ($LASTEXITCODE) { exit $LASTEXITCODE }
$plan = $json | ConvertFrom-Json
if ($DryRun) { Write-Output $json; exit 0 }

# Every environment value is a folder inside the root (checked by launch-plan); create it, then set it.
foreach ($p in $plan.env.PSObject.Properties) {
    New-Item -ItemType Directory -Force -Path $p.Value | Out-Null
    Set-Item -LiteralPath "Env:$($p.Name)" -Value $p.Value
}

# An id the Owner chose is recorded as such (provenance `owner`) before the launch.
if ($Resume) {
    & $py -I -m minion_process session-record --root $root $Session $Resume | Out-Null
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
}

# Record the session id for the next relaunch. `session-observe` writes only an observation of this pane
# that names this session's tool and the project root, and never the id the pane showed before this
# launch (a stale one) or the one already recorded by this launch.
$job = $null
$pane = $env:HERDR_PANE_ID
# The pre-launch read must succeed: a confirmed empty pane or a pane showing an id (excluded as stale).
# If herdr cannot be read, nothing is recorded for this launch and the recorded target is kept.
$baseline = $null
if ($pane) {
    try {
        $seen = (herdr pane get $pane) -join "`n" | ConvertFrom-Json
        if ($LASTEXITCODE -eq 0 -and $seen.result.pane.pane_id -eq $pane) {
            $baseline = @()
            $sid = $seen.result.pane.agent_session.value
            if ($sid) { $baseline += [string]$sid }
        }
    }
    catch { $baseline = $null }
    if ($null -eq $baseline) { Write-Warning "herdr could not be read for pane $pane; this launch's session id is not recorded" }
}
if ($null -ne $baseline) {
    if ($Fresh -and $plan.previous) { $baseline += [string]$plan.previous }  # a new session never has the old id
    $poll = 5
    if ($env:MINION_RELAUNCH_POLL_SECONDS -match '^[1-9][0-9]?$') { $poll = [int]$env:MINION_RELAUNCH_POLL_SECONDS }
    $excluded = ($baseline | Where-Object { $_ }) -join ','  # session ids hold no ','
    $job = Start-Job -ArgumentList $py, $root, $Session, $pane, $excluded, $poll -ScriptBlock {
        param($py, $root, $name, $pane, $excluded, $poll)
        $exclude = @(([string]$excluded).Split(',') | Where-Object { $_ })
        while ($true) {
            Start-Sleep -Seconds $poll
            $observeArgs = @('-I', '-m', 'minion_process', 'session-observe', '--root', $root, $name, '--pane', $pane)
            foreach ($id in $exclude) { if ($id) { $observeArgs += @('--exclude', $id) } }
            $out = (herdr pane get $pane) -join "`n" | & $py @observeArgs
            if ($LASTEXITCODE -eq 0 -and $out) { $exclude += ([string]$out).Trim() }
        }
    }
}

Set-Location -LiteralPath $plan.cwd
$exe = $plan.argv[0]
$rest = @($plan.argv | Select-Object -Skip 1)
try { & $exe @rest }
finally { if ($job) { Stop-Job $job; Remove-Job $job } }
