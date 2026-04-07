@echo off
:: PXEGEMINI Launcher v5.3 - Com admin e firewall auto-config
cd /d "%~dp0"

:: ============== ADMIN CHECK ==============
net session >nul 2>&1
if %errorlevel% == 0 goto :ADMIN_OK

:: Re-run as admin
echo Pedindo permissao de Administrador...
powershell -Command "Start-Process cmd -ArgumentList '/c cd /d \"%~dp0\" && \"%~f0\"' -Verb RunAs"
exit /b

:ADMIN_OK
echo [PXEGEMINI] Executando como Administrador...

:: ============== FIREWALL RULES ==============
echo [PXEGEMINI] Configurando Firewal...

netsh advfirewall firewall delete rule name="PXE GEMINI HTTP" >nul 2>&1
netsh advfirewall firewall add rule name="PXE GEMINI HTTP" dir=in action=allow protocol=TCP localport=80 profile=any >nul 2>&1
echo  - Regra HTTP (TCP/80) OK

netsh advfirewall firewall delete rule name="PXE GEMINI TFTP" >nul 2>&1
netsh advfirewall firewall add rule name="PXE GEMINI TFTP" dir=in action=allow protocol=UDP localport=69 profile=any >nul 2>&1
echo  - Regra TFTP (UDP/69) OK

netsh advfirewall firewall delete rule name="PXE GEMINI DHCP" >nul 2>&1
netsh advfirewall firewall add rule name="PXE GEMINI DHCP" dir=in action=allow protocol=UDP localport=67 profile=any >nul 2>&1
echo  - Regra DHCP (UDP/67) OK

netsh advfirewall firewall delete rule name="PXE GEMINI PROXYDHCP" >nul 2>&1
netsh advfirewall firewall add rule name="PXE GEMINI PROXYDHCP" dir=in action=allow protocol=UDP localport=4011 profile=any >nul 2>&1
echo  - Regra ProxyDHCP (UDP/4011) OK

echo.
echo [PXEGEMINI] Firewal configurado. Iniciando aplicacao...
echo.

:: ============== LAUNCH APP ==============
python main.py

PAUSE
