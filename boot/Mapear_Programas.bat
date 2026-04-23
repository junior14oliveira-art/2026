@echo off
title Mapeando Ferramentas Strelec via PXEGEMINI...
echo Aguardando a rede inicializar (10 segundos)...
ping 127.0.0.1 -n 10 > nul

echo.
echo Tentando mapear servidor PXE (192.168.0.21)...
net use Y: \\192.168.0.21\SSTR /user:Guest "" 

if exist Y:\MInst\ (
    echo.
    echo [SUCESSO] Os programas do Strelec foram conectados com sucesso na unidade Y: !!!
    echo.
    echo Iniciando o Menu de Ferramentas (MInst.exe)...
    
    :: Mudar para o drive mapeado e iniciar o launcher do Strelec
    Y:
    cd \SSTR\MInst\
    start MInst.exe
    
    echo O Macrium e o Start Menu estarao carregados agora!
) else (
    echo.
    echo [ERRO] Nao foi possivel mapear os programas. Verifique o Firewall do servidor.
    pause
    exit
)
echo.
timeout /t 5
