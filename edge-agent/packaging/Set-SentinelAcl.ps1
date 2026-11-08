param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$Preset
)
$ErrorActionPreference = "Stop"
$known = @("data", "private", "app", "models", "control", "logs")
if ($known -notcontains $Preset) {
    [Console]::Error.WriteLine("Unknown preset $Preset")
    exit 2
}
& takeown.exe /F $Path /A /R /D Y | Out-Null

function Set-One($Item) {
    $isDir = [bool]($Item.Attributes -band [IO.FileAttributes]::Directory)
    if ($isDir) {
        $acl = New-Object System.Security.AccessControl.DirectorySecurity
        $inherit = [System.Security.AccessControl.InheritanceFlags]"ContainerInherit,ObjectInherit"
    } else {
        $acl = New-Object System.Security.AccessControl.FileSecurity
        $inherit = [System.Security.AccessControl.InheritanceFlags]::None
    }
    $acl.SetAccessRuleProtection($true, $false)
    $none = [System.Security.AccessControl.PropagationFlags]::None
    $allow = [System.Security.AccessControl.AccessControlType]::Allow
    $rules = @(
        @("S-1-5-18", "FullControl"),
        @("S-1-5-32-544", "FullControl")
    )
    if ($Preset -eq "data") {
        $rules += ,@("S-1-5-19", "Modify")
        $rules += ,@("S-1-5-32-545", "ReadAndExecute")
    } elseif ($Preset -eq "private") {
        $rules += ,@("S-1-5-19", "Modify")
    } elseif ($Preset -eq "app" -or $Preset -eq "models") {
        $rules += ,@("S-1-5-19", "ReadAndExecute")
    } elseif ($Preset -eq "control") {
        $rules += ,@("S-1-5-19", "Modify")
        $rules += ,@("S-1-5-32-545", "Modify")
    } elseif ($Preset -eq "logs") {
        $rules += ,@("S-1-5-19", "Modify")
        $rules += ,@("S-1-5-32-545", "ReadAndExecute")
    }
    foreach ($pair in $rules) {
        $sid = New-Object System.Security.Principal.SecurityIdentifier ([string]$pair[0])
        $rights = [System.Security.AccessControl.FileSystemRights]$pair[1]
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            $sid, $rights, $inherit, $none, $allow)
        $acl.AddAccessRule($rule)
    }
    $Item.SetAccessControl($acl)
}

function Walk($Item) {
    Set-One $Item
    if ($Item.PSIsContainer) {
        foreach ($child in $Item.GetFileSystemInfos()) {
            Walk $child
        }
    }
}

try {
    Walk (New-Object System.IO.DirectoryInfo $Path)
} catch {
    [Console]::Error.WriteLine($_.Exception.ToString())
    exit 1
}
exit 0
