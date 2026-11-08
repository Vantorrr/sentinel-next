param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$Preset
)
$ErrorActionPreference = "Stop"
if (-not ([System.Management.Automation.PSTypeName]"TokenPriv").Type) {
    Add-Type @"
using System;
using System.Runtime.InteropServices;
public class TokenPriv {
  [DllImport("advapi32.dll", SetLastError=true)]
  public static extern bool OpenProcessToken(IntPtr ProcessHandle, uint DesiredAccess, out IntPtr TokenHandle);
  [DllImport("advapi32.dll", SetLastError=true, CharSet=CharSet.Unicode)]
  public static extern bool LookupPrivilegeValue(string lpSystemName, string lpName, out long lpLuid);
  [DllImport("advapi32.dll", SetLastError=true)]
  public static extern bool AdjustTokenPrivileges(IntPtr TokenHandle, bool DisableAllPrivileges, ref TokPriv1Luid NewState, uint BufferLength, IntPtr PreviousState, IntPtr ReturnLength);
  [StructLayout(LayoutKind.Sequential, Pack=1)]
  public struct TokPriv1Luid { public uint Count; public long Luid; public uint Attr; }
  public static void Enable(string name) {
    IntPtr token;
    OpenProcessToken(System.Diagnostics.Process.GetCurrentProcess().Handle, 0x0028, out token);
    long luid;
    LookupPrivilegeValue(null, name, out luid);
    TokPriv1Luid tp;
    tp.Count = 1;
    tp.Luid = luid;
    tp.Attr = 0x00000002;
    AdjustTokenPrivileges(token, false, ref tp, 0, IntPtr.Zero, IntPtr.Zero);
  }
}
"@
}
[TokenPriv]::Enable("SeTakeOwnershipPrivilege")
[TokenPriv]::Enable("SeRestorePrivilege")
$known = @("data", "private", "app", "models", "control", "logs")
if ($known -notcontains $Preset) {
    [Console]::Error.WriteLine("Unknown preset $Preset")
    exit 2
}

function Set-Dacl($Item) {
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
    $admin = New-Object System.Security.Principal.SecurityIdentifier "S-1-5-32-544"
    $acl.SetOwner($admin)
    $Item.SetAccessControl($acl)
}

function Walk($Item) {
    Set-Dacl $Item
    $isDir = [bool]($Item.Attributes -band [IO.FileAttributes]::Directory)
    if (-not $isDir) { return }
    if ($Preset -eq "data") {
        foreach ($child in $Item.GetFiles()) { Walk $child }
        return
    }
    foreach ($child in $Item.GetFileSystemInfos()) { Walk $child }
}

try {
    Walk (New-Object System.IO.DirectoryInfo $Path)
} catch {
    [Console]::Error.WriteLine($_.Exception.ToString())
    exit 1
}
exit 0
