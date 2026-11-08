param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][ValidateSet("data", "private", "app", "models", "control", "logs")][string]$Preset
)
$ErrorActionPreference = "Stop"
& takeown.exe /F $Path /A /R /D Y | Out-Null

function New-Sid([string]$Value) {
    New-Object System.Security.Principal.SecurityIdentifier $Value
}

function New-CleanAcl([bool]$Directory, [string]$Kind) {
    if ($Directory) {
        $acl = New-Object System.Security.AccessControl.DirectorySecurity
        $inherit = [System.Security.AccessControl.InheritanceFlags]"ContainerInherit,ObjectInherit"
    } else {
        $acl = New-Object System.Security.AccessControl.FileSecurity
        $inherit = [System.Security.AccessControl.InheritanceFlags]::None
    }
    $acl.SetOwner((New-Sid "S-1-5-32-544"))
    $acl.SetAccessRuleProtection($true, $false)
    $none = [System.Security.AccessControl.PropagationFlags]::None
    $allow = [System.Security.AccessControl.AccessControlType]::Allow
    function Add-Rule([string]$Sid, [string]$Rights) {
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            (New-Sid $Sid), $Rights, $inherit, $none, $allow)
        $acl.AddAccessRule($rule)
    }
    Add-Rule "S-1-5-18" "FullControl"
    Add-Rule "S-1-5-32-544" "FullControl"
    switch ($Kind) {
        "data" {
            Add-Rule "S-1-5-19" "Modify"
            Add-Rule "S-1-5-32-545" "ReadAndExecute"
        }
        "private" { Add-Rule "S-1-5-19" "Modify" }
        "app" { Add-Rule "S-1-5-19" "ReadAndExecute" }
        "models" { Add-Rule "S-1-5-19" "ReadAndExecute" }
        "control" {
            Add-Rule "S-1-5-19" "Modify"
            Add-Rule "S-1-5-32-545" "Modify"
        }
        "logs" {
            Add-Rule "S-1-5-19" "Modify"
            Add-Rule "S-1-5-32-545" "ReadAndExecute"
        }
    }
    return $acl
}

function Set-Tree([System.IO.FileSystemInfo]$Item, [string]$Kind) {
    $isDir = $Item.PSIsContainer
    $acl = New-CleanAcl $isDir $Kind
    $Item.SetAccessControl($acl)
    if ($isDir) {
        foreach ($child in $Item.GetFileSystemInfos()) {
            Set-Tree $child $Kind
        }
    }
}

Set-Tree (New-Object System.IO.DirectoryInfo $Path) $Preset
exit 0
