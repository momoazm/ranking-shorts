# Registers "MOMO Runner Helper" to launch hidden at every logon. Run this once:
#   powershell -ExecutionPolicy Bypass -File register-task.ps1
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

$action  = New-ScheduledTaskAction -Execute "powershell.exe" `
             -Argument "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$here\start-helper.ps1`""
$trigger = New-ScheduledTaskTrigger -AtLogOn

try {
    Register-ScheduledTask -TaskName "MOMO Runner Helper" -Action $action -Trigger $trigger -Force | Out-Null
    Write-Host "Task registered. Starting it now..."
    Start-ScheduledTask -TaskName "MOMO Runner Helper"
    Start-Sleep -Seconds 2
    $p = Get-Process pythonw -ErrorAction SilentlyContinue
    if ($p) { Write-Host "Helper is running (PID $($p.Id))." }
    else { Write-Host "Task started but no pythonw process seen yet -- check helper.log in a few seconds." }
} catch {
    Write-Host "FAILED: $($_.Exception.Message)"
    Write-Host "If this says 'Access is denied', try running PowerShell as Administrator just for this one step."
}
