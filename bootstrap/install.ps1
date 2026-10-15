<#
.SYNOPSIS
Install a pinned Minion-Process kit release inside a project (project-scope.md PS-1, PS-3). Owner-run.

.DESCRIPTION
Creates <root>\.tmp\kit\<version>\venv, installs the kit release into it, copies the shipped
relaunch.ps1 to <root>\.minion\ and writes <root>\.minion\kit.json (version and interpreter). Nothing is
written outside the root: temp and the pip cache are redirected to <root>\.tmp first. Installing a later
version adds a new venv beside the old one and switches kit.json, so going back is re-running with the
old version.

.EXAMPLE
.\bootstrap\install.ps1 -Root E:\Work\MyProject -Version 0.4.0
#>
param(
    [Parameter(Mandatory)][string]$Root,
    [Parameter(Mandatory)][ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version,
    [string]$Python = 'python',
    # A pip requirement for the release; a local checkout path also works.
    [string]$From = ''
)
$ErrorActionPreference = 'Stop'
$rootFull = (Resolve-Path -LiteralPath $Root).Path.TrimEnd('\')

function Assert-Inside([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    if (-not $full.StartsWith($rootFull + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "refusing a path outside the root: $full"
    }
    return $full
}

if (-not $From) { $From = "minion-process @ git+https://github.com/EGAILab/minion-process@v$Version" }
$tmp = Assert-Inside (Join-Path $rootFull '.tmp')
$venv = Assert-Inside (Join-Path $rootFull ".tmp\kit\$Version\venv")
$minion = Assert-Inside (Join-Path $rootFull '.minion')
$env:TEMP = $tmp; $env:TMP = $tmp
$env:PIP_CACHE_DIR = Assert-Inside (Join-Path $tmp 'pip-cache')

if (-not (Test-Path -LiteralPath $venv)) {
    & $Python -m venv $venv
    if ($LASTEXITCODE) { throw "creating the venv failed ($LASTEXITCODE)" }
}
$py = Join-Path $venv 'Scripts\python.exe'
& $py -m pip install --disable-pip-version-check --quiet $From
if ($LASTEXITCODE) { throw "installing the kit failed ($LASTEXITCODE)" }
$installed = (& $py -c "from importlib.metadata import version; print(version('minion-process'))").Trim()
if ($installed -ne $Version) { throw "installed minion-process $installed, expected $Version" }

New-Item -ItemType Directory -Force -Path $minion | Out-Null
$shipped = (& $py -c "from importlib import resources; print(resources.files('minion_process.bootstrap') / 'relaunch.ps1')").Trim()
Copy-Item -LiteralPath $shipped -Destination (Assert-Inside (Join-Path $minion 'relaunch.ps1')) -Force
$kitJson = @{ version = $Version; python = $py } | ConvertTo-Json
[IO.File]::WriteAllText((Assert-Inside (Join-Path $minion 'kit.json')), $kitJson + "`n")

Write-Output "minion-process $Version installed in $venv"
Write-Output "next: list the sessions in $minion\sessions.yaml, then run"
Write-Output "  & $py -m minion_process onboard --root $rootFull --from <current> --to $Version"
