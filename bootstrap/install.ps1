<#
.SYNOPSIS
Install a pinned Minion-Process kit release inside a project (project-scope.md PS-1, PS-3). Owner-run.

.DESCRIPTION
Creates <root>\.tmp\kit\<version>\venv, installs the kit release into it, copies the shipped
relaunch.ps1 to <root>\.minion\ and writes <root>\.minion\kit.json (version and interpreter).

Nothing is written outside the root:
- no path component below the root may be a junction or link;
- temp and the pip cache are under <root>\.tmp;
- pip runs isolated, with no inherited destination or configuration.

Installing a later version adds a new venv beside the old one and switches kit.json, so going back is
re-running with the old version.

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

# A destination is accepted only if it is lexically under the root AND no existing component between the
# root and it (the leaf included) is a reparse point (junction or symbolic link), so a spelling inside the
# root can never write outside it. Checked before every write and every child command that writes.
function Assert-Inside([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    if (-not $full.StartsWith($rootFull + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "refusing a path outside the root: $full"
    }
    $current = $rootFull
    foreach ($part in $full.Substring($rootFull.Length + 1).Split('\')) {
        $current = Join-Path $current $part
        $item = Get-Item -LiteralPath $current -Force -ErrorAction SilentlyContinue
        if ($null -eq $item) { break }
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "refusing a redirected path component (junction or link): $current"
        }
    }
    return $full
}

# No link anywhere under a folder this script writes into (the venv, after creation and after install).
function Assert-NoLinks([string]$Path) {
    Assert-Inside $Path | Out-Null
    $link = Get-ChildItem -LiteralPath $Path -Recurse -Force -Attributes ReparsePoint -ErrorAction Stop |
        Select-Object -First 1
    if ($link) { throw "refusing a junction or link inside ${Path}: $($link.FullName)" }
}

if (-not $From) { $From = "minion-process @ git+https://github.com/EGAILab/minion-process@v$Version" }
$tmp = Assert-Inside (Join-Path $rootFull '.tmp')
$venv = Assert-Inside (Join-Path $rootFull ".tmp\kit\$Version\venv")
$cache = Assert-Inside (Join-Path $tmp 'pip-cache')
$minion = Assert-Inside (Join-Path $rootFull '.minion')

# The child processes get no inherited install destination or configuration: every PIP_* variable and
# the Python path variables are removed, pip loads no configuration file and runs isolated, and the
# cache is given on the command line. The venv's own interpreter is then the only install destination.
Get-ChildItem Env: | Where-Object { $_.Name -like 'PIP_*' } | ForEach-Object { Remove-Item -LiteralPath "Env:$($_.Name)" }
foreach ($name in 'PYTHONPATH', 'PYTHONHOME', 'PYTHONUSERBASE', 'PYTHONSTARTUP', 'VIRTUAL_ENV') {
    Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
}
$env:PYTHONNOUSERSITE = '1'
$env:PIP_CONFIG_FILE = 'nul'
$env:TEMP = $tmp; $env:TMP = $tmp

if (-not (Test-Path -LiteralPath $venv)) {
    New-Item -ItemType Directory -Force -Path $venv | Out-Null
    Assert-Inside $venv | Out-Null
    & $Python -I -m venv $venv
    if ($LASTEXITCODE) { throw "creating the venv failed ($LASTEXITCODE)" }
}
Assert-NoLinks $venv
$py = Join-Path $venv 'Scripts\python.exe'
& $py -I -m pip install --isolated --no-input --disable-pip-version-check --quiet --cache-dir $cache $From
if ($LASTEXITCODE) { throw "installing the kit failed ($LASTEXITCODE)" }
Assert-NoLinks $venv
$installed = (& $py -I -c "from importlib.metadata import version; print(version('minion-process'))").Trim()
if ($installed -ne $Version) { throw "installed minion-process $installed, expected $Version" }
$package = (& $py -I -c "import minion_process, os; print(os.path.realpath(minion_process.__file__))").Trim()
if (-not $package.StartsWith($venv + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw "minion_process was imported from $package, not from $venv"
}

New-Item -ItemType Directory -Force -Path $minion | Out-Null
Assert-Inside $minion | Out-Null
$shipped = (& $py -I -c "from importlib import resources; print(resources.files('minion_process.bootstrap') / 'relaunch.ps1')").Trim()
Copy-Item -LiteralPath $shipped -Destination (Assert-Inside (Join-Path $minion 'relaunch.ps1')) -Force
$kitJson = @{ version = $Version; python = $py } | ConvertTo-Json
[IO.File]::WriteAllText((Assert-Inside (Join-Path $minion 'kit.json')), $kitJson + "`n")

Write-Output "minion-process $Version installed in $venv"
Write-Output "next: list the sessions in $minion\sessions.yaml, then run"
Write-Output "  & $py -m minion_process onboard --root $rootFull --from <current> --to $Version"
