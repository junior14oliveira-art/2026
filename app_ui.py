import customtkinter as ctk
import threading
import logging
import time
import os
import psutil
import socket
import tkinter as tk
from tkinter import filedialog, messagebox
from servers.dhcp import DHCPD
from servers.tftp import TFTPD
from servers.http import HTTPD
from iso_manager import ISOManager
from config import load_config, save_config

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class LogHandler(logging.Handler):
    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget

    def emit(self, record):
        msg = self.format(record)
        self.text_widget.configure(state="normal")
        self.text_widget.insert("end", msg + "\n")
        self.text_widget.configure(state="disabled")
        self.text_widget.see("end")

class PXEGEMINIApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("PXEGEMINI - v5.0 Multi-ISO")
        self.geometry("1000x700")

        self.config = load_config()
        self.servers = {"dhcp": None, "tftp": None, "http": None}
        self.threads = []
        self.running = False

        self.iso_manager = ISOManager(self.config)

        self.setup_ui()
        self.setup_logging()
        self.check_readiness()

    def setup_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Sidebar
        self.sidebar = ctk.CTkFrame(self, width=220, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(5, weight=1)

        self.logo = ctk.CTkLabel(self.sidebar, text="PXEGEMINI", font=ctk.CTkFont(size=24, weight="bold", family="Inter"))
        self.logo.grid(row=0, column=0, padx=20, pady=(30, 20))

        self.btn_dash = ctk.CTkButton(self.sidebar, text="DASHBOARD", command=lambda: self.show_page("dash"))
        self.btn_dash.grid(row=1, column=0, padx=20, pady=10)

        self.btn_iso = ctk.CTkButton(self.sidebar, text="ISO MANAGER", command=self._show_iso_tab)
        self.btn_iso.grid(row=2, column=0, padx=20, pady=10)

        self.btn_releases = ctk.CTkButton(self.sidebar, text="RELEASES", fg_color="#34495e", command=lambda: self.show_page("releases"))
        self.btn_releases.grid(row=3, column=0, padx=20, pady=10)

        self.btn_settings = ctk.CTkButton(self.sidebar, text="SETTINGS", command=lambda: self.show_page("settings"))
        self.btn_settings.grid(row=4, column=0, padx=20, pady=10)

        self.status_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.status_frame.grid(row=6, column=0, pady=20)
        self.status_led = ctk.CTkLabel(self.status_frame, text="●", text_color="gray", font=ctk.CTkFont(size=20))
        self.status_led.grid(row=0, column=0, padx=5)
        self.status_text = ctk.CTkLabel(self.status_frame, text="OFFLINE", font=ctk.CTkFont(weight="bold"))
        self.status_text.grid(row=0, column=1)

        # Main Area
        self.main_container = ctk.CTkFrame(self, corner_radius=15, fg_color="#1a1a1a")
        self.main_container.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        self.pages = {}

        self.create_dash_page()
        self.create_iso_page()
        self.create_releases_page()
        self.create_settings_page()

        self.show_page("dash")

    def create_dash_page(self):
        page = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.pages["dash"] = page

        header = ctk.CTkLabel(page, text="Network Boot Control", font=ctk.CTkFont(size=32, weight="bold"))
        header.pack(pady=(20, 5))
        sub_header = ctk.CTkLabel(page, text="Gerencie o motor PXE e acompanhe a frota cliente em tempo real.", font=ctk.CTkFont(size=14), text_color="gray")
        sub_header.pack(pady=(0, 20))

        self.readiness_box = ctk.CTkFrame(page, height=60, fg_color="#2c3e50", corner_radius=10)
        self.readiness_box.pack(padx=40, fill="x", pady=10)
        self.readiness_label = ctk.CTkLabel(self.readiness_box, text="Scanning System Readiness...", font=ctk.CTkFont(size=14, weight="bold"))
        self.readiness_label.pack(pady=15)

        # ISO count badge
        self.iso_count_label = ctk.CTkLabel(page, text="", font=ctk.CTkFont(size=13), text_color="#3498db")
        self.iso_count_label.pack(pady=2)

        # Action Buttons
        button_container = ctk.CTkFrame(page, fg_color="transparent")
        button_container.pack(pady=20, fill="x", padx=40)

        self.start_btn = ctk.CTkButton(button_container, text="START ENGINE", height=50, font=ctk.CTkFont(size=16, weight="bold"),
                                       fg_color="#2ecc71", hover_color="#27ae60", command=self.start_engine)
        self.start_btn.pack(side="left", padx=10, expand=True, fill="x")

        self.stop_btn = ctk.CTkButton(button_container, text="STOP ENGINE", height=50, font=ctk.CTkFont(size=16, weight="bold"),
                                      fg_color="#e74c3c", hover_color="#c0392b", command=self.stop_engine, state="disabled")
        self.stop_btn.pack(side="right", padx=10, expand=True, fill="x")

        # Network fix button
        fix_frame = ctk.CTkFrame(page, fg_color="transparent")
        fix_frame.pack(pady=(5, 10))
        self.fix_btn = ctk.CTkButton(fix_frame, text="Fix Firewall / Rede", fg_color="#3498db", hover_color="#2980b9",
                                     command=self.run_network_fix, height=30)
        self.fix_btn.pack()

        # Console (Feedback Real)
        console_label = ctk.CTkLabel(page, text="REAL-TIME LOGS", font=ctk.CTkFont(size=12, weight="bold"), text_color="#A0A0A0")
        console_label.pack(pady=(10, 0), anchor="w", padx=40)
        self.console = ctk.CTkTextbox(page, height=260, fg_color="#0a0a0a", text_color="#2ecc71", font=ctk.CTkFont(family="Consolas"))
        self.console.pack(padx=40, pady=(5, 20), fill="both", expand=True)
        self.console.configure(state="disabled")
        self.console.insert("0.0", "PXEGEMINI v5.0 Multi-ISO Boot System Initialized.\n")

    def create_iso_page(self):
        page = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.pages["iso"] = page

        title = ctk.CTkLabel(page, text="ISO Manager", font=ctk.CTkFont(size=28, weight="bold"))
        title.pack(pady=15)

        # Top buttons
        top_btns = ctk.CTkFrame(page, fg_color="transparent")
        top_btns.pack(pady=5)

        self.btn_add_iso = ctk.CTkButton(top_btns, text="Adicionar ISO", height=35, fg_color="#2ecc71",
                                         hover_color="#27ae60", font=ctk.CTkFont(size=14, weight="bold"),
                                         command=self._add_iso_dialog)
        self.btn_add_iso.pack(side="left", padx=10)

        self.btn_add_folder = ctk.CTkButton(top_btns, text="Scanear Pasta", height=35, fg_color="#3498db",
                                            hover_color="#2980b9", font=ctk.CTkFont(size=14, weight="bold"),
                                            command=self._scan_folder)
        self.btn_add_folder.pack(side="left", padx=10)

        self.btn_scan_drives = ctk.CTkButton(top_btns, text="Scanear Discos", height=35, fg_color="#9b59b6",
                                             hover_color="#8e44ad", font=ctk.CTkFont(size=14, weight="bold"),
                                             command=self._scan_drives)
        self.btn_scan_drives.pack(side="left", padx=10)

        # ISO list
        list_frame = ctk.CTkFrame(page, fg_color="#242424", corner_radius=15)
        list_frame.pack(padx=30, pady=10, fill="both", expand=True)

        # Table-like header
        list_header = ctk.CTkFrame(list_frame, fg_color="#2c3e50", corner_radius=0)
        list_header.pack(fill="x", padx=0, pady=0)

        ctk.CTkLabel(list_header, text="ISO", width=250, anchor="w", font=ctk.CTkFont(weight="bold", size=13)).pack(side="left", padx=10, pady=8)
        ctk.CTkLabel(list_header, text="Tipo", width=100, anchor="w", font=ctk.CTkFont(weight="bold", size=13)).pack(side="left", padx=5, pady=8)
        ctk.CTkLabel(list_header, text="Tamanho", width=80, anchor="w", font=ctk.CTkFont(weight="bold", size=13)).pack(side="left", padx=5, pady=8)

        self.iso_listbox = ctk.CTkScrollableFrame(list_frame, fg_color="transparent")
        self.iso_listbox.pack(fill="both", expand=True, padx=0, pady=0)

        # Bottom buttons
        bottom_btns = ctk.CTkFrame(page, fg_color="transparent")
        bottom_btns.pack(pady=10)

        self.btn_refresh = ctk.CTkButton(bottom_btns, text="Atualizar Lista", height=35, command=self._refresh_iso_list)
        self.btn_refresh.pack(side="left", padx=10)

        self.btn_remove_iso = ctk.CTkButton(bottom_btns, text="Remover Selecionada", height=35,
                                            fg_color="#e74c3c", hover_color="#c0392b",
                                            command=self._remove_iso)
        self.btn_remove_iso.pack(side="left", padx=10)

        self.btn_regen_menu = ctk.CTkButton(bottom_btns, text="Regenerar Menu", height=35,
                                            fg_color="#f39c12", hover_color="#e67e22",
                                            command=self._regen_menu)
        self.btn_regen_menu.pack(side="left", padx=10)

        # Info text
        self.iso_info = ctk.CTkLabel(page, text="Nenhuma ISO adicionada. Clique em 'Adicionar ISO' para começar.",
                                     text_color="gray", font=ctk.CTkFont(size=12))
        self.iso_info.pack(pady=5)

        # Keep references to ISO row widgets for removal
        self._iso_rows = {}

    def _show_iso_tab(self):
        self.show_page("iso")
        self._refresh_iso_list()

    def create_releases_page(self):
        page = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.pages["releases"] = page

        ctk.CTkLabel(page, text="Historico de Versoes", font=ctk.CTkFont(size=28, weight="bold")).pack(pady=20)

        history = ctk.CTkTextbox(page, fg_color="#141414", font=ctk.CTkFont(size=14), wrap="word")
        history.pack(padx=40, pady=10, fill="both", expand=True)

        changelog = """
# v5.0 - Multi-ISO Support (Estavel)
- Feature: Suporte a multiplas ISOs (WinPE, Linux live, UEFI).
- Feature: Scanner de todos os discos por qualquer ISO.
- Feature: Detecao automatica de tipo (WinPE/Linux/UEFI).
- Feature: Menu iPxE gerado dinamicamente.
- Feature: Adicionar/remover ISOs via UI.
- Feature: Scanear pasta local ou discos inteiros.

# v4.0 - Otimizacao de Memoria e SMB Share
- Fix Critico: Resolvido estouro de RAM no notebook.
- Feature: Servidor SMB Compartilhado para Strelec.
- Feature: Extração automatica da ISO para pasta SSTR.

# v3.0 - Estabilidade e Automacao Total
- Feature: Busca interna em todos os discos por ISOs Strelec.
- Fix: Resolvido erro de "wimboot Not Found".

# v2.2 - UEFI Power
- Troca para snponly.efi (Drivers nativos).
- Resolvido "No more network devices".

# v2.1 - Interface & Log
- Corrigido erro de cores no CTkFont.
- Aba RELEASES adicionada.
- Crash Logger integrado.
"""
        history.insert("0.0", changelog.strip())
        history.configure(state="disabled")

        btn_export = ctk.CTkButton(page, text="EXPORTAR LOGS", command=self.export_logs)
        btn_export.pack(pady=10)

    def export_logs(self):
        desktop = os.path.join(os.environ["USERPROFILE"], "Desktop")
        target = os.path.join(desktop, "PXEGEMINI_DEBUG_LOG.txt")
        content = self.console.get("1.0", "end")
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)
        logging.info(f"Logs exportados para Desktop: {target}")

    def create_settings_page(self):
        page = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.pages["settings"] = page

        ctk.CTkLabel(page, text="System Settings", font=ctk.CTkFont(size=28, weight="bold")).pack(pady=20)

        card = ctk.CTkFrame(page, fg_color="#242424", corner_radius=15)
        card.pack(padx=40, pady=20, fill="both", expand=True)

        # IP
        ctk.CTkLabel(card, text="Main Server Static IP:", font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(30, 5))
        self.entry_ip = ctk.CTkEntry(card, width=250, height=40, font=ctk.CTkFont(size=16), justify="center")
        self.entry_ip.insert(0, self.config.get("server_ip", "0.0.0.0"))
        self.entry_ip.pack(pady=5)

        # ISO Dir
        ctk.CTkLabel(card, text="Pasta de busca ISO:", font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(15, 5))
        self.entry_iso_dir = ctk.CTkEntry(card, width=350, height=40, font=ctk.CTkFont(size=14), justify="center")
        self.entry_iso_dir.insert(0, self.config.get("iso_dir", "E:\\"))
        self.entry_iso_dir.pack(pady=5)

        # Proxy Mode
        self.proxy_var = ctk.BooleanVar(value=self.config.get("mode_proxy", True))
        self.chk_proxy = ctk.CTkSwitch(card, text="ProxyDHCP Mode (Evita conflito com DHCP Corporativo)",
                                       variable=self.proxy_var, font=ctk.CTkFont(size=14))
        self.chk_proxy.pack(pady=30)

        btn_save = ctk.CTkButton(card, text="SALVAR CONFIG", height=50, font=ctk.CTkFont(size=16, weight="bold"),
                                 command=self.save_settings)
        btn_save.pack(pady=20, padx=80, fill="x")

    def show_page(self, name):
        for p in self.pages.values():
            p.pack_forget()
        self.pages[name].pack(fill="both", expand=True)

    def setup_logging(self):
        root = logging.getLogger()
        handler = LogHandler(self.console)
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', "%H:%M:%S")
        handler.setFormatter(formatter)
        root.addHandler(handler)
        root.setLevel(logging.INFO)

    def check_readiness(self):
        errors = []
        import ctypes
        if not ctypes.windll.shell32.IsUserAnAdmin():
            errors.append("Precisa de Admin")

        for port in [67, 69, 80, 4011]:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM if port in [67, 69, 4011] else socket.SOCK_STREAM) as s:
                try:
                    s.bind(('', port))
                except Exception:
                    errors.append(f"Porta {port} ocupada")

        if errors:
            self.readiness_label.configure(text=f"ATENCAO: {', '.join(errors)}", text_color="#e74c3c")
            return False
        else:
            self.readiness_label.configure(text="PRONTO PARA INICIAR", text_color="#2ecc71")
            return True

    # ===================== ENGINE =====================

    def start_engine(self):
        if not self.check_readiness():
            return

        self.running = True
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status_led.configure(text_color="#2ecc71")
        self.status_text.configure(text="ONLINE")

        config = self.config.copy()
        config["server_ip"] = self.entry_ip.get()
        config["mode_proxy"] = self.proxy_var.get()

        # Regenera menu antes de iniciar
        threading.Thread(target=self.iso_manager.generate_menu, daemon=True).start()

        try:
            self.servers["dhcp"] = DHCPD(config)
            self.servers["tftp"] = TFTPD(config)
            self.servers["http"] = HTTPD(config)

            threading.Thread(target=self.servers["dhcp"].listen, daemon=True).start()
            threading.Thread(target=self.servers["tftp"].listen, daemon=True).start()
            threading.Thread(target=self.servers["http"].listen, daemon=True).start()

            logging.info("PXEGEMINI Engine Iniciado.")
            logging.info(f"Modo: {'ProxyDHCP' if config['mode_proxy'] else 'DHCP'} | UEFI: snponly.efi")
        except Exception as e:
            logging.error(f"Falha ao iniciar: {e}")
            self.stop_engine()

    def stop_engine(self):
        self.running = False
        logging.info("Parando servidores...")
        for name, server in self.servers.items():
            if server and hasattr(server, 'sock'):
                try:
                    server.sock.close()
                except Exception:
                    pass
        self.status_led.configure(text_color="gray")
        self.status_text.configure(text="OFFLINE")
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        logging.info("Servidores parados.")

    def run_network_fix(self):
        logging.info("Rodando Firewall & Network Fixer...")
        import sys
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))

        paths_to_check = [
            os.path.join(base_path, "FIX_PXE.bat"),
            os.path.join(base_path, "_internal", "FIX_PXE.bat"),
            os.path.join(os.getcwd(), "FIX_PXE.bat")
        ]

        bat_path = None
        for p in paths_to_check:
            if os.path.exists(p):
                bat_path = p
                break

        if bat_path:
            try:
                import ctypes
                ctypes.windll.shell32.ShellExecuteW(None, "runas", bat_path, None, None, 1)
                logging.info(f"Fixer executado: {bat_path}")
            except Exception as e:
                logging.error(f"Falha ao rodar fixer: {e}")
        else:
            logging.error("FIX_PXE.bat nao encontrado.")

    def save_settings(self):
        self.config["server_ip"] = self.entry_ip.get()
        self.config["iso_dir"] = self.entry_iso_dir.get()
        self.config["mode_proxy"] = self.proxy_var.get()
        save_config(self.config)
        self.iso_manager.iso_dir = self.entry_iso_dir.get()
        logging.info("Configuracao salva.")

    # ===================== ISO MANAGEMENT =====================

    def _add_iso_dialog(self):
        """Abre file dialog para selecionar 1+ ISOs."""
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        files = filedialog.askopenfilenames(
            title="Selecionar ISO(s)",
            filetypes=[("ISO files", "*.iso"), ("All files", "*.*")]
        )
        root.destroy()

        if not files:
            return

        for f in files:
            iso_info = {"path": f, "name": os.path.basename(f), "size_mb": os.path.getsize(f) / (1024 * 1024)}
            threading.Thread(target=self._do_add_iso, args=(iso_info,), daemon=True).start()

    def _do_add_iso(self, iso_info):
        result = self.iso_manager.add_iso(iso_info)
        if result["success"]:
            self.after(0, lambda: logging.info(f"ISO '{iso_info['name']}' adicionada!"))
            self.after(0, self._refresh_iso_list)
            self.after(0, self.iso_manager.generate_menu)
        else:
            self.after(0, lambda: logging.error(f"Falha: {iso_info['name']} - {result['error']}"))

    def _scan_folder(self):
        """Escaneia pasta configurada por ISOs."""
        target_dir = self.config.get("iso_dir", "E:\\")
        threading.Thread(target=self._do_scan_folder, args=(target_dir,), daemon=True).start()

    def _do_scan_folder(self, folder):
        isos = self.iso_manager.find_isos_in_dir(folder)
        if not isos:
            self.after(0, lambda: logging.warning(f"Nenhuma ISO encontrada em {folder}"))
            return

        self.after(0, lambda: logging.info(f"Encontradas {len(isos)} ISO(s) em {folder}"))
        for iso in isos:
            threading.Thread(target=self._do_add_iso, args=(iso,), daemon=True).start()
        self.after(1000, self._refresh_iso_list)

    def _scan_drives(self):
        """Escaneia todos os discos por ISOs."""
        threading.Thread(target=self._do_scan_drives, daemon=True).start()

    def _do_scan_drives(self):
        isos = self.iso_manager.find_all_isos()
        if not isos:
            self.after(0, lambda: logging.warning("Nenhuma ISO encontrada nos discos."))
            return

        # Deduplica por path
        seen = set()
        unique = []
        for iso in isos:
            if iso["path"] not in seen:
                seen.add(iso["path"])
                unique.append(iso)

        self.after(0, lambda: logging.info(f"Encontradas {len(unique)} ISO(s) nos discos."))

        # Adiciona com delay para nao sobrecarregar
        delay = 0
        for iso in unique:
            threading.Timer(delay, self._do_add_iso_scanned, args=(iso,), daemon=True).start()
            delay += 0.5

        self.after(int(delay * 1000 + 3000), self._refresh_iso_list)

    def _do_add_iso_scanned(self, iso):
        result = self.iso_manager.add_iso(iso)
        if result["success"]:
            logging.info(f"ISO '{iso['name']}' adicionada!")
        else:
            logging.error(f"Falha: {iso['name']} - {result.get('error', 'unknown')}")
        self.after(0, self._refresh_iso_list)
        self.after(0, self.iso_manager.generate_menu)

    def _refresh_iso_list(self):
        """Atualiza a lista visual de ISOs."""
        # Limpa
        for key, row in self._iso_rows.items():
            try:
                row.pack_forget()
            except Exception:
                pass
        self._iso_rows.clear()

        isos = self.iso_manager.list_added_isos()

        if not isos:
            empty_label = ctk.CTkLabel(self.iso_listbox, text="Nenhuma ISO adicionada ainda.",
                                       text_color="gray", font=ctk.CTkFont(size=14))
            empty_label.pack(pady=40)
            self._iso_rows["_empty"] = empty_label
            self.iso_info.configure(text="Nenhuma ISO adicionada.")
            self.iso_count_label.configure(text="")
            return

        self.iso_count_label.configure(text=f"{len(isos)} ISO(s) configurada(s)")
        self.iso_info.configure(text=f"{len(isos)} ISO(s) adicionada(s). Servidor pronto para boot.")

        for iso in isos:
            key = iso["key"]
            name_display = iso.get("name", key)
            iso_type = iso.get("type", "unknown")
            size_mb = iso.get("size_mb", 0)

            row = ctk.CTkFrame(self.iso_listbox, fg_color="#1e1e1e", corner_radius=8)
            row.pack(fill="x", padx=5, pady=3)

            ctk.CTkLabel(row, text=name_display, width=250, anchor="w", font=ctk.CTkFont(size=13)).pack(side="left", padx=10)
            ctk.CTkLabel(row, text=iso_type, width=100, anchor="w", font=ctk.CTkFont(size=13),
                        text_color="#3498db").pack(side="left", padx=5)
            ctk.CTkLabel(row, text=f"{size_mb:.0f}MB", width=80, anchor="w",
                        font=ctk.CTkFont(size=12), text_color="gray").pack(side="left", padx=5)

            # Remove button
            rm_btn = ctk.CTkButton(row, text="X", width=28, height=28, fg_color="#e74c3c",
                                   hover_color="#c0392b",
                                   command=lambda k=key: self._remove_iso_by_key(k))
            rm_btn.pack(side="right", padx=5)

            self._iso_rows[key] = row

    def _remove_iso(self):
        """Placeholder - usa X button inline."""
        logging.info("Use o botao 'X' na lista para remover uma ISO.")

    def _remove_iso_by_key(self, key):
        if not messagebox.askokcancel("Remover ISO", f"Remover ISO '{key}'?"):
            return
        if self.iso_manager.remove_iso(key):
            logging.info(f"ISO '{key}' removida.")
            self._refresh_iso_list()
            self.iso_manager.generate_menu()

    def _regen_menu(self):
        self.iso_manager.generate_menu()
        logging.info("menu.ipxe regenerado.")


if __name__ == "__main__":
    app = PXEGEMINIApp()
    app.mainloop()
