<#
.SYNOPSIS
Install a pinned Minion-Process kit release inside a project (project-scope.md PS-1, PS-3). Owner-run.

.DESCRIPTION
Creates <root>\.tmp\kit\<version>\venv, installs the kit release into it, copies the shipped
relaunch.ps1 to <root>\.minion\ and writes <root>\.minion\kit.json (version and interpreter).

Nothing is written outside the root:
- no path component below the root may be a junction or link;
- temp and the pip cache are a new folder under <root>\.tmp\kit\<version> for each run;
- the venv may hold no link, junction or hard-linked file, and outputs are replaced by rename;
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

# Writes go only where no alias can lead outside the root:
# - pip's cache and the children's temp folder are a new, empty folder created for this run;
# - the venv is scanned before and after pip, and any symbolic link, junction or hard-linked file in it is
#   refused (a hard link is not a reparse point, so a file could otherwise be shared with a file outside);
# - kit.json and relaunch.ps1 are written to a new file and renamed over the old one, which replaces the
#   directory entry and never writes into a file that may be linked elsewhere.
$scanPy = @'
import os, sys
for top, dirs, files in os.walk(sys.argv[1]):
    for name in dirs + files:
        path = os.path.join(top, name)
        if os.path.islink(path) or os.path.isjunction(path) or (name in files and os.lstat(path).st_nlink > 1):
            print(path)
            sys.exit(3)
'@

function Assert-NoAliases([string]$Interpreter, [string]$Path) {
    Assert-Inside $Path | Out-Null
    $found = (& $Interpreter -I $scan $Path)
    if ($LASTEXITCODE -eq 3) { throw "refusing a link, junction or hard-linked file inside ${Path}: $found" }
    if ($LASTEXITCODE) { throw "scanning $Path failed ($LASTEXITCODE)" }
}

function Set-NewFile([string]$Destination, [scriptblock]$Write) {
    $target = Assert-Inside $Destination
    $temp = Assert-Inside "$target.$PID.new"
    if (Test-Path -LiteralPath $temp) { throw "refusing to reuse $temp" }
    & $Write $temp
    Assert-Inside $temp | Out-Null
    Move-Item -LiteralPath $temp -Destination $target -Force
}

if (-not $From) { $From = "minion-process @ git+https://github.com/EGAILab/minion-process@v$Version" }
$kitDir = Assert-Inside (Join-Path $rootFull ".tmp\kit\$Version")
$venv = Assert-Inside (Join-Path $kitDir 'venv')
$run = Assert-Inside (Join-Path $kitDir ("run-{0}-{1}" -f (Get-Date -Format 'yyyyMMdd-HHmmss'), $PID))
$minion = Assert-Inside (Join-Path $rootFull '.minion')
if (Test-Path -LiteralPath $run) { throw "refusing an existing run folder $run" }
New-Item -ItemType Directory -Force -Path $run | Out-Null
Assert-Inside $run | Out-Null
$cache = Assert-Inside (Join-Path $run 'pip-cache')
$runTemp = Assert-Inside (Join-Path $run 'temp')
New-Item -ItemType Directory -Path $cache, $runTemp | Out-Null
$scan = Assert-Inside (Join-Path $run 'scan.py')
[IO.File]::WriteAllText($scan, $scanPy)

# The child processes get no inherited install destination or configuration: every PIP_* variable and
# the Python path variables are removed, pip loads no configuration file and runs isolated, and the
# cache is given on the command line. The venv's own interpreter is then the only install destination.
Get-ChildItem Env: | Where-Object { $_.Name -like 'PIP_*' } | ForEach-Object { Remove-Item -LiteralPath "Env:$($_.Name)" }
foreach ($name in 'PYTHONPATH', 'PYTHONHOME', 'PYTHONUSERBASE', 'PYTHONSTARTUP', 'VIRTUAL_ENV') {
    Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
}
$env:PYTHONNOUSERSITE = '1'
$env:PIP_CONFIG_FILE = 'nul'
$env:TEMP = $runTemp; $env:TMP = $runTemp

if (-not (Test-Path -LiteralPath $venv)) {
    New-Item -ItemType Directory -Force -Path $venv | Out-Null
    Assert-Inside $venv | Out-Null
    & $Python -I -m venv $venv
    if ($LASTEXITCODE) { throw "creating the venv failed ($LASTEXITCODE)" }
}
$py = Join-Path $venv 'Scripts\python.exe'
Assert-NoAliases $py $venv
& $py -I -m pip install --isolated --no-input --disable-pip-version-check --quiet --cache-dir $cache $From
if ($LASTEXITCODE) { throw "installing the kit failed ($LASTEXITCODE)" }
Assert-NoAliases $py $venv
$installed = (& $py -I -c "from importlib.metadata import version; print(version('minion-process'))").Trim()
if ($installed -ne $Version) { throw "installed minion-process $installed, expected $Version" }
$package = (& $py -I -c "import minion_process, os; print(os.path.realpath(minion_process.__file__))").Trim()
if (-not $package.StartsWith($venv + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw "minion_process was imported from $package, not from $venv"
}

New-Item -ItemType Directory -Force -Path $minion | Out-Null
Assert-Inside $minion | Out-Null
$shipped = (& $py -I -c "from importlib import resources; print(resources.files('minion_process.bootstrap') / 'relaunch.ps1')").Trim()
Set-NewFile (Join-Path $minion 'relaunch.ps1') { param($t) Copy-Item -LiteralPath $shipped -Destination $t }
$kitJson = (@{ version = $Version; python = $py } | ConvertTo-Json) + "`n"
Set-NewFile (Join-Path $minion 'kit.json') { param($t) [IO.File]::WriteAllText($t, $kitJson) }

Write-Output "minion-process $Version installed in $venv"
Write-Output "next: list the sessions in $minion\sessions.yaml, then run"
Write-Output "  & $py -m minion_process onboard --root $rootFull --from <current> --to $Version"
