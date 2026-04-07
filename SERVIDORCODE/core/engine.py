import os
import shutil
import re
import socket

class HookEngine:
    def __init__(self, base_dir, config):
        self.base_dir = base_dir
        self.config = config
        self.extracted_dir = os.path.join(base_dir, 'data', 'extracted')
        self.isos_dir = os.path.join(base_dir, 'data', 'isos')
        self.boot_dir = os.path.join(base_dir, 'boot')
        os.makedirs(self.extracted_dir, exist_ok=True)
        os.makedirs(self.isos_dir, exist_ok=True)

    def prepare_environment(self, iso_filename):
        """
        Extremely stripped-down prepare that simulates the user dropping an ISO and unpacking.
        For SERVIDORCODE, we assume the user already has standard WinPE structure scattered, or we extract it.
        We'll just map the existing ISO for HTTPDisk and generate the Hooks.
        """
        key = iso_filename.replace('.iso', '').lower()
        if not re.match("^[a-z0-9_]+$", key):
            key = re.sub(r"[^a-z0-9_]", "", key)
            
        target_dir = os.path.join(self.extracted_dir, key)
        os.makedirs(target_dir, exist_ok=True)
        
        # In a real scenario we use 7zip. For our focused test, we assume the user puts boot.wim in the target_dir.
        return key, target_dir

    def generate_hooks(self, key, target_dir, iso_name):
        """
        Gera os arquivos de Hook Absoluto (winpeshl.ini e hook.cmd) e atualiza o IPXE menu.
        """
        server_ip = self.config.get("server_ip", "192.168.0.21")
        
        # 1. Gerar o hook.cmd (The Absolute Hook)
        hook_cmd_content = f"""@echo off
color 0b
echo ====================================================
echo   FAST HTTPDisk Engine - Hook Executing (SYSTEM)
echo ====================================================
echo.
echo [1] Ajustando Rede...
wpeinit

echo [2] Registrando Kernel Driver (httpdisk.sys)...
sc create HttpDisk binpath= system32\\drivers\\httpdisk.sys type= kernel start= demand 2>nul
sc start HttpDisk

echo [3] Montando Arquivo Bruto ISO via Server Range Request...
httpdisk.exe /mount 0 http://{server_ip}/data/isos/{iso_name} /size 0 Y:

echo.
if exist Y:\\SSTR\\MInst\\MInst.exe (
    echo [SUCESSO] ISO virtual Y: montada e disponivel em velocidade total!
    echo Transferindo controle para Sergei Strelec (PEcmd)...
    start pecmd.exe MAIN %SystemRoot%\\System32\\pecmd.ini
) else (
    echo [ERRO] Falha no HTTPDisk ou formato incorreto.
    echo Caimos pro modo de depuracao local...
    cmd.exe
)
"""
        with open(os.path.join(target_dir, 'hook.cmd'), 'w', encoding='utf-8') as f:
            f.write(hook_cmd_content)

        # 2. Gerar winpeshl.ini fajuto
        winpeshl_content = """[LaunchApps]
%SystemRoot%\\System32\\hook.cmd
"""
        with open(os.path.join(target_dir, 'winpeshl.ini'), 'w', encoding='utf-8') as f:
            f.write(winpeshl_content)

        # 3. Gerar menu.ipxe Entry
        entry = f""":{key}
# Fast HTTPDisk: {key}
kernel http://{server_ip}/boot/wimboot rawbcd
initrd http://{server_ip}/virtual/bootmgr bootmgr
initrd http://{server_ip}/virtual/bootmgr bootmgr.efi
initrd http://{server_ip}/virtual/bootx64.efi bootmgfw.efi
initrd http://{server_ip}/virtual/bootx64.efi EFI/Microsoft/Boot/bootmgfw.efi
initrd http://{server_ip}/virtual/BCD BCD
initrd http://{server_ip}/virtual/BCD boot/BCD
initrd http://{server_ip}/virtual/boot.sdi boot.sdi
initrd {server_ip}/virtual/boot.sdi boot/boot.sdi
initrd http://{server_ip}/virtual/boot.wim boot.wim
initrd http://{server_ip}/virtual/boot.wim sources/boot.wim

# Injecting The Absolute Hook
initrd http://{server_ip}/virtual/hook.cmd hook.cmd
initrd http://{server_ip}/virtual/hook.cmd Windows/System32/hook.cmd
initrd http://{server_ip}/virtual/winpeshl.ini winpeshl.ini
initrd http://{server_ip}/virtual/winpeshl.ini Windows/System32/winpeshl.ini

# Injecting Drivers
initrd http://{server_ip}/boot/httpdisk.sys httpdisk.sys
initrd http://{server_ip}/boot/httpdisk.sys Windows/System32/drivers/httpdisk.sys
initrd http://{server_ip}/boot/httpdisk.exe httpdisk.exe
initrd http://{server_ip}/boot/httpdisk.exe Windows/System32/httpdisk.exe

boot
"""
        return entry

    def rebuild_menu(self):
        server_ip = self.config.get("server_ip", "192.168.0.21")
        menu_path = os.path.join(self.boot_dir, 'menu.ipxe')
        
        content = f"""#!ipxe
# SERVIDORCODE - PXE Fast HTTPDisk Menu

:start
menu Fast HTTPDisk PXE Root
item --gap --             -------------------------
"""
        entries = []
        
        # Procurar ISOs preparadas
        for iso in os.listdir(self.isos_dir):
            if iso.lower().endswith('.iso'):
                key = iso.replace('.iso', '').lower()
                target_dir = os.path.join(self.extracted_dir, key)
                if os.path.isdir(target_dir):
                    content += f"item {key} Boot via HTTPDisk: {iso}\n"
                    entries.append(self.generate_hooks(key, target_dir, iso))

        content += """item reboot Reiniciar Servidor
choose target && goto ${target}

:reboot
reboot
"""
        for e in entries:
            content += "\n" + e

        with open(menu_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return True
