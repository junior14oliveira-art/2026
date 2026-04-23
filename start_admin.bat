@echo off
setlocal EnableExtensions
cd /d "%~dp0"

rem Request elevation if the script is not running as Administrator.
net session >nul 2>&1
if not %errorlevel%==0 (
    echo Solicitando permissao de Administrador...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath 'cmd.exe' -ArgumentList '/c','\"\"%~f0\"\"' -Verb RunAs"
    exit /b
)

echo [PXEGEMINI] Executando como Administrador...
echo [PXEGEMINI] Configurando Firewall...

netsh advfirewall firewall delete rule name="PXEGEMINI HTTP" >nul 2>&1
netsh advfirewall firewall add rule name="PXEGEMINI HTTP" dir=in action=allow protocol=TCP localport=80 profile=any >nul 2>&1

netsh advfirewall firewall delete rule name="PXEGEMINI TFTP" >nul 2>&1
netsh advfirewall firewall add rule name="PXEGEMINI TFTP" dir=in action=allow protocol=UDP localport=69 profile=any >nul 2>&1

netsh advfirewall firewall delete rule name="PXEGEMINI DHCP" >nul 2>&1
netsh advfirewall firewall add rule name="PXEGEMINI DHCP" dir=in action=allow protocol=UDP localport=67 profile=any >nul 2>&1

netsh advfirewall firewall delete rule name="PXEGEMINI PROXYDHCP" >nul 2>&1
netsh advfirewall firewall add rule name="PXEGEMINI PROXYDHCP" dir=in action=allow protocol=UDP localport=4011 profile=any >nul 2>&1

echo [PXEGEMINI] Verificando portas em uso...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$udpPorts = @(67,69,4011); " ^
  "$pids = @(); " ^
  "$pids += @(Get-NetUDPEndpoint -ErrorAction SilentlyContinue | Where-Object { $udpPorts -contains $_.LocalPort } | Select-Object -ExpandProperty OwningProcess); " ^
  "$pids += @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -eq 80 } | Select-Object -ExpandProperty OwningProcess); " ^
  "$pids = $pids | Sort-Object -Unique; " ^
  "foreach ($procId in $pids) { " ^
  "  if (-not $procId) { continue } " ^
  "  try { " ^
  "    $proc = Get-Process -Id $procId -ErrorAction Stop; " ^
  "    if ($proc.ProcessName -match 'python|pyw|pythonw') { " ^
  "      Stop-Process -Id $procId -Force -ErrorAction Stop; " ^
  "      Write-Host ('  - Instancia antiga encerrada: PID ' + $procId); " ^
  "    } else { " ^
  "      Write-Host ('  - Porta usada por outro processo: ' + $proc.ProcessName + ' (PID ' + $procId + ')'); " ^
  "    } " ^
  "  } catch { } " ^
  "}"

set "PY_CMD="
where py >nul 2>&1 && set "PY_CMD=py -3"
if not defined PY_CMD (
    where python >nul 2>&1 && set "PY_CMD=python"
)

if not defined PY_CMD (
    echo Python nao encontrado. Instale o Python ou ajuste o PATH.
    pause
    exit /b 1
)

echo.
echo [PXEGEMINI] Iniciando aplicacao...
echo.

%PY_CMD% main.py
set "EXIT_CODE=%errorlevel%"

echo.
echo [PXEGEMINI] Aplicacao finalizada com codigo %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
