<#
.SYNOPSIS
Owner step G of kit 0.4.2 (orchestrator.md): deny the Codex sandbox writes to a project's control files, then print the ACLs.

.DESCRIPTION
Run by the Owner from a NON-elevated PowerShell, once per project, after:
  - the reviewed guard, settings and Codex rules are installed (Owner step F), and
  - the project's Codex session has been relaunched and has run one sandboxed command, so that Codex's
    own sandbox setup refresh has already rewritten the root's ACL (it drops a deny on the root).

It is idempotent: an entry already present is left as it is. -Check only reports and changes nothing;
it exits 1 when an entry is missing or an owner is wrong. Run -Check again after any Codex sandbox setup
refresh (a new Codex version, a relaunch with other writable roots).

The deny binds only the local group CodexSandboxUsers (the sandbox accounts). The Owner's own account and
Claude sessions are unaffected. Rights (icacls notation): D delete, DC delete-child, WD create files,
AD create folders, W write, WDAC change permissions, WO take ownership; (OI)(CI) inherit to files and
folders below.

Containment: the only paths touched are the fixed list below, under -Root (and the root's parent with
-ProtectParent). Each must resolve to itself (no link or junction) inside the root. Nothing is created,
moved or deleted. Anything unexpected stops the script before any change.

Elevation: none of this needs it, and it refuses to run elevated: objects an elevated shell creates are
owned by Administrators, and Codex's setup refresh then fails with WRITE_DAC denied. The one elevated
step is the ownership repair it prints when it finds that case.

.EXAMPLE
& .\owner-acl.ps1 -Root E:\AI\Projects\OpenMinds\Minions\Minion-Remote -Check
& .\owner-acl.ps1 -Root E:\AI\Projects\OpenMinds\Minions\Minion-Remote
#>
param(
    [Parameter(Mandatory)][string]$Root,
    [switch]$Check,
    [switch]$ProtectParent
)
$ErrorActionPreference = 'Stop'
$Group = 'CodexSandboxUsers'

# --- rights ---------------------------------------------------------------------------------------
$R = [System.Security.AccessControl.FileSystemRights]
$bits = @{
    D    = [int]$R::Delete
    DC   = [int]$R::DeleteSubdirectoriesAndFiles
    WD   = [int]$R::CreateFiles
    AD   = [int]$R::CreateDirectories
    W    = [int]$R::WriteData -bor [int]$R::AppendData -bor [int]$R::WriteExtendedAttributes -bor [int]$R::WriteAttributes
    WDAC = [int]$R::ChangePermissions
    WO   = [int]$R::TakeOwnership
}
function Mask([string[]]$names) { $m = 0; foreach ($n in $names) { $m = $m -bor $bits[$n] }; $m }

# Relative path, inherit to children, rights, required (else skipped when absent).
$targets = @(
    @{ Rel = '';                           Inherit = $false; Rights = @('D', 'DC');                           Required = $true },
    @{ Rel = '.claude';                    Inherit = $false; Rights = @('WD', 'AD', 'DC', 'D', 'WDAC', 'WO'); Required = $false },
    @{ Rel = '.claude\settings.json';      Inherit = $false; Rights = @('W', 'D', 'WDAC', 'WO');              Required = $false },
    @{ Rel = '.claude\settings.local.json'; Inherit = $false; Rights = @('W', 'D', 'WDAC', 'WO');             Required = $false },
    @{ Rel = '.claude\hooks';              Inherit = $true;  Rights = @('W', 'D', 'WDAC', 'WO', 'DC');        Required = $false },
    @{ Rel = '.claude\skills';             Inherit = $true;  Rights = @('W', 'D', 'WDAC', 'WO', 'DC');        Required = $false },
    @{ Rel = '.codex';                     Inherit = $false; Rights = @('WD', 'AD', 'DC', 'D', 'WDAC', 'WO'); Required = $false },
    @{ Rel = '.codex\rules';               Inherit = $true;  Rights = @('W', 'D', 'WDAC', 'WO', 'DC');        Required = $false }
)

# --- containment and preconditions ---------------------------------------------------------------
if ($Root -notmatch '^[A-Za-z]:\\[^\\/:*?"<>|]+(\\[^\\/:*?"<>|]+)*$' -or $Root -match '\\\.\.?(\\|$)') {
    throw "Root must be a plain absolute path such as E:\Folder\Project (no UNC, '..', trailing '\'): $Root"
}
$item = Get-Item -LiteralPath $Root -Force
if (-not $item.PSIsContainer) { throw "Root is not a folder: $Root" }
if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Root is a link or junction: $Root" }
if ($item.FullName -ne $Root) { throw "Root must be spelled as it resolves: $($item.FullName)" }
$guard = Test-Path -LiteralPath (Join-Path $Root '.claude\settings.json')
$rules = Test-Path -LiteralPath (Join-Path $Root '.codex\rules')
if (-not ($guard -or $rules)) {
    throw "No installed .claude\settings.json or .codex\rules under $Root. Install the reviewed pack first (Owner step F)."
}
$me = [Security.Principal.WindowsIdentity]::GetCurrent()
$elevated = ([Security.Principal.WindowsPrincipal]$me).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($elevated -and -not $Check) {
    throw 'Run this from a NON-elevated PowerShell. Nothing here needs elevation, and objects touched elevated end up owned by Administrators.'
}
try { $sid = (New-Object Security.Principal.NTAccount($Group)).Translate([Security.Principal.SecurityIdentifier]) }
catch { throw "Local group $Group not found: the Codex elevated sandbox has not been set up on this host." }

function Resolve-Target($rel) {
    $p = if ($rel) { Join-Path $Root $rel } else { $Root }
    if (-not (Test-Path -LiteralPath $p)) { return $null }
    $i = Get-Item -LiteralPath $p -Force
    if ($i.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Link or junction refused: $p" }
    if ($i.FullName -ne $p -or ($rel -and -not $i.FullName.StartsWith("$Root\", [StringComparison]::OrdinalIgnoreCase))) {
        throw "Resolves outside the root: $p -> $($i.FullName)"
    }
    return $i.FullName
}

function Test-Deny($path, $mask, $inherit) {
    $want = if ($inherit) { [Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit' } else { [Security.AccessControl.InheritanceFlags]::None }
    foreach ($ace in (Get-Acl -LiteralPath $path).Access) {
        if ($ace.AccessControlType -ne 'Deny' -or $ace.IsInherited) { continue }
        try { $aceSid = $ace.IdentityReference.Translate([Security.Principal.SecurityIdentifier]) } catch { continue }
        if ($aceSid -ne $sid -or $ace.InheritanceFlags -ne $want) { continue }
        if ((([int]$ace.FileSystemRights) -band $mask) -eq $mask) { return $true }
    }
    return $false
}

# --- plan ----------------------------------------------------------------------------------------
$user = $me.Name
$problems = 0
$work = @()
$list = @($targets)
if ($ProtectParent) { $list = @(@{ Rel = '..'; Inherit = $false; Rights = @('D', 'DC'); Required = $true }) + $list }
foreach ($t in $list) {
    if ($t.Rel -eq '..') {
        $path = Split-Path -Parent $Root
        if ((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Parent is a link: $path" }
    } else {
        $path = Resolve-Target $t.Rel
    }
    if (-not $path) {
        if ($t.Required) { throw "Missing: $Root\$($t.Rel)" }
        continue
    }
    $owner = (Get-Acl -LiteralPath $path).Owner
    if ($owner -notin @($user)) {
        Write-Output "OWNER  $path is owned by $owner, not $user."
        Write-Output "       It was probably created from an elevated shell; Codex's setup refresh then cannot set its ACL."
        Write-Output "       Repair once, from an ELEVATED shell:  icacls `"$path`" /setowner `"$user`" /T"
        $problems++
        continue
    }
    $mask = Mask $t.Rights
    $flags = if ($t.Inherit) { '(OI)(CI)' } else { '' }
    $spec = "${Group}:$flags($($t.Rights -join ','))"
    if (Test-Deny $path $mask $t.Inherit) {
        Write-Output "OK     $path  deny $spec"
    } else {
        Write-Output "MISSING $path  deny $spec"
        $work += , @($path, $spec)
    }
}

# Stale sandbox grants on the parent keep R4 routes 5 and 6 open (a sandbox that can move the root aside).
$parent = Split-Path -Parent $Root
foreach ($ace in (Get-Acl -LiteralPath $parent).Access) {
    if ($ace.AccessControlType -ne 'Allow') { continue }
    try { $aceSid = $ace.IdentityReference.Translate([Security.Principal.SecurityIdentifier]) } catch { continue }
    if ($aceSid -eq $sid) {
        Write-Output "PARENT $parent grants $Group $($ace.FileSystemRights) (inherited: $($ace.IsInherited))."
        Write-Output '       Left by a Codex session whose writable root was the parent. Either remove it'
        Write-Output "       (icacls `"$parent`" /remove:g $Group  - slow: it rewrites every file below)"
        Write-Output '       or rerun with -ProtectParent to deny D,DC on the parent itself.'
        if (-not $ProtectParent) { $problems++ }
    }
}

if ($Check) {
    foreach ($w in $work) { $problems++ }
    Write-Output $(if ($problems) { "CHECK-FAIL: $problems problem(s)" } else { 'CHECK-PASS' })
    exit [int]($problems -gt 0)
}
if ($problems) { throw "Stopped before any change: $problems problem(s) above." }

# --- apply ---------------------------------------------------------------------------------------
foreach ($w in $work) {
    & icacls $w[0] /deny $w[1] | Out-Null
    if ($LASTEXITCODE) { throw "icacls failed on $($w[0])" }
    Write-Output "ADDED  $($w[0])  deny $($w[1])"
}
Write-Output ''
Write-Output 'ACLs for the record (post them on the coordination issue):'
foreach ($t in $list) {
    $p = if ($t.Rel -eq '..') { $parent } else { Resolve-Target $t.Rel }
    if ($p) { & icacls $p }
}
