param(
    [Parameter(Mandatory = $true)][string]$Root
)
$ErrorActionPreference = "Stop"
$item = New-Object System.IO.DirectoryInfo $Root
if (-not $item.Exists) {
    [Console]::Error.WriteLine("Package folder was not found.")
    exit 2
}
if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
    [Console]::Error.WriteLine("Package path is a link or junction. Copy the folder to a normal directory and run Install again.")
    exit 2
}
if ($PSVersionTable.PSVersion.Major -ge 6) {
    $acl = [System.IO.FileSystemAclExtensions]::GetAccessControl($item)
} else {
    $acl = $item.GetAccessControl()
}
$writeBits = 0x0002 -bor 0x0004 -bor 0x0010 -bor 0x0040 -bor 0x0100 -bor 0x10000
$me = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$trusted = @("S-1-5-18", "S-1-5-32-544", "S-1-3-4", $me)
function Test-Entry([System.Security.AccessControl.FileSystemSecurity]$EntryAcl) {
    foreach ($ace in $EntryAcl.Access) {
        if ($ace.AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow) { continue }
        $name = $ace.IdentityReference.Value
        $sid = $name
        if ($name -notmatch "^S-1-") {
            try {
                $sid = $ace.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
            } catch {
                $sid = $name
            }
        }
        if ($trusted -contains $sid) { continue }
        if (([int]$ace.FileSystemRights -band $writeBits) -ne 0) {
            [Console]::Error.WriteLine("Someone other than the installing administrator can write this package. Move it to an administrator-only folder and run Install again.")
            exit 3
        }
    }
}
Test-Entry $acl
$package = Join-Path $Root "sentinel_edge"
if ([System.IO.Directory]::Exists($package)) {
    $packageItem = New-Object System.IO.DirectoryInfo $package
    if ($PSVersionTable.PSVersion.Major -ge 6) {
        Test-Entry ([System.IO.FileSystemAclExtensions]::GetAccessControl($packageItem))
    } else {
        Test-Entry $packageItem.GetAccessControl()
    }
    foreach ($file in $packageItem.GetFiles("*.py")) {
        if ($PSVersionTable.PSVersion.Major -ge 6) {
            Test-Entry ([System.IO.FileSystemAclExtensions]::GetAccessControl($file))
        } else {
            Test-Entry $file.GetAccessControl()
        }
    }
}
exit 0
