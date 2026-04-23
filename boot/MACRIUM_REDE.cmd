@echo off
setlocal EnableExtensions
title MACRIUM REFLECT VIA REDE - PXEGEMINI
color 1F

:: Configurações de caminhos baseadas na estrutura do Sergei Strelec
set "SSTR_DRIVE=Y:"
set "SSTR_PATH=Y:\SSTR"
set "PORTABLE_BASE=%SSTR_PATH%\MInst\Portable"

echo [PXEGEMINI] Buscando Macrium Reflect...

:: Possíveis caminhos do executável (v7, v8, x64, x86)
set "MACRIUM_PATHS[0]=%PORTABLE_BASE%\x64\MacriumReflect8_x64.exe"
set "MACRIUM_PATHS[1]=%PORTABLE_BASE%\x64\MacriumReflect_x64.exe"
set "MACRIUM_PATHS[2]=%PORTABLE_BASE%\x86\MacriumReflect_x86.exe"
set "MACRIUM_PATHS[3]=%PORTABLE_BASE%\x64\Reflect8_x64.exe"

set "FOUND="

for /L %%i in (0,1,3) do (
    call set "CANDIDATE=%%MACRIUM_PATHS[%%i]%%"
    if exist "!CANDIDATE!" (
        set "FOUND=!CANDIDATE!"
        goto :launch
    )
)

:: Se não encontrou no Y: (HTTPDisk), tenta no Z: (SMB)
if not defined FOUND (
    echo [!] Nao encontrado em Y:, tentando em Z: (SMB)...
    set "PORTABLE_BASE=Z:\MInst\Portable"
    if exist "Z:\MInst\Portable\" (
        if exist "Z:\MInst\Portable\x64\MacriumReflect8_x64.exe" set "FOUND=Z:\MInst\Portable\x64\MacriumReflect8_x64.exe"
        if exist "Z:\MInst\Portable\x64\MacriumReflect_x64.exe" set "FOUND=Z:\MInst\Portable\x64\MacriumReflect_x64.exe"
    )
)

:launch
if defined FOUND (
    echo [OK] Macrium encontrado: %FOUND%
    echo [PXEGEMINI] Iniciando aplicativo...
    start "" "%FOUND%"
    exit /b 0
) else (
    echo [ERRO] Macrium Reflect nao foi localizado na estrutura SSTR.
    echo Certifique-se de que a ISO do Strelec esta completa.
    pause
    exit /b 1
)
