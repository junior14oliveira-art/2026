@echo off
title 4MCSERVER v2.0.4 - Ultra PXE Engine
setlocal enabledelayedexpansion

:: ----- Elevacao de Privilegios ----
net session >nul 2>&1
if !errorLevel! neq 0 (
    echo [!] Elevando privilegios de Administrador...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

:: Garantir que o diretorio de trabalho e a pasta do script
cd /d "%~dp0"
:: Limpar atributos de arquivos extraidos para garantir visibilidade no servidor HTTP
attrib -R -H -S "data\*" /S /D >nul 2>&1
cls

echo.
echo  ================================================================
echo    4MCSERVER v2.0  ^|  Ultra High Performance PXE  ^|  Go Edition
echo  ================================================================
echo.

:: ----- Matar processo antigo se existir (Agresso) -----
echo  [0/3] Limpando porta 8080 e processos antigos...
powershell -Command "Stop-Process -Name 4mcserver -Force -ErrorAction SilentlyContinue" >nul 2>&1
taskkill /F /IM 4mcserver.exe /T >nul 2>&1
wmic process where "name='4mcserver.exe'" delete >nul 2>&1
timeout /t 1 /nobreak >nul

:: ----- Liberar Firewall (Crucial para PXE) -----
echo  [0.1/3] Configurando Firewall do Windows...
netsh advfirewall firewall delete rule name="4MCSERVER" >nul 2>&1
netsh advfirewall firewall add rule name="4MCSERVER" dir=in action=allow program="%~dp04mcserver.exe" enable=yes >nul 2>&1
netsh advfirewall firewall add rule name="4MCSERVER" dir=out action=allow program="%~dp04mcserver.exe" enable=yes >nul 2>&1
:: Regras explicitas por porta para garantir
netsh advfirewall firewall add rule name="4MCSERVER_UDP" dir=in action=allow protocol=UDP localport=67,68,69,4011 enable=yes >nul 2>&1
netsh advfirewall firewall add rule name="4MCSERVER_TCP" dir=in action=allow protocol=TCP localport=80,8080 enable=yes >nul 2>&1

:: ----- Compilar (sempre recompila para garantir versao mais nova) -----
echo  [1/3] Compilando projeto Go...
if exist 4mcserver.exe del /f /q 4mcserver.exe

go build -o 4mcserver.exe ./cmd/gemini/
if !errorLevel! neq 0 (
    echo.
    echo  [ERRO] Falha na compilacao. Verifique se o Go esta instalado.
    echo  Download: https://go.dev/dl/
    echo.
    pause
    exit /b
)
echo  [OK] Compilado com sucesso.

:: ----- Criar pasta iso se nao existir -----
if not exist iso mkdir iso

:: ----- Iniciar servidor em background -----
echo  [2/3] Iniciando servidor 4MCSERVER...
start /b 4mcserver.exe

:: ----- Aguardar o servidor subir ANTES de abrir o browser -----
echo  Aguardando servidor inicializar...
timeout /t 3 /nobreak >nul

:: ----- Abrir navegador APOS o servidor estar no ar -----
echo  [3/3] Abrindo Painel de Controle no navegador...
start "" "http://localhost:8080"

echo.
echo  ================================================================
echo    4MCSERVER ativo!
echo    Painel: http://localhost:8080
echo    Jogue ISOs na pasta:  %~dp0iso\
echo    Pressione qualquer tecla para ENCERRAR o servidor.
echo  ================================================================
echo.
pause >nul

:: ----- Encerrar ao pressionar tecla -----
echo  Encerrando servidores...
taskkill /F /IM 4mcserver.exe >nul 2>&1
echo  4MCSERVER encerrado.
timeout /t 2 /nobreak >nul
