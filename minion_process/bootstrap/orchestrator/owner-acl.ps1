<#
.SYNOPSIS
Owner step G of kit 0.4.2 (orchestrator.md): deny the Codex sandbox writes to a project's control files, then print the ACLs.

.DESCRIPTION
Run by the Owner from a NON-elevated PowerShell, once per project, after:
  - the reviewed guard, settings and Codex rules are installed (Owner step F), and
  - the project's Codex session has been relaunched and has run one sandboxed command, so that Codex's
    own sandbox setup refresh has already rewritten the root's ACL (it drops a deny on the root).

It is idempotent: an entry already present with the requested scope is left as it is. -Check only
reports and changes nothing; it exits 1 when an entry is missing, an owner is wrong, or the parent
folder grants the sandbox access. Run -Check again after any Codex sandbox setup refresh (a new Codex
version, a relaunch with other writable roots).

The deny binds only the local group CodexSandboxUsers (the sandbox accounts). The Owner's own account and
Claude sessions are unaffected. Rights (icacls notation): D delete, DC delete-child, WD create files,
AD create folders, W write, WDAC change permissions, WO take ownership; (OI)(CI) inherit to files and
folders below. A deny counts as present only when it is explicit, applies to the object itself
(propagation None, never inherit-only) and, for (OI)(CI), reaches every level below.

Containment: the only objects changed are the fixed list below, all inside -Root. Before anything is
read for selection, every component of the root's path, from the drive down, and of each target's path
must be an ordinary folder or file: no junction, symbolic link or other reparse point anywhere in the
chain. Nothing is created, moved or deleted. Anything unexpected stops the script before any change.
The parent folder is only read, to report a stale sandbox grant; this script never changes it.

Elevation: none of this needs it, and it refuses to run elevated: objects an elevated shell creates are
owned by Administrators, and Codex's setup refresh then fails with WRITE_DAC denied. The one elevated
step is the ownership repair it prints when it finds that case.

.EXAMPLE
& .\owner-acl.ps1 -Root E:\AI\Projects\OpenMinds\Minions\Minion-Remote -Check
& .\owner-acl.ps1 -Root E:\AI\Projects\OpenMinds\Minions\Minion-Remote
#>
param(
    [Parameter(Mandatory)][string]$Root,
    [switch]$Check
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
    @{ Rel = '';                            Inherit = $false; Rights = @('D', 'DC');                           Required = $true },
    @{ Rel = '.claude';                     Inherit = $false; Rights = @('WD', 'AD', 'DC', 'D', 'WDAC', 'WO'); Required = $false },
    @{ Rel = '.claude\settings.json';       Inherit = $false; Rights = @('W', 'D', 'WDAC', 'WO');              Required = $false },
    @{ Rel = '.claude\settings.local.json'; Inherit = $false; Rights = @('W', 'D', 'WDAC', 'WO');              Required = $false },
    @{ Rel = '.claude\hooks';               Inherit = $true;  Rights = @('W', 'D', 'WDAC', 'WO', 'DC');        Required = $false },
    @{ Rel = '.claude\skills';              Inherit = $true;  Rights = @('W', 'D', 'WDAC', 'WO', 'DC');        Required = $false },
    @{ Rel = '.codex';                      Inherit = $false; Rights = @('WD', 'AD', 'DC', 'D', 'WDAC', 'WO'); Required = $false },
    @{ Rel = '.codex\rules';                Inherit = $true;  Rights = @('W', 'D', 'WDAC', 'WO', 'DC');        Required = $false }
)

# --- containment ---------------------------------------------------------------------------------
# Every component from the drive root down to $path must exist as itself: not a reparse point (junction,
# symbolic link, mount point), and spelled as it resolves. FullName alone does not resolve a junction
# above the object, so each ancestor is inspected (KIT-042-R002).
function Assert-NoLinkChain([string]$path) {
    $parts = $path.Split('\')
    $current = $parts[0] + '\'
    for ($i = 1; $i -lt $parts.Count; $i++) {
        $current = if ($i -eq 1) { $current + $parts[$i] } else { $current + '\' + $parts[$i] }
        $item = Get-Item -LiteralPath $current -Force
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $item.LinkType) {
            throw "Link or junction in the path, refused: $current"
        }
        if ($item.FullName -ne $current) { throw "Path component does not resolve to itself: $current -> $($item.FullName)" }
    }
}

if ($Root -notmatch '^[A-Za-z]:\\[^\\/:*?"<>|]+(\\[^\\/:*?"<>|]+)*$' -or $Root -match '\\\.\.?(\\|$)') {
    throw "Root must be a plain absolute path such as E:\Folder\Project (no UNC, '..', trailing '\'): $Root"
}
Assert-NoLinkChain $Root
if (-not (Get-Item -LiteralPath $Root -Force).PSIsContainer) { throw "Root is not a folder: $Root" }
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
    Assert-NoLinkChain $p
    $i = Get-Item -LiteralPath $p -Force
    if ($i.FullName -ne $p -or ($rel -and -not $i.FullName.StartsWith("$Root\", [StringComparison]::OrdinalIgnoreCase))) {
        throw "Resolves outside the root: $p -> $($i.FullName)"
    }
    return $i.FullName
}

# An explicit deny for the sandbox group, with the whole mask, that applies to the object itself
# (propagation None: not inherit-only, and for (OI)(CI) not limited to one level) (KIT-042-R003).
function Test-Deny($path, $mask, $inherit) {
    $want = if ($inherit) { [Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit' } else { [Security.AccessControl.InheritanceFlags]::None }
    foreach ($ace in (Get-Acl -LiteralPath $path).Access) {
        if ($ace.AccessControlType -ne 'Deny' -or $ace.IsInherited) { continue }
        try { $aceSid = $ace.IdentityReference.Translate([Security.Principal.SecurityIdentifier]) } catch { continue }
        if ($aceSid -ne $sid -or $ace.InheritanceFlags -ne $want) { continue }
        if ($ace.PropagationFlags -ne [Security.AccessControl.PropagationFlags]::None) { continue }
        if ((([int]$ace.FileSystemRights) -band $mask) -eq $mask) { return $true }
    }
    return $false
}

# --- plan ----------------------------------------------------------------------------------------
$user = $me.Name
$problems = 0
$warnings = 0
$work = @()
foreach ($t in $targets) {
    $path = Resolve-Target $t.Rel
    if (-not $path) {
        if ($t.Required) { throw "Missing: $Root\$($t.Rel)" }
        continue
    }
    $owner = (Get-Acl -LiteralPath $path).Owner
    if ($owner -ne $user) {
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

# Read only: a stale sandbox grant on the parent keeps R4 routes 5 and 6 open (a sandbox that can move
# the root aside). Removing it is an Owner action outside this project's root; this script never does it.
$parent = Split-Path -Parent $Root
foreach ($ace in (Get-Acl -LiteralPath $parent).Access) {
    if ($ace.AccessControlType -ne 'Allow') { continue }
    try { $aceSid = $ace.IdentityReference.Translate([Security.Principal.SecurityIdentifier]) } catch { continue }
    if ($aceSid -eq $sid) {
        Write-Output "PARENT $parent grants $Group $($ace.FileSystemRights) (inherited: $($ace.IsInherited))."
        Write-Output '       Left by a Codex session whose writable root was the parent. It is outside this'
        Write-Output '       project; the Owner removes it if no session needs it:'
        Write-Output "       icacls `"$parent`" /remove:g $Group   (slow: it rewrites every file below)"
        $warnings++
    }
}

if ($Check) {
    $problems += $work.Count
    $total = $problems + $warnings
    Write-Output $(if ($total) { "CHECK-FAIL: $total problem(s)" } else { 'CHECK-PASS' })
    exit [int]($total -gt 0)
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
foreach ($t in $targets) {
    $p = Resolve-Target $t.Rel
    if ($p) { & icacls $p }
}
if ($warnings) { Write-Output "WARNING: $warnings parent grant(s) reported above; see W8 and W9." }
