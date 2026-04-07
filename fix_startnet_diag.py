import os

# Startnet.cmd DIAGNOSTICO - mostra tudo na tela para depuracao
content = (
    "@echo off\n"
    "color 0A\n"
    "cls\n"
    "echo ============================================\n"
    "echo  PXEGEMINI v5.1 - HTTPDisk Boot Diagnostico\n"
    "echo ============================================\n"
    "echo.\n"
    "echo [1/4] Iniciando wpeinit...\n"
    "wpeinit\n"
    "echo [1/4] wpeinit OK\n"
    "echo.\n"
    "echo [2/4] Registrando servico HttpDisk...\n"
    "sc create HttpDisk binpath= system32\\drivers\\httpdisk.sys type= kernel start= demand 2>nul\n"
    "sc start HttpDisk\n"
    "echo Resultado sc start: %errorlevel%\n"
    "echo.\n"
    "echo [3/4] Montando ISO via HTTPDisk...\n"
    "echo URL: http://192.168.0.21/geminiiso/strelec.iso\n"
    "httpdisk.exe /mount 0 http://192.168.0.21/geminiiso/strelec.iso /size 0 Y:\n"
    "echo Resultado /mount: %errorlevel%\n"
    "echo.\n"
    "echo [4/4] Verificando Y:\\SSTR\\MInst\\MInst.exe ...\n"
    "if exist Y:\\SSTR\\MInst\\MInst.exe (\n"
    "    echo [SUCESSO] Disco Y: montado! MInst encontrado.\n"
    "    echo Iniciando MInst...\n"
    "    start Y:\\SSTR\\MInst\\MInst.exe\n"
    ") else (\n"
    "    echo [FALHOU] Y:\\SSTR\\MInst\\MInst.exe nao encontrado.\n"
    "    echo.\n"
    "    echo Conteudo do disco Y: (se montado):\n"
    "    dir Y:\\ 2>&1\n"
    "    echo.\n"
    "    echo Tentando fallback SMB...\n"
    '    net use Z: \\\\\\\\192.168.0.21\\\\SSTR /user:Guest ""\n'
    "    dir Z:\\ 2>&1\n"
    ")\n"
    "echo.\n"
    "echo ============================================\n"
    "echo  FIM DO DIAGNOSTICO - Tire uma foto desta tela\n"
    "echo ============================================\n"
    "pause\n"
    "cmd.exe\n"
)

path = r"E:\PXEGEMINI\data\extracted\geminiiso\startnet.cmd"
with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print(f"[OK] startnet.cmd DIAGNOSTICO escrito em {path}")
print("[OK] Reinicie o PXEGEMINI e tire foto da tela preta durante o boot!")
