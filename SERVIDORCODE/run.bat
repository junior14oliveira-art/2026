@echo off
:: Fast HTTPDisk PXE Engine - Inicializador
title Fast HTTPDisk PXE
cd /d "%~dp0"

:: ============== ADMIN CHECK ==============
:: Verifica se tem privilegios de Administrador (Obrigatorio para DHCP/TFTP)
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [INFO] Solicitando privilegios de Administrador...
    powershell -Command "Start-Process cmd -ArgumentList '/c \"%~dpx0%~nx0\"' -Verb RunAs"
    exit /b
)

echo [OK] Privilegios de Administrador confirmados.

:: ============== FIREWALL RULES ==============
echo [INFO] Configurando regras do Windows Firewall...
for %%p in (67 69 80 4011) do (
    netsh advfirewall firewall show rule name="PXE_FAST_%%p_UDP" >nul 2>&1
    if errorlevel 1 (
        netsh advfirewall firewall add rule name="PXE_FAST_%%p_UDP" dir=in action=allow protocol=UDP localport=%%p >nul
        echo   - Porta UDP %%p liberada.
    )
)

netsh advfirewall firewall show rule name="PXE_FAST_80_TCP" >nul 2>&1
if errorlevel 1 (
    netsh advfirewall firewall add rule name="PXE_FAST_80_TCP" dir=in action=allow protocol=TCP localport=80 >nul
    echo   - Porta TCP 80 liberada.
)

echo [OK] Firewall configurado.
echo.
echo ==============================================
echo   INICIANDO MOTOR FAST HTTPDISK PXE...
echo ==============================================
echo.

:: Inicia o servidor Python
python app.py

:: Pausa em caso de crash
pause
