import os
import subprocess
import logging
import shutil
import re
from datetime import datetime

from config import save_config


# ============================================================
# ISOManager v5.7
# Heuristica Nielsen: Visibilidade do estado do sistema,
# Controle do usuario, Prevencao de erros
# ============================================================

class ISOManager:
    """
    Gerencia ISOs para boot PXE via HTTPDisk.
    Fluxo: usuario escolhe ISO -> add_iso() extrai arquivos de boot
    -> generate_menu() gera menu.ipxe dinamico.
    Nao faz scan automatico de disco (evita travamento no Windows).
    """

    VERSION = "5.7"

    # Tipos suportados
    TYPE_WIMBOOT  = "wimboot"    # WinPE (Strelec, Win10/11 PE)
    TYPE_LINUX    = "linux"      # Linux com vmlinuz + initrd
    TYPE_SQUASHFS = "squashfs"   # Ubuntu/Debian live
    TYPE_UEFI     = "uefi"       # bootx64.efi direto
    TYPE_UNKNOWN  = "unknown"

    def __init__(self, config, logger=None):
        self.config      = config
        self.iso_dir     = config.get("iso_dir", "E:\\")
        self.extract_dir = config.get("extract_dir", os.path.join("data", "extracted"))
        self.boot_dir    = config.get("boot_dir", "boot")
        self.logger      = logger or logging.getLogger("ISO")
        os.makedirs(self.extract_dir, exist_ok=True)
        os.makedirs(self.boot_dir,    exist_ok=True)

    # ----------------------------------------------------------
    # LOGGING HELPER
    # ----------------------------------------------------------

    def _log(self, level, msg, *args):
        getattr(self.logger, level)(msg, *args)

    # ----------------------------------------------------------
    # MOUNT / UNMOUNT  (Windows PowerShell)
    # ----------------------------------------------------------

    def _mount_iso(self, iso_path):
        """Monta ISO via PowerShell, retorna letra de drive (ex: 'D:') ou None."""
        ps = (
            f'$v = Mount-DiskImage -ImagePath "{iso_path}" -PassThru -ErrorAction Stop'
            f' | Get-Volume; $v.DriveLetter'
        )
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True, text=True, timeout=30,
            )
            letter = r.stdout.strip()
            if letter and len(letter) == 1 and letter.isalpha():
                return letter + ":"
        except Exception as e:
            self._log("warning", "Mount falhou para %s: %s", iso_path, e)
        return None

    def _unmount_iso(self, iso_path):
        """Desmonta ISO silenciosamente."""
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f'Dismount-DiskImage -ImagePath "{iso_path}" -ErrorAction SilentlyContinue'],
                capture_output=True, text=True, timeout=15,
            )
        except Exception:
            pass

    # ----------------------------------------------------------
    # DETECCAO DE TIPO
    # ----------------------------------------------------------

    def detect_iso_type(self, iso_path):
        """
        Detecta tipo da ISO montando e inspecionando conteudo.
        Fallback por nome do arquivo se nao conseguir montar.
        """
        drive = self._mount_iso(iso_path)
        if not drive:
            return self._detect_by_name(iso_path)
        try:
            return self._classify_drive(drive)
        finally:
            self._unmount_iso(iso_path)

    def _detect_by_name(self, iso_path):
        name = os.path.basename(iso_path).lower()
        if any(k in name for k in ("strelec", "winpe", "win10pe", "win11pe", "bartpe")):
            return self.TYPE_WIMBOOT
        if any(k in name for k in ("ubuntu", "debian", "mint", "kali", "fedora", "arch")):
            return self.TYPE_SQUASHFS
        return self.TYPE_UNKNOWN

    def _classify_drive(self, drive):
        """Analisa arquivos no drive montado para determinar tipo."""
        # WinPE: qualquer .wim em qualquer lugar
        for root, _, files in os.walk(drive):
            for f in files:
                if f.lower().endswith(".wim"):
                    return self.TYPE_WIMBOOT

        # Coleta root para analise rapida
        try:
            root_files = os.listdir(drive)
        except OSError:
            return self.TYPE_UNKNOWN

        lower = [f.lower() for f in root_files]

        # Linux squashfs (Ubuntu/Debian style)
        has_kernel = any(re.match(r"(vmlinuz|bzimage)", f) for f in lower)
        has_squash  = any(f.endswith(".squashfs") for f in lower)
        if has_kernel and has_squash:
            return self.TYPE_SQUASHFS

        # Linux generico
        has_initrd = any(re.match(r"(initrd|initramfs)", f) for f in lower)
        if has_kernel and has_initrd:
            return self.TYPE_LINUX

        # UEFI direto
        efi_path = os.path.join(drive, "EFI")
        if os.path.isdir(efi_path):
            for _, _, files in os.walk(efi_path):
                if any(f.lower().endswith(".efi") for f in files):
                    return self.TYPE_UEFI

        return self.TYPE_UNKNOWN

    # ----------------------------------------------------------
    # ADICIONAR ISO  (entrada principal do usuario)
    # ----------------------------------------------------------

    def add_iso(self, iso_path):
        """
        Adiciona uma ISO ao sistema.
        - iso_path: caminho completo para o arquivo .iso
        Retorna dict: {success, key, type, error, name}
        """
        if isinstance(iso_path, dict):
            iso_path = iso_path.get("path", "")

        if not os.path.isfile(iso_path):
            return {"success": False, "key": "", "type": self.TYPE_UNKNOWN,
                    "error": f"Arquivo nao encontrado: {iso_path}", "name": ""}

        iso_name = os.path.basename(iso_path)
        key = re.sub(r"[^a-zA-Z0-9_\-]", "_", os.path.splitext(iso_name)[0])
        target = os.path.join(self.extract_dir, key)
        os.makedirs(target, exist_ok=True)

        # Ja existe? Retorna sem re-extrair
        marker = os.path.join(target, ".pxegemini_type")
        if os.path.exists(marker):
            with open(marker, "r", encoding="utf-8") as f:
                prev_type = f.read().strip()
            self._log("info", "ISO '%s' ja adicionada (tipo=%s).", iso_name, prev_type)
            return {"success": True, "key": key, "type": prev_type, "error": "", "name": iso_name}

        self._log("info", "Detectando tipo de '%s'...", iso_name)
        iso_type = self.detect_iso_type(iso_path)
        self._log("info", "Tipo detectado: %s", iso_type)

        drive = self._mount_iso(iso_path)
        try:
            if not drive:
                return {"success": False, "key": key, "type": iso_type,
                        "error": "Nao foi possivel montar a ISO (requer admin)", "name": iso_name}

            if iso_type == self.TYPE_WIMBOOT:
                ok = self._extract_wimboot(drive, target)
            elif iso_type == self.TYPE_LINUX:
                ok = self._extract_linux(drive, target)
            elif iso_type == self.TYPE_SQUASHFS:
                ok = self._extract_squashfs(drive, target)
            elif iso_type == self.TYPE_UEFI:
                ok = self._extract_uefi(drive, target)
            else:
                ok = self._extract_fallback(drive, target)

            if not ok:
                return {"success": False, "key": key, "type": iso_type,
                        "error": "Extracao falhou", "name": iso_name}

            # Salva marcadores
            with open(marker, "w", encoding="utf-8") as f:
                f.write(iso_type)
            with open(os.path.join(target, ".pxegemini_meta"), "w", encoding="utf-8") as f:
                f.write(f"name={iso_name}\npath={iso_path}\nkey={key}\ntype={iso_type}\n")

            # Copia wimboot se WinPE
            if iso_type == self.TYPE_WIMBOOT:
                for fname in ["wimboot", "httpdisk.exe", "httpdisk.sys", "MACRIUM_REDE.cmd"]:
                    src = os.path.join(self.boot_dir, fname)
                    dst = os.path.join(target, fname)
                    if os.path.exists(src) and not os.path.exists(dst):
                        shutil.copy2(src, dst)

            self._log("info", "ISO '%s' adicionada com sucesso (key=%s).", iso_name, key)
            return {"success": True, "key": key, "type": iso_type, "error": "", "name": iso_name}

        finally:
            if drive:
                self._unmount_iso(iso_path)

    def remove_iso(self, key):
        """Remove ISO adicionada pelo key."""
        folder = os.path.join(self.extract_dir, key)
        if os.path.isdir(folder):
            try:
                shutil.rmtree(folder)
                self._log("info", "ISO removida: %s", key)
                return True
            except Exception as e:
                self._log("error", "Falha ao remover %s: %s", key, e)
        return False

    def find_isos_in_dir(self, folder):
        """Lista ISOs em uma pasta especifica sem modifica-las."""
        results = []
        if not folder or not os.path.isdir(folder):
            return results

        try:
            entries = sorted(os.listdir(folder))
        except OSError:
            return results

        for entry in entries:
            if not entry.lower().endswith(".iso"):
                continue
            full_path = os.path.join(folder, entry)
            if not os.path.isfile(full_path):
                continue
            results.append({
                "path": full_path,
                "name": entry,
                "size_mb": os.path.getsize(full_path) / (1024 * 1024),
            })
        return results

    def find_all_isos(self):
        """Escaneia todas as unidades locais por arquivos ISO."""
        results = []
        skip_dirs = {
            "$recycle.bin",
            "system volume information",
            "windows",
            "program files",
            "program files (x86)",
            "programdata",
        }

        roots = []
        for code in range(ord("A"), ord("Z") + 1):
            root = f"{chr(code)}:\\"
            if os.path.isdir(root):
                roots.append(root)

        for root in roots:
            for current_root, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs if d.lower() not in skip_dirs]
                for name in files:
                    if not name.lower().endswith(".iso"):
                        continue
                    full_path = os.path.join(current_root, name)
                    try:
                        size_mb = os.path.getsize(full_path) / (1024 * 1024)
                    except OSError:
                        size_mb = 0
                    results.append({
                        "path": full_path,
                        "name": name,
                        "size_mb": size_mb,
                    })
        return results

    # ----------------------------------------------------------
    # EXTRACAO POR TIPO
    # ----------------------------------------------------------

    def _find_recursive(self, base, pattern):
        """Busca arquivo por regex em toda arvore. Retorna primeiro match ou None."""
        for root, _, files in os.walk(base):
            for f in files:
                if re.match(pattern, f, re.IGNORECASE):
                    return os.path.join(root, f)
        return None

    def _find_all_recursive(self, base, pattern):
        """Busca todos os arquivos por regex. Retorna lista."""
        results = []
        for root, _, files in os.walk(base):
            for f in files:
                if re.match(pattern, f, re.IGNORECASE):
                    results.append(os.path.join(root, f))
        return results

    def _extract_wimboot(self, drive, target):
        """Extrai componentes WinPE: .wim, BCD, boot.sdi, fonts, bootmgr, efi."""
        try:
            # WIM: pega o maior (boot.wim ou install.wim)
            wims = self._find_all_recursive(drive, r".*\.wim$")
            if wims:
                biggest = max(wims, key=lambda p: os.path.getsize(p))
                shutil.copy2(biggest, os.path.join(target, "boot.wim"))

            # boot.sdi
            sdi = self._find_recursive(drive, r"^boot\.sdi$")
            if sdi:
                shutil.copy2(sdi, os.path.join(target, "boot.sdi"))

            # BCD
            bcd = self._find_recursive(drive, r"^BCD$")
            if bcd:
                shutil.copy2(bcd, os.path.join(target, "BCD"))

            # bootmgr
            bm = os.path.join(drive, "bootmgr")
            if os.path.exists(bm):
                shutil.copy2(bm, os.path.join(target, "bootmgr"))

            # bootx64.efi
            efi = self._find_recursive(drive, r"^bootx64\.efi$")
            if not efi:
                efi = self._find_recursive(drive, r"^bootmgfw\.efi$")
            if efi:
                shutil.copy2(efi, os.path.join(target, "bootx64.efi"))

            # Fonts
            font_dir = os.path.join(target, "Fonts")
            os.makedirs(font_dir, exist_ok=True)
            for ttf in self._find_all_recursive(drive, r".*\.ttf$")[:10]:
                shutil.copy2(ttf, os.path.join(font_dir, os.path.basename(ttf)))

            return True
        except Exception as e:
            self._log("error", "WinPE extraction failed: %s", e)
            return False

    def _extract_linux(self, drive, target):
        """Extrai kernel + initrd de Linux live ISO."""
        try:
            kernel = self._find_recursive(drive, r"^(vmlinuz|bzImage|vmlinux)([\.\-].*)?$")
            initrd = self._find_recursive(drive, r"^(initrd|initramfs)([\.\-].*)?$")
            if kernel:
                shutil.copy2(kernel, os.path.join(target, "vmlinuz"))
            if initrd:
                shutil.copy2(initrd, os.path.join(target, "initrd"))
            return bool(kernel)
        except Exception as e:
            self._log("error", "Linux extraction failed: %s", e)
            return False

    def _extract_squashfs(self, drive, target):
        """Extrai kernel + squashfs para Ubuntu/Debian style."""
        try:
            kernel = self._find_recursive(drive, r"^vmlinuz([\.\-].*)?$")
            if not kernel:
                # Tenta casper/
                casper = os.path.join(drive, "casper")
                if os.path.isdir(casper):
                    kernel = self._find_recursive(casper, r"^vmlinuz.*$")
            squash = self._find_recursive(drive, r".*\.squashfs$")
            initrd = self._find_recursive(drive, r"^initrd(\.gz|\.xz|\.lz4|\.img)?$")

            if kernel:
                shutil.copy2(kernel, os.path.join(target, "vmlinuz"))
            if squash:
                shutil.copy2(squash, os.path.join(target, "filesystem.squashfs"))
            if initrd:
                shutil.copy2(initrd, os.path.join(target, "initrd"))
            return bool(kernel)
        except Exception as e:
            self._log("error", "Squashfs extraction failed: %s", e)
            return False

    def _extract_uefi(self, drive, target):
        """Copia bootx64.efi para boot UEFI direto."""
        try:
            efi = self._find_recursive(drive, r"^bootx64\.efi$")
            if not efi:
                efi = self._find_recursive(drive, r".*\.efi$")
            if efi:
                shutil.copy2(efi, os.path.join(target, "bootx64.efi"))
                return True
            return False
        except Exception as e:
            self._log("error", "UEFI extraction failed: %s", e)
            return False

    def _extract_fallback(self, drive, target):
        """Fallback: copia root da ISO para uso com chainload."""
        try:
            for item in os.listdir(drive):
                src = os.path.join(drive, item)
                if os.path.isfile(src):
                    shutil.copy2(src, target)
            return True
        except Exception as e:
            self._log("error", "Fallback extraction failed: %s", e)
            return False

    # ----------------------------------------------------------
    # LISTAGEM DE ISOs ADICIONADAS
    # ----------------------------------------------------------

    def _resolve_iso_path(self, key: str, name: str) -> str:
        """
        Tenta localizar o arquivo ISO original por nome.
        Procura em locais comuns: iso_dir, raiz dos drives, iventoy, etc.
        Retorna caminho completo ou string vazia se nao encontrar.
        """
        candidates = []

        # Nome possivel do arquivo
        iso_name = name if name.lower().endswith('.iso') else name + '.iso'
        # Tambem tenta pelo key
        key_iso  = key  if key.lower().endswith('.iso')  else key  + '.iso'

        search_roots = [self.iso_dir]
        # Adiciona raizes comuns dos drives
        for code in range(ord('C'), ord('Z') + 1):
            root = f"{chr(code)}:\\"
            if os.path.isdir(root):
                search_roots.append(root)

        for root in search_roots:
            for candidate_name in (iso_name, key_iso):
                # Direto na raiz
                p = os.path.join(root, candidate_name)
                if os.path.isfile(p):
                    candidates.append(p)
                # Em subpastas comuns
                for sub in ('iso', 'isos', 'IMAGENS', 'iventoy-1.0.21\\iso',
                            'PXEGEMINI', 'PXE', 'images'):
                    p = os.path.join(root, sub, candidate_name)
                    if os.path.isfile(p):
                        candidates.append(p)

        # Prefere o maior arquivo (mais provavelmente a ISO real)
        if candidates:
            try:
                best = max(candidates, key=lambda p: os.path.getsize(p))
                self._log('info', 'ISO path resolvido por heuristica: %s -> %s', key, best)
                return best
            except OSError:
                return candidates[0]

        return ''

    def list_added_isos(self):
        """
        Lista ISOs validas ja adicionadas.
        Rapido: so le .pxegemini_meta, nao escaneia disco.
        Quando path= esta vazio, tenta localizar o ISO por heuristica
        e persiste o resultado no meta para proximas chamadas.
        """
        isos = []
        if not os.path.isdir(self.extract_dir):
            return isos

        for entry in sorted(os.listdir(self.extract_dir)):
            if entry.startswith('.'):
                continue
            folder = os.path.join(self.extract_dir, entry)
            if not os.path.isdir(folder):
                continue

            meta_path = os.path.join(folder, '.pxegemini_meta')
            type_path = os.path.join(folder, '.pxegemini_type')

            info = {'key': entry, 'folder': folder, 'name': entry, 'type': self.TYPE_UNKNOWN, 'path': ''}

            if os.path.isfile(meta_path):
                with open(meta_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if '=' in line:
                            k, v = line.strip().split('=', 1)
                            info[k] = v
            elif os.path.isfile(type_path):
                with open(type_path, 'r', encoding='utf-8') as f:
                    info['type'] = f.read().strip()
            else:
                # Pasta sem meta: detecta pelo conteudo (rapido, sem montar)
                detected = self._detect_folder_type(folder)
                if detected == 'invalid':
                    continue
                info['type'] = detected
                with open(meta_path, 'w', encoding='utf-8') as f:
                    f.write(f"name={entry}\npath=\nkey={entry}\ntype={detected}\n")

            # Se path esta vazio ou aponta para arquivo inexistente,
            # tenta localizar o ISO original por heuristica.
            iso_path = info.get('path', '')
            if not iso_path or not os.path.isfile(iso_path):
                resolved = self._resolve_iso_path(info['key'], info['name'])
                if resolved:
                    info['path'] = resolved
                    # Persiste para nao precisar buscar de novo
                    try:
                        with open(meta_path, 'w', encoding='utf-8') as f:
                            f.write(
                                f"name={info['name']}\n"
                                f"path={resolved}\n"
                                f"key={info['key']}\n"
                                f"type={info['type']}\n"
                            )
                    except OSError:
                        pass
                elif iso_path and not os.path.isfile(iso_path):
                    self._log('warning',
                              'ISO path nao encontrado: %s | chave=%s',
                              iso_path, entry)

            isos.append(info)

        return isos

    def _detect_folder_type(self, folder):
        """Detecta tipo olhando apenas arquivos essenciais (sem montar ISO)."""
        if os.path.isfile(os.path.join(folder, "boot.wim")):
            return self.TYPE_WIMBOOT
        if os.path.isfile(os.path.join(folder, "bootx64.efi")):
            return self.TYPE_UEFI
        if os.path.isfile(os.path.join(folder, "vmlinuz")):
            return self.TYPE_LINUX
        return "invalid"

    def get_iso_size_str(self, iso_path):
        """Retorna tamanho formatado da ISO (ex: '4.2 GB')."""
        try:
            size = os.path.getsize(iso_path)
            if size >= 1024**3:
                return f"{size / 1024**3:.1f} GB"
            if size >= 1024**2:
                return f"{size / 1024**2:.0f} MB"
            return f"{size / 1024:.0f} KB"
        except OSError:
            return "?"

    # ----------------------------------------------------------
    # GERACAO DO MENU iPXE
    # ----------------------------------------------------------

    @staticmethod
    def _boot_base_url(server_ip, http_port):
        return f"http://{server_ip}:{http_port}"

    def _write_entrypoint_scripts(self, server_ip, http_port):
        """Escreve scripts curtos para chainload HTTP e fallback autoexec."""
        base_url = self._boot_base_url(server_ip, http_port)
        menu_url = f"{base_url}/boot/menu.ipxe"

        launcher = (
            "#!ipxe\n"
            f"set menu-url {menu_url}\n"
            "chain ${menu-url} || goto retry\n"
            ":retry\n"
            "dhcp || goto shell\n"
            "chain ${menu-url} || goto shell\n"
            ":shell\n"
            "echo [PXEGEMINI] Falha ao carregar o menu HTTP.\n"
            "echo [PXEGEMINI] Tente: dhcp ; chain ${menu-url}\n"
            "shell\n"
        )

        for filename in ("boot.ipxe", "autoexec.ipxe"):
            with open(os.path.join(self.boot_dir, filename), "w", encoding="utf-8") as f:
                f.write(launcher)

    def generate_menu(self):
        """Gera menu.ipxe dinamico com todas as ISOs adicionadas."""
        server_ip = self.config.get("server_ip", "192.168.0.21")
        http_port = int(self.config.get("http_port", 80))
        isos = self.list_added_isos()

        if not isos:
            menu = (
                "#!ipxe\n"
                ":start\n"
                "menu PXEGEMINI HTTPDisk - Sem ISOs\n"
                "item exit Reboot\n"
                "choose target && goto ${target}\n"
                ":exit\nreboot\n"
            )
        else:
            items_lines  = []
            entries_text = []

            for iso in isos:
                key      = iso["key"]
                name     = iso.get("name", key)
                iso_type = iso.get("type", self.TYPE_UNKNOWN)
                folder   = iso.get("folder", "")
                iso_path = iso.get("path", "")

                # Gera scripts de boot para WinPE
                if iso_type == self.TYPE_WIMBOOT and folder:
                    self._write_winpe_scripts(key, folder, server_ip, http_port, iso_path)

                items_lines.append(f"item {key} {name}  [{iso_type}]")
                entries_text.append(
                    self._make_menu_entry(key, name, iso_type, server_ip, http_port)
                )

            menu = (
                "#!ipxe\n"
                f"# PXEGEMINI HTTPDisk v{ISOManager.VERSION} - Server: {server_ip}\n\n"
                ":start\n"
                "menu PXEGEMINI HTTPDisk - Network Boot\n"
                + "\n".join(items_lines)
                + "\nitem exit Reboot\n"
                "choose target && goto ${target}\n\n"
                + "\n".join(entries_text)
                + "\n:exit\nreboot\n"
            )

        try:
            menu_path = os.path.join(self.boot_dir, "menu.ipxe")
            with open(menu_path, "w", encoding="utf-8") as f:
                f.write(menu)
            self._write_entrypoint_scripts(server_ip, http_port)
            self.config["menu_version"] = int(self.config.get("menu_version", 0)) + 1
            self.config["last_menu_generated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                save_config(self.config)
            except Exception:
                pass
            self._log("info", "menu.ipxe gerado com %d ISO(s). Rev %s",
                      len(isos), self.config["menu_version"])
        except Exception as e:
            self._log("error", "Falha ao gerar menu: %s", e)

    def _write_winpe_scripts(self, key, folder, server_ip, http_port, iso_path):
        """Gera startnet.cmd e mount_iso.cmd para WinPE HTTPDisk."""
        # Copia suporte HTTPDisk se ausente
        for fname in ["httpdisk.exe", "httpdisk.sys", "MACRIUM_REDE.cmd"]:
            src = os.path.join(self.boot_dir, fname)
            dst = os.path.join(folder, fname)
            if os.path.exists(src) and not os.path.exists(dst):
                try:
                    shutil.copy2(src, dst)
                except Exception:
                    pass

        script = (
            "@echo off\n"
            "echo [PXEGEMINI] Iniciando WinPE...\n"
            "wpeinit\n"
            "echo [PXEGEMINI] Aguardando rede...\n"
            f"ping -n 4 {server_ip} >nul\n"
            "echo [PXEGEMINI] Registrando driver HTTPDisk...\n"
            "sc query HttpDisk >nul 2>&1 || "
            "sc create HttpDisk binpath= \"X:\\Windows\\System32\\drivers\\httpdisk.sys\""
            " type= kernel start= demand >nul 2>&1\n"
            "sc start HttpDisk >nul 2>&1\n"
            "echo [PXEGEMINI] Montando ISO via HTTP...\n"
            f"httpdisk.exe /mount 0 http://{server_ip}:{http_port}/{key}_raw.iso /cd Y:\n"
            "timeout /t 2 >nul\n"
            "if exist Y:\\ (\n"
            "    echo [OK] ISO montada em Y:\n"
            "    if exist Y:\\SSTR\\MInst\\MInst.exe (\n"
            "        echo [INFO] Strelec detectado - iniciando MInst\n"
            "        start \"\" \"Y:\\SSTR\\MInst\\MInst.exe\"\n"
            "    ) else if exist Y:\\setup.exe (\n"
            "        echo [INFO] Iniciando setup do Windows\n"
            "        start \"\" Y:\\setup.exe\n"
            "    ) else (\n"
            "        echo [INFO] Abrindo explorer\n"
            "        start \"\" explorer.exe Y:\\\n"
            "    )\n"
            "    if exist MACRIUM_REDE.cmd call MACRIUM_REDE.cmd\n"
            ") else (\n"
            "    echo [ERRO] HTTPDisk falhou. Tentando SMB...\n"
            f"    net use Z: \\\\{server_ip}\\SSTR /user:Guest \"\" /persistent:no\n"
            "    if exist Z:\\MInst\\MInst.exe start \"\" \"Z:\\MInst\\MInst.exe\"\n"
            ")\n"
            "cmd.exe\n"
        )

        for fname in ["startnet.cmd", "mount_iso.cmd"]:
            try:
                with open(os.path.join(folder, fname), "w", encoding="utf-8") as f:
                    f.write(script)
            except Exception as e:
                self._log("warning", "Nao foi possivel escrever %s: %s", fname, e)

    def _make_menu_entry(self, key, name, iso_type, server_ip, http_port):
        """Gera bloco iPXE para uma ISO."""
        url = f"http://{server_ip}:{http_port}/{key}"

        if iso_type == self.TYPE_WIMBOOT:
            return self._entry_wimboot(key, name, url, server_ip)
        elif iso_type == self.TYPE_LINUX:
            return self._entry_linux(key, name, url)
        elif iso_type == self.TYPE_SQUASHFS:
            return self._entry_squashfs(key, name, url)
        elif iso_type == self.TYPE_UEFI:
            return self._entry_uefi(key, name, url)
        else:
            return self._entry_unknown(key, name, url)

    def _entry_wimboot(self, key, name, url, server_ip):
        lines = [
            f":{key}",
            f"# WinPE: {name}",
            f"kernel {url}/wimboot rawbcd",
            f"initrd {url}/bootmgr bootmgr",
            f"initrd {url}/bootmgr bootmgr.efi",
            f"initrd {url}/bootx64.efi bootmgfw.efi",
            f"initrd {url}/bootx64.efi EFI/Microsoft/Boot/bootmgfw.efi",
            f"initrd {url}/BCD BCD",
            f"initrd {url}/BCD boot/BCD",
            f"initrd {url}/boot.sdi boot.sdi",
            f"initrd {url}/boot.sdi boot/boot.sdi",
            f"initrd {url}/boot.wim boot.wim",
            f"initrd {url}/boot.wim sources/boot.wim",
        ]
        for font in ["segmono_boot.ttf", "segoe_slboot.ttf", "wgl4_boot.ttf"]:
            lines.append(f"initrd {url}/Fonts/{font} Fonts/{font}")
            lines.append(f"initrd {url}/Fonts/{font} EFI/Microsoft/Boot/Fonts/{font}")
        lines += [
            f"initrd {url}/httpdisk.sys Windows/System32/drivers/httpdisk.sys",
            f"initrd {url}/httpdisk.exe Windows/System32/httpdisk.exe",
            f"initrd {url}/startnet.cmd Windows/System32/startnet.cmd",
            f"initrd {url}/mount_iso.cmd Windows/System32/mount_iso.cmd",
            "initrd {url}/mount_iso.cmd Users/Default/AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup/mount_iso.cmd".format(url=url),
            f"initrd {url}/MACRIUM_REDE.cmd Windows/System32/MACRIUM_REDE.cmd",
            f"initrd {url}/MACRIUM_REDE.cmd Users/Default/Desktop/MACRIUM_REDE.cmd",
            "boot",
            "",
        ]
        return "\n".join(lines)

    def _entry_linux(self, key, name, url):
        return (
            f":{key}\n"
            f"# Linux: {name}\n"
            f"kernel {url}/vmlinuz ip=dhcp\n"
            f"initrd {url}/initrd\n"
            "boot\n"
        )

    def _entry_squashfs(self, key, name, url):
        return (
            f":{key}\n"
            f"# Linux Live (squashfs): {name}\n"
            f"kernel {url}/vmlinuz boot=casper ip=dhcp quiet splash\n"
            f"initrd {url}/initrd\n"
            "boot\n"
        )

    def _entry_uefi(self, key, name, url):
        return (
            f":{key}\n"
            f"# UEFI: {name}\n"
            f"chain {url}/bootx64.efi\n"
        )

    def _entry_unknown(self, key, name, url):
        return (
            f":{key}\n"
            f"# Tipo desconhecido: {name}\n"
            f"chain {url}/bootx64.efi || goto {key}_fail\n"
            "goto exit\n"
            f":{key}_fail\n"
            f"echo Falha ao bootar {name}. Tipo nao reconhecido.\n"
            "goto start\n"
        )
