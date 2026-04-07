import shutil
import os

# 1. Fix startnet.cmd for geminiiso
content = (
    "@echo off\n"
    "wpeinit\n"
    "echo [PXEGEMINI v5.1] Montando ISO via HTTPDisk...\n"
    "httpdisk.exe /mount 0 http://192.168.0.21/geminiiso/strelec.iso /size 0 Y:\n"
    "if exist Y:\\SSTR\\MInst\\MInst.exe (\n"
    "    echo [PXEGEMINI] Disco Virtual Y: Montado com Sucesso!\n"
    "    start Y:\\SSTR\\MInst\\MInst.exe\n"
    ") else (\n"
    "    echo [!] HTTPDisk falhou. Tentando Fallback SMB...\n"
    '    net use Z: \\\\192.168.0.21\\SSTR /user:Guest ""\n'
    "    if exist Z:\\MInst\\MInst.exe start Z:\\MInst\\MInst.exe\n"
    ")\n"
    "cmd.exe\n"
)

startnet_path = r"E:\PXEGEMINI\data\extracted\geminiiso\startnet.cmd"
with open(startnet_path, "w", encoding="utf-8") as f:
    f.write(content)
print(f"[OK] startnet.cmd escrito em {startnet_path}")

# 2. Replace boot.wim with DISM-modified version (has httpdisk driver in registry)
src_wim = r"E:\PXEGEMINI\strelec_httpdisk\boot.wim"
dst_wim = r"E:\PXEGEMINI\data\extracted\geminiiso\boot.wim"
src_size = os.path.getsize(src_wim) // 1024 // 1024
dst_size = os.path.getsize(dst_wim) // 1024 // 1024
print(f"[INFO] Substituindo boot.wim: {dst_size}MB -> {src_size}MB (DISM-modified)")
shutil.copy2(src_wim, dst_wim)
print(f"[OK] boot.wim substituido com sucesso!")

# 3. Verify httpdisk binaries are present
for binary in ["httpdisk.exe", "httpdisk.sys"]:
    p = os.path.join(r"E:\PXEGEMINI\data\extracted\geminiiso", binary)
    if os.path.isfile(p):
        print(f"[OK] {binary} presente ({os.path.getsize(p)} bytes)")
    else:
        # Copy from boot dir
        src_b = os.path.join(r"E:\PXEGEMINI\boot", binary)
        if os.path.isfile(src_b):
            shutil.copy2(src_b, p)
            print(f"[OK] {binary} copiado de boot/")
        else:
            print(f"[ERRO] {binary} NAO encontrado!")

print("\n=== CONFIGURACAO HTTPDISK COMPLETA ===")
print("Reinicie o PXEGEMINI e tente o boot novamente.")
