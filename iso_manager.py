import os
import subprocess
import logging
import shutil
import string
import re

class ISOManager:
    """Gerencia multiplas ISOs: scan, deteccao de tipo, extracao e geracao dinamica do menu.ipxe."""

    # Tipos de ISO suportados
    TYPE_WIMBOOT = "wimboot"       # WinPE (Strelec, Win10/11 PE, etc)
    TYPE_LINUX_ISO = "linux"       # Linux com vmlinuz + initrd
    TYPE_LINUX_SQUASHFS = "squashfs"  # Ubuntu/Debian live (casar vmlinuz + filesystem.squashfs)
    TYPE_UEFI_DIRECT = "uefi"      # Ha bootx64.efi direto na ISO
    TYPE_UNKNOWN = "unknown"
    TYPE_MEMDISK = "memdisk"       # Fallback: boot via memdisk (ISO pequena)

    def __init__(self, config, logger=None):
        self.config = config
        self.iso_dir = config.get("iso_dir", "E:\\")
        self.extract_dir = config.get("extract_dir", os.path.join("data", "extracted"))
        self.boot_dir = config.get("boot_dir", "boot")
        self.logger = logger or logging.getLogger("ISO")
        os.makedirs(self.extract_dir, exist_ok=True)
        os.makedirs(self.boot_dir, exist_ok=True)

    # ===================== SCANNING =====================

    def find_all_isos(self, scan_dir=None):
        """Busca TODAS as ISOs em todos os drives acessiveis (nao so Strelec)."""
        if scan_dir:
            drives = [scan_dir]
        else:
            drives = [f"{d}:" for d in string.ascii_uppercase if os.path.exists(f"{d}:")]

        found = []
        for d in drives:
            try:
                for root, dirs, files in os.walk(d):
                    # Pula diretorios grandes que nao tem ISO
                    dirs[:] = [x for x in dirs if x.lower() not in ("windows", "program files", "programdata", "$recycle.bin")]
                    for f in files:
                        if f.lower().endswith(".iso"):
                            full = os.path.join(root, f)
                            try:
                                size_mb = os.path.getsize(full) / (1024 * 1024)
                            except OSError:
                                size_mb = 0
                            found.append({"path": full, "name": f, "size_mb": size_mb})
                    # Limita profundidade para nao travar
                    if len(root) - len(d) > 3 * max(len(x) for x in os.sep.split("/") if x):
                        dirs.clear()
            except (PermissionError, OSError):
                continue
        return found

    def find_isos_in_dir(self, target_dir):
        """Busca ISOs em um diretorio especifico."""
        result = []
        if not os.path.isdir(target_dir):
            return result
        for root, dirs, files in os.walk(target_dir):
            dirs[:] = [x for x in dirs if x.lower() not in ("$recycle.bin", "system volume information")]
            for f in files:
                if f.lower().endswith(".iso"):
                    full = os.path.join(root, f)
                    try:
                        size_mb = os.path.getsize(full) / (1024 * 1024)
                    except OSError:
                        size_mb = 0
                    result.append({"path": full, "name": f, "size_mb": size_mb})
        return result

    # ===================== DETECTION =====================

    def detect_iso_type(self, iso_path):
        """Detecta o tipo de boot da ISO montando e inspecionando conteudo."""
        drive = self._mount_iso(iso_path)
        if not drive:
            # Fallback: tenta pelo nome
            name = os.path.basename(iso_path).lower()
            if "strelec" in name or "winpe" in name or "win10" in name or "win11" in name:
                return self.TYPE_WIMBOOT
            if "ubuntu" in name or "debian" in name or "mint" in name or "kali" in name:
                return self.TYPE_LINUX_SQUASHFS
            return self.TYPE_UNKNOWN

        try:
            contents = self._list_iso_contents(drive)
            return self._classify_contents(contents, drive)
        finally:
            self._unmount_iso(iso_path)

    def _classify_contents(self, contents, drive):
        """Analisa arquivos da ISO montada para determinar o tipo."""
        lower_map = {x.lower(): x for x in contents}

        # WinPE: tem .wim
        wim_files = [f for f in contents if f.lower().endswith(".wim")]
        if wim_files:
            return self.TYPE_WIMBOOT

        # Linux live: vmlinuz ou bzImage
        has_kernel = any(re.match(r"(?i)(vmlinuz|bzImage|vmlinux|linux.*)", f) for f in contents)
        has_initrd = any(re.match(r"(?i)(initrd|initramfs)", f) for f in contents)

        # Ubuntu/Debian live style
        squash_files = [f for f in contents if f.lower().endswith(".squashfs")]
        if has_kernel and squash_files:
            return self.TYPE_LINUX_SQUASHFS

        if has_kernel and has_initrd:
            return self.TYPE_LINUX_ISO

        # UEFI direto
        if "EFI" in lower_map:
            efi_dir_contents = []
            efi_path = os.path.join(drive, "EFI")
            try:
                for root, dirs, files in os.walk(efi_path):
                    for f in files:
                        if f.lower().endswith(".efi"):
                            efi_dir_contents.append(f)
            except OSError:
                pass
            if efi_dir_contents:
                return self.TYPE_UEFI_DIRECT

        # Fallback: procura bootx64.efi em qualquer lugar
        efi_any = [f for f in contents if f.lower().endswith(".efi")]
        if efi_any:
            return self.TYPE_UEFI_DIRECT

        # ISO pequena -> memdisk
        return self.TYPE_UNKNOWN

    # ===================== MOUNT/UNMOUNT =====================

    def _mount_iso(self, iso_path):
        """Monta a ISO em disco, retorna a letra da unidade ou None."""
        ps_cmd = f"""
        Mount-DiskImage -ImagePath "{iso_path}" -ErrorAction Stop | Get-Volume | Select-Object -ExpandProperty DriveLetter
        """
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=30,
            )
            letter = result.stdout.strip().strip()
            if letter and len(letter) == 1 and letter.isalpha():
                return letter + ":"
        except Exception as e:
            self.logger.warning(f"Mount falhou: {e}")
        return None

    def _unmount_iso(self, iso_path):
        """Desmonta a ISO."""
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f'Dismount-DiskImage -ImagePath "{iso_path}" -ErrorAction SilentlyContinue'],
                capture_output=True, text=True, timeout=15,
            )
        except Exception:
            pass

    def _list_iso_contents(self, drive):
        """Lista arquivos no root da ISO montada."""
        try:
            return os.listdir(drive)
        except OSError:
            return []

    # ===================== EXTRACTION =====================

    def add_iso(self, iso_info):
        """
        Adiciona uma ISO ao sistema.
        Retorna dict com {"success": bool, "key": str, "type": str, "error": str}.
        `key` e o nome de pasta interno usado pelo menu.
        """
        iso_path = iso_info["path"]
        iso_name = iso_info["name"]
        # Gera chave unica baseada no nome (sem .iso)
        key = re.sub(r"[^a-zA-Z0-9_-]", "_", os.path.splitext(iso_name)[0])
        target = os.path.join(self.extract_dir, key)
        os.makedirs(target, exist_ok=True)

        # Verifica se ja existe (pula extracao se sim, mas atualiza menu)
        marker = os.path.join(target, ".pxegemini_type")
        if os.path.exists(marker):
            with open(marker, "r") as f:
                prev_type = f.read().strip()
            self.logger.info(f"ISO '{iso_name}' ja adicionada (tipo={prev_type}).")
            return {"success": True, "key": key, "type": prev_type, "error": ""}

        iso_type = self.detect_iso_type(iso_path)
        self.logger.info(f"Detected ISO '{iso_name}' tipo={iso_type}")

        drive = self._mount_iso(iso_path)
        try:
            if not drive:
                self.logger.error(f"Nao foi possivel montar a ISO: {iso_name}")
                return {"success": False, "key": key, "type": iso_type, "error": "Nao foi possivel montar a ISO"}

            if iso_type == self.TYPE_WIMBOOT:
                result = self._extract_wimboot(drive, target)
            elif iso_type == self.TYPE_LINUX_ISO:
                result = self._extract_linux(drive, target)
            elif iso_type == self.TYPE_LINUX_SQUASHFS:
                result = self._extract_linux_squashfs(drive, target, drive)
            elif iso_type == self.TYPE_UEFI_DIRECT:
                result = self._extract_uefi_direct(drive, target)
            else:
                self.logger.warning(f"Tipo desconhecido para {iso_name}, tentando extrair como memdisk fallback.")
                result = self._extract_unknown(drive, target)

            if result:
                # Salva marker
                with open(marker, "w") as f:
                    f.write(iso_type)
                # Salva metadata
                with open(os.path.join(target, ".pxegemini_meta"), "w", encoding="utf-8") as f:
                    f.write(f"name={iso_name}\npath={iso_path}\nkey={key}\ntype={iso_type}\n")
                # Copia wimboot para a pasta se existir no boot_dir
                wimboot_src = os.path.join(self.boot_dir, "wimboot")
                if os.path.exists(wimboot_src) and iso_type == self.TYPE_WIMBOOT:
                    shutil.copy2(wimboot_src, os.path.join(target, "wimboot"))
                self.logger.info(f"ISO '{iso_name}' adicionada com sucesso (key={key}, type={iso_type}).")
                return {"success": True, "key": key, "type": iso_type, "error": ""}
            else:
                return {"success": False, "key": key, "type": iso_type, "error": "Extracao falhou"}
        finally:
            if drive:
                self._unmount_iso(iso_path)

    # ===================== WIMBOOT EXTRACTION =====================

    def _extract_wimboot(self, drive, target):
        """Extrai componentes WinPE (.wim, BCD, boot.sdi, fonts, bootmgr, efi)."""
        try:
            # Busca arquivos recursivamente
            def find(pattern, recursive=True):
                results = []
                for root, dirs, files in os.walk(drive):
                    for f in files:
                        if re.match(pattern, f, re.IGNORECASE):
                            results.append(os.path.join(root, f))
                    if not recursive:
                        break
                return results

            # WIM
            wim_files = find(r".*\.wim$")
            if wim_files:
                maior = max(wim_files, key=lambda p: os.path.getsize(p))
                shutil.copy2(maior, os.path.join(target, "boot.wim"))

            # boot.sdi
            sdi_files = find(r"boot\.sdi$")
            if sdi_files:
                shutil.copy2(sdi_files[0], os.path.join(target, "boot.sdi"))

            # BCD
            bcd_files = find(r"^BCD$")
            if bcd_files:
                shutil.copy2(bcd_files[0], os.path.join(target, "BCD"))

            # Fonts
            font_folder = os.path.join(target, "Fonts")
            os.makedirs(font_folder, exist_ok=True)
            font_dirs = find(r"^(Fonts|SSTR|SSTR_fonts)$", recursive=False)
            for fd in font_dirs:
                if os.path.isdir(fd):
                    try:
                        for ff in os.listdir(fd):
                            src = os.path.join(fd, ff)
                            if os.path.isfile(src):
                                shutil.copy2(src, os.path.join(font_folder, ff))
                    except OSError:
                        pass

            # Se nao achou Fonts recursivamente
            if not os.listdir(font_folder):
                all_fonts = find(r"\.ttf$", True)
                for af in all_fonts[:10]:
                    shutil.copy2(af, os.path.join(font_folder, os.path.basename(af)))

            # bootmgr
            bm = os.path.join(drive, "bootmgr")
            if os.path.exists(bm):
                shutil.copy2(bm, os.path.join(target, "bootmgr"))

            # bootx64.efi
            efi_files = find(r"bootx64\.efi$")
            if efi_files:
                shutil.copy2(efi_files[0], os.path.join(target, "bootx64.efi"))

            return True
        except Exception as e:
            self.logger.error(f"WinPE extraction failed: {e}")
            return False

    # ===================== LINUX EXTRACTION =====================

    def _extract_linux(self, drive, target):
        """Extrai kernel + initrd de Linux live ISO."""
        try:
            def find(pattern):
                for root, dirs, files in os.walk(drive):
                    for f in files:
                        if re.match(pattern, f, re.IGNORECASE):
                            return os.path.join(root, f)
                return None

            kernel_path = find(r"(vmlinuz|bzImage|vmlinux|linux)[\.\-].*")
            if not kernel_path:
                kernel_path = find(r"^(vmlinuz|bzImage|vmlinux|linux)$")

            initrd_path = find(r"(initrd|initramfs)[\.\-\.].*$")
            if not initrd_path:
                initrd_path = find(r"^(initrd\.img|initrd|initramfs.*\.img|initramfs.*\.cpio)$")

            if kernel_path:
                shutil.copy2(kernel_path, os.path.join(target, "vmlinuz"))
            if initrd_path:
                shutil.copy2(initrd_path, os.path.join(target, "initrd"))

            return True
        except Exception as e:
            self.logger.error(f"Linux extraction failed: {e}")
            return False

    def _extract_linux_squashfs(self, drive, target, mount_drive):
        """Extrai kernel + squashfs para Ubuntu/Debian style."""
        try:
            def find(pattern):
                for root, dirs, files in os.walk(drive):
                    for f in files:
                        if re.match(pattern, f, re.IGNORECASE):
                            return os.path.join(root, f)
                return None

            kernel_path = find(r"(vmlinuz|bzImage)")
            if not kernel_path:
                for root, dirs, files in os.walk(os.path.join(drive, "casper")):
                    for f in files:
                        if f.startswith("vmlinuz"):
                            kernel_path = os.path.join(root, f)
                            break
                    if kernel_path:
                        break

            squashed = find(r".*\.squashfs$")

            if kernel_path:
                shutil.copy2(kernel_path, os.path.join(target, "vmlinuz"))
            if squashed:
                shutil.copy2(squashed, os.path.join(target, "filesystem.squashfs"))

            # Tambem tenta procurar initrd se houver
            initrd_path = find(r"initrd.*\.gz|initrd.*\.xz|initrd.*\.lz4")
            if initrd_path:
                shutil.copy2(initrd_path, os.path.join(target, "initrd"))

            return True
        except Exception as e:
            self.logger.error(f"Linux squashfs extraction failed: {e}")
            return False

    # ===================== UEFI DIRECT =====================

    def _extract_uefi_direct(self, drive, target):
        """Copia EFI boot files para boot direto."""
        try:
            def find(pattern):
                for root, dirs, files in os.walk(drive):
                    for f in files:
                        if re.match(pattern, f, re.IGNORECASE):
                            return os.path.join(root, f)
                return None

            # Copia bootx64.efi
            efi = find(r"bootx64\.efi$")
            if not efi:
                efi = find(r"([^/]+\.efi)$")

            if efi:
                shutil.copy2(efi, os.path.join(target, "bootx64.efi"))
                return True

            return False
        except Exception as e:
            self.logger.error(f"UEFI extraction failed: {e}")
            return False

    # ===================== UNKNOWN FALLBACK =====================

    def _extract_unknown(self, drive, target):
        """Fallback: copia conteudo do root para possivel uso com memdisk."""
        try:
            for item in os.listdir(drive):
                src = os.path.join(drive, item)
                if os.path.isfile(src):
                    shutil.copy2(src, target)
            return True
        except Exception as e:
            self.logger.error(f"Unknown extraction fallback failed: {e}")
            return False

    # ===================== STRELEC LEGACY =====================

    def find_strelec_iso(self):
        """Busca Strelec ISO (compatibilidade legado)."""
        drives = [f"{d}:" for d in string.ascii_uppercase if os.path.exists(f"{d}:")]
        for d in drives:
            try:
                root_files = os.listdir(d)
                strelec = [f for f in root_files if f.lower().endswith(".iso") and "strelec" in f.lower()]
                if strelec:
                    return os.path.join(d, strelec[0])
            except OSError:
                continue
        return None

    def extract_strelec(self, iso_path):
        """Compatibilidade legado - wrapper para add_iso."""
        iso_name = os.path.basename(iso_path)
        return self.add_iso({"path": iso_path, "name": iso_name, "size_mb": 0})

    # ===================== MENU GENERATION =====================

    # Arquivos essenciais por tipo
    _TYPE_FILES = {
        TYPE_WIMBOOT: ["boot.wim", "bootx64.efi"],
        TYPE_LINUX_ISO: ["vmlinuz"],
        TYPE_LINUX_SQUASHFS: ["vmlinuz"],
        TYPE_UEFI_DIRECT: ["bootx64.efi"],
    }

    def list_added_isos(self):
        """Lista todas as ISOs validas ja adicionadas."""
        isos = []
        if not os.path.isdir(self.extract_dir):
            return isos

        # First pass: apenas le os .pxegemini_meta (rapido, nao escaneia disco)
        valid_keys = set()
        for entry in sorted(os.listdir(self.extract_dir)):
            if entry.startswith("."):
                continue
            metadata = os.path.join(self.extract_dir, entry, ".pxegemini_meta")
            if os.path.isfile(metadata):
                info = {"key": entry, "folder": os.path.join(self.extract_dir, entry)}
                with open(metadata, "r", encoding="utf-8") as f:
                    for line in f:
                        if "=" in line:
                            k, v = line.strip().split("=", 1)
                            info[k] = v
                isos.append(info)
                valid_keys.add(entry)

        # Second pass: pastas antigas sem meta — verifica se tem arquivos de boot
        # So olha arquivos especificos, nao faz listagem completa (evita travamento)
        for entry in sorted(os.listdir(self.extract_dir)):
            if entry.startswith(".") or entry in valid_keys:
                continue
            folder = os.path.join(self.extract_dir, entry)
            if not os.path.isdir(folder):
                continue
            detected_type = self._detect_folder_type(folder)
            if detected_type == "invalid":
                # Pasta sem arquivos de boot — ignorar
                continue
            with open(os.path.join(folder, ".pxegemini_meta"), "w", encoding="utf-8") as f:
                f.write(f"name={entry}\npath=\nkey={entry}\ntype={detected_type}\n")
            isos.append({"key": entry, "name": entry, "type": detected_type, "folder": folder})
            valid_keys.add(entry)

        return isos

    def _detect_folder_type(self, folder):
        """Detecta tipo olhando apenas arquivos essenciais (rapido)."""
        if os.path.isfile(os.path.join(folder, "boot.wim")) and os.path.isfile(os.path.join(folder, "bootx64.efi")):
            return self.TYPE_WIMBOOT
        if os.path.isfile(os.path.join(folder, "boot.wim")):
            return self.TYPE_WIMBOOT
        if os.path.isfile(os.path.join(folder, "vmlinuz")):
            return self.TYPE_LINUX_ISO
        if os.path.isfile(os.path.join(folder, "bootx64.efi")):
            return self.TYPE_UEFI_DIRECT
        # Sem arquivos essenciais = pasta invalida
        return "invalid"

    def remove_iso(self, key):
        """Remove uma ISO adicionada."""
        folder = os.path.join(self.extract_dir, key)
        if os.path.isdir(folder):
            try:
                shutil.rmtree(folder)
                self.logger.info(f"ISO removida: {key}")
                return True
            except Exception as e:
                self.logger.error(f"Falha ao remover ISO {key}: {e}")
                return False
        return False

    def generate_menu(self):
        """Gera menu.ipxe dinamico com todas as ISOs adicionadas."""
        server_ip = self.config.get("server_ip", "192.168.0.21")
        # HTTPD root ja e extract_dir, entao nao precisa prefixo "/extracted"
        base_url = f"http://{server_ip}"
        boot_url = f"http://{server_ip}"

        isos = self.list_added_isos()

        if not isos:
            # Menu vazio com mensagem
            menu = f"""#!ipxe
# PXEGEMINI Boot Menu - Nenhuma ISO adicionada
# Use a aba ISO Manager para adicionar ISOs.

:start
menu PXEGEMINI - Sem ISOs adicionadas
item help Nenhuma ISO disponivel. Adicione via ISO Manager.
item exit Reboot
choose target && goto ${{target}}
:help
echo Nenhuma ISO configurada.
chain menu.ipxe ||
:exit
reboot
"""
        else:
            items = []
            entries = []

            for iso in isos:
                key = iso["key"]
                name = iso.get("name", key)
                iso_type = iso.get("type", "unknown")
                entry = self._make_menu_entry(key, name, iso_type, base_url, boot_url)
                items.append(f"item {key} {name} [{iso_type}]")
                entries.append(entry)

            items_text = "\n".join(items)
            entries_text = "\n".join(entries)

            menu = f"""#!ipxe
# PXEGEMINI Boot Menu - Generated dynamically
# Server: {server_ip}

:start
menu PXEGEMINI - Network Boot
{items_text}
item exit Reboot
choose target && goto ${{target}}

{entries_text}

:exit
reboot
"""

        try:
            menu_path = os.path.join(self.boot_dir, "menu.ipxe")
            with open(menu_path, "w") as f:
                f.write(menu)
            self.logger.info(f"Generated menu.ipxe com {len(isos)} ISO(s).")
        except Exception as e:
            self.logger.error(f"Failed to generate menu: {e}")

    def _make_menu_entry(self, key, name, iso_type, base_url, boot_url):
        """Gera secao de boot para uma ISO no menu.ipxe."""
        iso_url = f"{base_url}/{key}"

        if iso_type == self.TYPE_WIMBOOT:
            return self._menu_wimboot(key, name, iso_url)
        elif iso_type == self.TYPE_LINUX_ISO:
            return self._menu_linux(key, name, iso_url)
        elif iso_type == self.TYPE_LINUX_SQUASHFS:
            return self._menu_linux_squashfs(key, name, iso_url)
        elif iso_type == self.TYPE_UEFI_DIRECT:
            return self._menu_uefi_direct(key, name, iso_url)
        else:
            return self._menu_unknown(key, name, iso_url)

    def _menu_wimboot(self, key, name, iso_url):
        """Entry para WinPE via wimboot."""
        boot_file = f"{iso_url}/bootx64.efi"
        entry = f""":{key}
# Boot WinPE: {name}
kernel {iso_url}/wimboot rawbcd
initrd {iso_url}/bootmgr bootmgr
initrd {iso_url}/bootmgr bootmgr.efi
initrd {iso_url}/bootx64.efi bootmgfw.efi
initrd {iso_url}/bootx64.efi EFI/Microsoft/Boot/bootmgfw.efi
initrd {iso_url}/BCD BCD
initrd {iso_url}/BCD boot/BCD
initrd {iso_url}/boot.sdi boot.sdi
initrd {iso_url}/boot.sdi boot/boot.sdi
initrd {iso_url}/boot.wim boot.wim
initrd {iso_url}/boot.wim sources/boot.wim"""

        # Font aliases
        for font in ['segmono_boot.ttf', 'segoe_slboot.ttf', 'wgl4_boot.ttf']:
            entry += f"\ninitrd {iso_url}/Fonts/{font} Fonts/{font}"
            entry += f"\ninitrd {iso_url}/Fonts/{font} EFI/Microsoft/Boot/Fonts/{font}"

        entry += "\nboot\n"
        return entry

    def _menu_linux(self, key, name, iso_url):
        """Entry para Linux live."""
        return f""":{key}
# Boot Linux: {name}
kernel {iso_url}/vmlinuz ip=dhcp
initrd {iso_url}/initrd
boot
"""

    def _menu_linux_squashfs(self, key, name, iso_url):
        """Entry para Ubuntu/Debian style com squashfs."""
        return f""":{key}
# Boot Linux live (squashfs): {name}
kernel {iso_url}/vmlinuz boot=casper netboot=nfs nfsroot={iso_url}/filesystem.squashfs ip=dhcp --
initrd {iso_url}/initrd
boot
"""

    def _menu_uefi_direct(self, key, name, iso_url):
        """Entry para boot UEFI direto."""
        return f""":{key}
# Boot UEFI: {name}
chain {iso_url}/bootx64.efi
"""

    def _menu_unknown(self, key, name, iso_url):
        """Fallback para tipo desconhecido."""
        return f""":{key}
# Unknown type: {name} (tentando boot via chainload)
chain {iso_url}/bootx64.efi || goto {key}_fail
goto exit
:{key}_fail
echo Falha ao bootar {name}. Tipo nao reconhecido.
goto start
"""


    # ===================== STRELEC LEGACY (mantido para compatibilidade) =====================

    def _get_font_lines(self, base_url):
        fonts = ['segmono_boot.ttf', 'segoe_slboot.ttf', 'wgl4_boot.ttf']
        lines = []
        for f in fonts:
            lines.append(f"initrd {base_url}/Fonts/{f} Fonts/{f}")
            lines.append(f"initrd {base_url}/Fonts/{f} SSTR/Fonts/{f}")
            lines.append(f"initrd {base_url}/Fonts/{f} EFI/Microsoft/Boot/Fonts/{f}")
        return lines
