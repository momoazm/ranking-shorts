# Starts the MOMO runner-helper hidden (no console window). Used by the manual run and by the
# "at logon" scheduled task. Prefers pythonw.exe (windowless) and falls back to python.exe.
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
if (-not $py) { $py = (Get-Command python -ErrorAction SilentlyContinue).Source }
if (-not $py) { Write-Error "Python not found on PATH."; exit 1 }
Start-Process -FilePath $py -ArgumentList "`"$here\runner_helper.py`"" -WorkingDirectory $here -WindowStyle Hidden
Write-Host "MOMO runner-helper launched ($py). Logs: $here\helper.log"
