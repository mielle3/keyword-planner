@echo off
rem Stop every running KeywordPlanner (old or new). ASCII only on purpose.
title Stop KeywordPlanner
echo.
echo  Looking for running KeywordPlanner programs...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$found=@();" ^
 "$ports=8765..8774;" ^
 "Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $ports -contains $_.LocalPort } | ForEach-Object { $found += $_.OwningProcess };" ^
 "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '^(python|pythonw|py)(\.exe)?$' -and $_.CommandLine -match 'app\.py' } | ForEach-Object { $found += $_.ProcessId };" ^
 "$found = $found | Sort-Object -Unique;" ^
 "if (-not $found) { Write-Host '  Nothing is running. You can delete the old folder now.' }" ^
 "foreach ($id in $found) { $p = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $id) -ErrorAction SilentlyContinue; if ($p) { Write-Host ('  Stopping PID ' + $id + ' : ' + $p.CommandLine); Stop-Process -Id $id -Force -ErrorAction SilentlyContinue } }" ^
 "if ($found) { Write-Host ''; Write-Host '  Done. Old KeywordPlanner stopped. You can delete the old folder now.' }"
echo.
pause
