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
foreach ($ace in $acl.Access) {
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
    $broad = @("S-1-5-32-545", "S-1-5-11", "S-1-1-0")
    $isBroad = ($broad -contains $sid) -or ($name -match "\\(Users|Everyone|Authenticated Users)$")
    if (-not $isBroad) { continue }
    if (([int]$ace.FileSystemRights -band $writeBits) -ne 0) {
        [Console]::Error.WriteLine("Users can write this folder. Move it somewhere only an administrator can change, then run Install again.")
        exit 3
    }
}
exit 0
