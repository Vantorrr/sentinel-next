param(
    [Parameter(Mandatory = $true)][string]$Root
)
$ErrorActionPreference = "Stop"
$item = New-Object System.IO.DirectoryInfo $Root
if (-not $item.Exists) {
    [Console]::Error.WriteLine("Package folder was not found.")
    exit 2
}

function Get-AclOf($entry) {
    $sections = [System.Security.AccessControl.AccessControlSections]::All
    if ($entry -is [System.IO.DirectoryInfo]) {
        return New-Object System.Security.AccessControl.DirectorySecurity($entry.FullName, $sections)
    }
    return New-Object System.Security.AccessControl.FileSecurity($entry.FullName, $sections)
}

function Convert-ToSid($identity) {
    $name = $identity.Value
    if ($name -match "^S-1-") { return $name }
    try {
        return $identity.Translate([System.Security.Principal.SecurityIdentifier]).Value
    } catch {
        return $name
    }
}

$me = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$writeBits = 0x0002 -bor 0x0004 -bor 0x0010 -bor 0x0040 -bor 0x0100 -bor 0x10000

function Test-Node($entry) {
    if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        [Console]::Error.WriteLine("Package path is a link or junction: $($entry.FullName)")
        exit 2
    }
    $acl = Get-AclOf $entry
    $owner = $acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value
    if ($owner -ne "S-1-5-32-544" -and $owner -ne "S-1-5-18" -and $owner -ne $me) {
        [Console]::Error.WriteLine("Owner is not Administrators or the installing user ($owner): $($entry.FullName)")
        exit 4
    }
    $allowed = @("S-1-5-18", "S-1-5-32-544")
    if ($owner -eq $me) { $allowed += $me }
    foreach ($ace in $acl.Access) {
        if ($ace.AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow) { continue }
        $sid = Convert-ToSid $ace.IdentityReference
        if ($allowed -contains $sid) { continue }
        $rightName = [string]$ace.FileSystemRights
        $rights = [int64]$ace.FileSystemRights
        $writes = ($rights -band [int64]$writeBits) -ne 0
        if ($writes -or $rightName -match "Modify|FullControl|Write|Delete|Append") {
            [Console]::Error.WriteLine("A principal other than Administrators can write: $($entry.FullName) $sid $rightName")
            exit 3
        }
    }
    if ($entry -is [System.IO.DirectoryInfo]) {
        foreach ($child in $entry.GetFileSystemInfos()) {
            Test-Node $child
        }
    }
}

Test-Node $item
exit 0
