import os
import subprocess
import logging
import shutil

class ISOManager:
    def __init__(self, config, logger=None):
        self.config = config
        self.iso_dir = config["iso_dir"]
        self.extract_dir = config["extract_dir"]
        self.boot_dir = config["boot_dir"]
        self.logger = logger or logging.getLogger("ISO")
        os.makedirs(self.extract_dir, exist_ok=True)
        os.makedirs(self.boot_dir, exist_ok=True)

    def find_strelec_iso(self):
        # Look for the ISO on all available drives (D:, E:, F:, ...)
        import string
        drives = [f"{d}:" for d in string.ascii_uppercase if os.path.exists(f"{d}:")]
        
        self.logger.info(f"Scanning drives for STRELEC.ISO: {drives}")
        for d in drives:
            try:
                root_files = os.listdir(d)
                strelec = [f for f in root_files if f.lower().endswith(".iso") and "strelec" in f.lower()]
                if strelec:
                    iso_path = os.path.join(d, strelec[0])
                    self.logger.info(f"Found Strelec ISO at: {iso_path}")
                    return iso_path
            except:
                continue
        return None

    def extract_strelec(self, iso_path):
        target = os.path.join(self.extract_dir, "strelec")
        os.makedirs(target, exist_ok=True)
        
        if os.path.exists(os.path.join(target, "boot.wim")):
            self.logger.info("Strelec components already extracted.")
            return True

        self.logger.info(f"Extracting Strelec from {iso_path}...")
        
        # PowerShell script to extract specific files from ISO
        ps_cmd = f"""
        $iso = "{iso_path}"
        $target = "{target}"
        $mount = Mount-DiskImage -ImagePath $iso -PassThru -ErrorAction SilentlyContinue
        $drive = ($mount | Get-Volume).DriveLetter + ":"
        
        if (-not $drive) {{
            Write-Error "Could not mount or find drive letter for $iso"
            exit 1
        }}

        # Deep Search for the main Strelec WIM (could be in Root, /SSTR, or /sources)
        $wimFile = Get-ChildItem -Path "$drive" -Filter "*.wim" -Recurse | Sort-Object Length -Descending | Select-Object -First 1
        if ($wimFile) {{
            Copy-Item -Path $wimFile.FullName -Destination "$target\\boot.wim" -Force
            Write-Host "Extracted WIM: $($wimFile.Name)"
        }}

        # Find and Extract boot.sdi and BCD
        $sdi = Get-ChildItem -Path "$drive" -Filter "boot.sdi" -Recurse | Select-Object -First 1
        if ($sdi) {{ Copy-Item -Path $sdi.FullName -Destination "$target\\boot.sdi" -Force }}
        
        $bcd = Get-ChildItem -Path "$drive" -Filter "BCD" -Recurse | Select-Object -First 1
        if ($bcd) {{ Copy-Item -Path $bcd.FullName -Destination "$target\\BCD" -Force }}

        # Extract fonts for UEFI rendering stability
        $fontTarget = "$target\\Fonts"
        New-Item -ItemType Directory -Path $fontTarget -Force -ErrorAction SilentlyContinue
        $fontFolder = Get-ChildItem -Path "$drive" -Directory -Filter "Fonts" -Recurse | Select-Object -First 1
        if ($fontFolder) {{
            Copy-Item -Path "$($fontFolder.FullName)\\*" -Destination $fontTarget -Force -ErrorAction SilentlyContinue
        }}

        # Extract boot managers
        Copy-Item -Path "$drive\\bootmgr" -Destination "$target\\bootmgr" -Force -ErrorAction SilentlyContinue
        $bootx64 = Get-ChildItem -Path "$drive" -Filter "bootx64.efi" -Recurse | Select-Object -First 1
        if ($bootx64) {{ Copy-Item -Path $bootx64.FullName -Destination "$target\\bootx64.efi" -Force }}
        
        Dismount-DiskImage -ImagePath $iso -ErrorAction SilentlyContinue
        """
        

        try:
            subprocess.run(["powershell", "-Command", ps_cmd], check=True, capture_output=True)
            
            # Copy wimboot from boot_dir to the extracted strelec folder for HTTP access
            wimboot_src = os.path.join(self.boot_dir, "wimboot")
            wimboot_dst = os.path.join(target, "wimboot")
            if os.path.exists(wimboot_src):
                shutil.copy2(wimboot_src, wimboot_dst)
                self.logger.info("Copied wimboot to extraction folder.")

            self.logger.info("Successfully extracted Strelec components and fonts.")
            return True
        except Exception as e:
            self.logger.error(f"Extraction failed: {e}")
            return False

    def _get_font_lines(self, base_url):
        fonts = ['segmono_boot.ttf', 'segoe_slboot.ttf', 'wgl4_boot.ttf']
        lines = []
        for f in fonts:
            # Different paths the Windows Boot Manager might look for
            lines.append(f"initrd {base_url}/Fonts/{f} Fonts/{f}")
            lines.append(f"initrd {base_url}/Fonts/{f} SSTR/Fonts/{f}")
            lines.append(f"initrd {base_url}/Fonts/{f} EFI/Microsoft/Boot/Fonts/{f}")
        return lines

    def generate_menu(self):
        # Generate menu.ipxe for Sergei Strelec
        # Using Nielsen Heuristic #1: Visibility of System Status (detailed logs)
        # Using Advanced Aliasing to prevent 0xc000000f and UEFI distortion
        
        server_ip = self.config['server_ip']
        base = f"http://{server_ip}/strelec"
        
        font_lines = "\n".join(self._get_font_lines(base))
        
        menu = f"""#!ipxe
# PXEGEMINI Antigravity Boot Menu
# Optimized for Dell & Lenovo UEFI | Nielsen Heuristics Compliant

set server {server_ip}
set base {base}

:start
menu PXEGEMINI - Boot Sergei Strelec Engine
item strelec Sergei Strelec WinPE (UEFI/Legacy)
item shell iPXE Shell
item exit Reboot

choose target && goto ${{target}}

:strelec
# Using rawbcd to avoid iPXE re-patching which causes 0xc000000f
kernel ${{base}}/wimboot rawbcd

# Boot Managers Aliases
initrd ${{base}}/bootmgr bootmgr
initrd ${{base}}/bootmgr bootmgr.efi
initrd ${{base}}/bootx64.efi bootmgfw.efi
initrd ${{base}}/bootx64.efi EFI/Microsoft/Boot/bootmgfw.efi

# BCD & SDI Aliases (Critical for 0xc000000f)
initrd ${{base}}/BCD BCD
initrd ${{base}}/BCD boot/BCD
initrd ${{base}}/BCD SSTR/BCD
initrd ${{base}}/boot.sdi boot.sdi
initrd ${{base}}/boot.sdi boot/boot.sdi
initrd ${{base}}/boot.sdi SSTR/boot.sdi

# WinPE Main Image
initrd ${{base}}/boot.wim boot.wim
initrd ${{base}}/boot.wim sources/boot.wim
initrd ${{base}}/boot.wim SSTR/strelec11x64Eng.wim

# Rendering Stability (Fonts)
{font_lines}

boot

:shell
shell

:exit
reboot
"""
        try:
            with open(os.path.join(self.boot_dir, "menu.ipxe"), "w") as f:
                f.write(menu)
            self.logger.info("Generated advanced menu.ipxe with Asset Aliasing.")
        except Exception as e:
            self.logger.error(f"Failed to generate menu: {e}")
