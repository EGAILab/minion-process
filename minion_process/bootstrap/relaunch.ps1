<#
.SYNOPSIS
(Re)launch one agent session of this project with the project-scope settings (project-scope.md PS-3, PS-5).

.DESCRIPTION
Run by the Owner in the session's own pane, after the agent has exited. The plan (working folder,
environment, command line) comes from `minion-process launch-plan`, which reads .minion\sessions.yaml.
The session resumed is -Resume, a new one with -Fresh, otherwise the one recorded at the last launch.
While the agent runs, a background job records the session id herdr reports for this pane into
.tmp\sessions\<name>.json, so the next relaunch needs no id. Installed by bootstrap\install.ps1.

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

$planArgs = @('-m', 'minion_process', 'launch-plan', '--root', $root, $Session)
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

$job = $null
if ($env:HERDR_PANE_ID) {
    $job = Start-Job -ArgumentList $py, $root, $Session, $env:HERDR_PANE_ID -ScriptBlock {
        param($py, $root, $name, $pane)
        $last = $null
        while ($true) {
            Start-Sleep -Seconds 5
            try { $id = ((herdr agent get $pane) -join '' | ConvertFrom-Json).result.agent.agent_session.value }
            catch { $id = $null }
            if ($id -and $id -ne $last) {
                & $py -m minion_process session-record --root $root $name $id | Out-Null
                if ($LASTEXITCODE -eq 0) { $last = $id }
            }
        }
    }
}

Set-Location -LiteralPath $plan.cwd
$exe = $plan.argv[0]
$rest = @($plan.argv | Select-Object -Skip 1)
try { & $exe @rest }
finally { if ($job) { Stop-Job $job; Remove-Job $job } }
