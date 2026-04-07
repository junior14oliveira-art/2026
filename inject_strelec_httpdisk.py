import os
import shutil

base = r'E:\PXEGEMINI\data\extracted'
strelec_dir = os.path.join(base, 'strelec')
geminiiso_dir = os.path.join(base, 'geminiiso')
boot_dir = r'E:\PXEGEMINI\boot'

print("=== Injetando HTTPDisk na pasta /strelec/ ===\n")

# 1. Listar o que tem no strelec
print("Conteudo atual de /strelec/:")
for f in os.listdir(strelec_dir):
    print(f"  {f}")
print()

# 2. Copiar boot.wim com HTTPDisk do geminiiso
src_wim = os.path.join(geminiiso_dir, 'boot.wim')
dst_wim = os.path.join(strelec_dir, 'boot.wim')
if os.path.isfile(src_wim):
    print(f"Copiando boot.wim DISM-modificado ({os.path.getsize(src_wim)//1024//1024} MB)...")
    shutil.copy2(src_wim, dst_wim)
    print(f"[OK] boot.wim -> {dst_wim}")
else:
    print("[ERRO] boot.wim nao encontrado em geminiiso!")

# 3. Copiar httpdisk.exe e httpdisk.sys
for binary in ['httpdisk.exe', 'httpdisk.sys']:
    src = os.path.join(boot_dir, binary)
    dst = os.path.join(strelec_dir, binary)
    if os.path.isfile(src):
        shutil.copy2(src, dst)
        print(f"[OK] {binary} copiado -> strelec/")
    elif os.path.isfile(os.path.join(geminiiso_dir, binary)):
        shutil.copy2(os.path.join(geminiiso_dir, binary), dst)
        print(f"[OK] {binary} copiado de geminiiso -> strelec/")
    else:
        print(f"[ERRO] {binary} nao encontrado!")

# 4. Copiar wimboot
src_wb = os.path.join(boot_dir, 'wimboot')
dst_wb = os.path.join(strelec_dir, 'wimboot')
if os.path.isfile(src_wb):
    shutil.copy2(src_wb, dst_wb)
    print(f"[OK] wimboot copiado -> strelec/")

# 5. Copiar boot.sdi e bootx64.efi do geminiiso se nao existir
for f in ['boot.sdi', 'bootx64.efi', 'bootmgr', 'BCD']:
    src = os.path.join(geminiiso_dir, f)
    dst = os.path.join(strelec_dir, f)
    if os.path.isfile(src) and not os.path.isfile(dst):
        shutil.copy2(src, dst)
        print(f"[OK] {f} copiado -> strelec/")
    elif os.path.isfile(dst):
        print(f"[--] {f} ja existe em strelec/")

# 6. Escrever startnet.cmd para /strelec/ apontar para o ISO certo
startnet_content = (
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
    "    start Y:\\SSTR\\MInst\\MInst.exe\n"
    ") else (\n"
    "    echo [FALHOU] Y:\\SSTR\\MInst\\MInst.exe nao encontrado.\n"
    "    echo Conteudo de Y:\n"
    "    dir Y:\\ 2>&1\n"
    "    echo.\n"
    "    echo Tentando fallback SMB...\n"
    '    net use Z: \\\\192.168.0.21\\SSTR /user:Guest ""\n'
    "    dir Z:\\ 2>&1\n"
    ")\n"
    "echo.\n"
    "echo FIM DO DIAGNOSTICO - Tire uma foto desta tela\n"
    "pause\n"
    "cmd.exe\n"
)

startnet_path = os.path.join(strelec_dir, 'startnet.cmd')
with open(startnet_path, 'w', encoding='utf-8') as f:
    f.write(startnet_content)
print(f"[OK] startnet.cmd (diagnostico) -> strelec/")

# 7. Copiar Fonts do geminiiso se existir
fonts_src = os.path.join(geminiiso_dir, 'Fonts')
fonts_dst = os.path.join(strelec_dir, 'Fonts')
if os.path.isdir(fonts_src) and not os.path.isdir(fonts_dst):
    shutil.copytree(fonts_src, fonts_dst)
    print(f"[OK] Fonts/ copiada -> strelec/")
elif os.path.isdir(fonts_dst):
    print(f"[--] Fonts/ ja existe em strelec/")

print("\n=== PRONTO! Liste final de strelec/: ===")
for f in sorted(os.listdir(strelec_dir)):
    fp = os.path.join(strelec_dir, f)
    sz = os.path.getsize(fp) if os.path.isfile(fp) else -1
    label = f'{sz//1024//1024} MB' if sz > 1024*1024 else (f'{sz} B' if sz >= 0 else 'DIR')
    print(f"  {f} [{label}]")

print("\nReinicie o PXEGEMINI e tente o boot!")
