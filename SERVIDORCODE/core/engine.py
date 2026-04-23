import os
import shutil
import re
import subprocess

class HookEngine:
    def __init__(self, base_dir, config):
        self.base_dir = base_dir
        self.config = config
        self.extracted_dir = os.path.join(base_dir, 'data', 'extracted')
        self.isos_dir = os.path.join(base_dir, 'data', 'isos')
        self.boot_dir = os.path.join(base_dir, 'boot')
        os.makedirs(self.extracted_dir, exist_ok=True)
        os.makedirs(self.isos_dir, exist_ok=True)

    def _is_strelec(self, target_dir):
        """Detecta se a ISO extraida eh do tipo Sergei Strelec."""
        return os.path.isdir(os.path.join(target_dir, 'SSTR')) or os.path.isfile(os.path.join(target_dir, 'winpeshl.ini'))

    def prepare_iso(self, iso_name):
        """Extrai os arquivos de boot de uma ISO usando PowerShell com busca recursiva."""
        key = re.sub(r"[^a-z0-9_]", "", iso_name.replace('.iso', '').lower())
        iso_path = os.path.join(self.isos_dir, iso_name)
        target_dir = os.path.join(self.extracted_dir, key)
        os.makedirs(target_dir, exist_ok=True)

        ps_cmd = f"""
        $iso = '{iso_path}';
        Mount-DiskImage -ImagePath $iso;
        $vi = Get-DiskImage -ImagePath $iso | Get-Volume;
        if ($vi) {{
            $d = $vi.DriveLetter + ':';
            # Lista de arquivos para buscar em qualquer lugar da ISO
            $targets = @{{
                'bootmgr' = 'bootmgr';
                'boot.sdi' = 'boot.sdi';
                'BCD' = 'BCD';
                'boot.wim' = 'boot.wim';
                'bootx64.efi' = 'bootx64.efi';
                'bootmgfw.efi' = 'bootmgfw.efi';
            }}
            foreach ($t in $targets.Keys) {{
                $f = Get-ChildItem -Path $d -Filter $targets[$t] -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1;
                if ($f) {{
                    $dest = Join-Path '{target_dir}' $t;
                    if (Test-Path $dest) {{ attrib -R $dest; rm $dest -Force; }}
                    cp $f.FullName $dest -Force;
                }}
            }}
            # SMART WIM DETECTION: Se nao achou 'boot.wim', pega o maior arquivo .wim (Sistema)
            if (-not (Test-Path (Join-Path '{target_dir}' 'boot.wim'))) {{
                $maxWim = Get-ChildItem -Path $d -Filter *.wim -Recurse -ErrorAction SilentlyContinue | Sort-Object Length -Descending | Select-Object -First 1;
                if ($maxWim) {{
                    cp $maxWim.FullName (Join-Path '{target_dir}' 'boot.wim') -Force;
                }}
            }}
            # Fallback UEFI
            if (Test-Path (Join-Path '{target_dir}' 'bootmgfw.efi')) {{
                if (-not (Test-Path (Join-Path '{target_dir}' 'bootx64.efi'))) {{
                    cp (Join-Path '{target_dir}' 'bootmgfw.efi') (Join-Path '{target_dir}' 'bootx64.efi') -Force;
                }}
            }}
            Dismount-DiskImage -ImagePath $iso;
            return 'OK';
        }}
        return 'ERRO';
        """
        try:
            subprocess.run(['powershell', '-Command', ps_cmd], check=True)
            return True
        except:
            return False

    def generate_hooks(self, key, target_dir, iso_name):
        server_ip = self.config.get("server_ip", "192.168.0.21")
        is_strelec = self._is_strelec(target_dir)

        # 1. Gerar o hook.cmd (The Universal Hook)
        hook_cmd_content = f"""@echo off
color 0b
echo ====================================================
echo   FAST HTTPDisk Engine - Hook Executing
echo   ISO: {iso_name} | Servidor: {server_ip}
echo ====================================================
echo.
echo [1] Ajustando Rede e Drivers...
wpeinit
ping -n 5 {server_ip} >nul

echo [2] Registrando Kernel Driver (httpdisk.sys)...
sc create HttpDisk binpath= "X:\\Windows\\System32\\drivers\\httpdisk.sys" type= kernel start= demand 2>nul
sc start HttpDisk

echo [3] Montando ISO via HTTP (Range Request)...
X:\\Windows\\System32\\httpdisk.exe /mount 0 http://{server_ip}:{self.config.get('http_port', 80)}/data/isos/{iso_name} /size 0 Y:

echo.
timeout /t 2 >nul
if exist Y:\\ (
    echo [SUCESSO] ISO virtual Y: montada!
    if exist Y:\\SSTR\\MInst\\MInst.exe (
        echo [INFO] WinPE Strelec Detectado.
        pecmd.exe MAIN %SystemRoot%\\System32\\pecmd.ini
    ) else if exist Y:\\setup.exe (
        echo [INFO] Iniciando Instalacao do Windows...
        Y:\\setup.exe
    ) else if exist Y:\\sources\\setup.exe (
        echo [INFO] Iniciando Instalacao do Windows (sources)...
        Y:\\sources\\setup.exe
    ) else (
        echo [AVISO] Setup nao encontrado. Abrindo Explorer.
        start explorer.exe Y:\\
    )
) else (
    echo [ERRO FATAL] Falha ao montar o disco Y:. 
    echo Verifique o servidor e o arquivo: {iso_name}
    pause
    cmd.exe
)
"""
        with open(os.path.join(target_dir, 'hook.cmd'), 'w', encoding='utf-8') as f:
            f.write(hook_cmd_content)

        # 1.5 Gerar o startnet.cmd
        startnet_content = f"@echo off\nX:\\Windows\\System32\\hook.cmd\n"
        with open(os.path.join(target_dir, 'startnet.cmd'), 'w', encoding='utf-8') as f:
            f.write(startnet_content)

        # 1.6 Gerar o winpeshl.ini
        winpeshl_content = f"[LaunchApps]\nX:\\Windows\\System32\\hook.cmd\n"
        with open(os.path.join(target_dir, 'winpeshl.ini'), 'w', encoding='utf-8') as f:
            f.write(winpeshl_content)

        # 2. PECMD Hook (Direto no local correto)
        if is_strelec:
            pecmd_content = f"""# Strelec Seizure
EXEC =!CMD.EXE /C "X:\\Windows\\System32\\hook.cmd"
IF EX Y:\\SSTR\\pecmd.ini,LOAD Y:\\SSTR\\pecmd.ini
"""
            with open(os.path.join(target_dir, 'pecmd.ini'), 'w', encoding='utf-8') as f:
                f.write(pecmd_content)

        base_url = f"http://{server_ip}:{self.config.get('http_port', 80)}"

        # 3. Gerar menu.ipxe Entry com Mapeamento de Path (Crucial para UEFI)
        entry = f""":{key}
# Fast HTTPDisk: {key}
kernel {base_url}/boot/wimboot gui rawbcd
initrd {base_url}/virtual/{key}/bootmgr      bootmgr
initrd {base_url}/virtual/{key}/bootx64.efi  bootx64.efi
initrd {base_url}/virtual/{key}/BCD          boot/bcd
initrd {base_url}/virtual/{key}/BCD          EFI/Microsoft/Boot/BCD
initrd {base_url}/virtual/{key}/boot.sdi      boot/boot.sdi
"""
        if is_strelec:
            # Strelec precisa do WIM em um caminho chato
            entry += f"initrd {base_url}/virtual/{key}/boot.wim   SSTR/system/SSTR10X64.WIM\n"
            entry += f"initrd {base_url}/virtual/{key}/pecmd.ini  Windows/System32/pecmd.ini\n"
        else:
            entry += f"initrd {base_url}/virtual/{key}/boot.wim   sources/boot.wim\n"

        entry += f"""initrd {base_url}/virtual/{key}/hook.cmd      Windows/System32/hook.cmd
initrd {base_url}/virtual/{key}/startnet.cmd  Windows/System32/startnet.cmd
initrd {base_url}/virtual/{key}/winpeshl.ini  Windows/System32/winpeshl.ini
initrd {base_url}/boot/httpdisk.sys      Windows/System32/drivers/httpdisk.sys
initrd {base_url}/boot/httpdisk.exe      Windows/System32/httpdisk.exe
boot
"""
        return entry

    def rebuild_menu(self):
        server_ip = self.config.get("server_ip", "192.168.0.21")
        menu_path = os.path.join(self.boot_dir, 'menu.ipxe')
        content = "#!ipxe\n:start\nmenu Fast HTTPDisk PXE Root\n"
        entries = []
        for iso in os.listdir(self.isos_dir):
            if iso.lower().endswith('.iso'):
                # Permitir underline para bater com o prepare_iso
                key = re.sub(r"[^a-z0-9_]", "", iso.replace('.iso', '').lower())
                target_dir = os.path.join(self.extracted_dir, key)
                if os.path.isdir(target_dir):
                    content += f"item {key} Boot: {iso}\n"
                    entries.append(self.generate_hooks(key, target_dir, iso))
        content += "item reboot Reboot\nchoose target && goto ${target}\n:reboot\nreboot\n"
        for e in entries: content += "\n" + e
        with open(menu_path, 'w', encoding='utf-8') as f: f.write(content)
        return True
