import customtkinter as ctk
import threading
import logging
import subprocess
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

# ===== Heuristic: Consistency & Standards — unified color palette =====
COLORS = {
    "bg": "#0d1117",
    "card": "#161b22",
    "card_border": "#30363d",
    "accent": "#58a6ff",
    "green": "#3fb950",
    "red": "#f85149",
    "orange": "#d29922",
    "purple": "#bc8cff",
    "text_primary": "#e6edf3",
    "text_secondary": "#8b949e",
    "text_muted": "#484f58",
    "input_bg": "#0d1117",
}

# ===== Heuristic: Error Prevention — IP validation =====
def is_valid_ip(ip):
    parts = ip.strip().split(".")
    if len(parts) != 4:
        return False
    for part in parts:
        try:
            n = int(part)
            if n < 0 or n > 255:
                return False
        except ValueError:
            return False
    return True


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


# ===== Heuristic: Aesthetic & Minimalist — compact server status card =====
class StatusCard(ctk.CTkFrame):
    """Card visual para status individual de um servidor."""

    def __init__(self, parent, label, icon="●"):
        super().__init__(parent, fg_color=COLORS["card"], corner_radius=10, border_width=1, border_color=COLORS["card_border"])
        self.icon = ctk.CTkLabel(self, text=icon, font=ctk.CTkFont(size=24))
        self.icon.pack(pady=(12, 2))
        self.lbl = ctk.CTkLabel(self, text=label, font=ctk.CTkFont(size=12, weight="bold"), text_color=COLORS["text_primary"])
        self.lbl.pack()
        self.detail = ctk.CTkLabel(self, text="Parado", font=ctk.CTkFont(size=11), text_color=COLORS["text_muted"])
        self.detail.pack(pady=(0, 10))

    def set_online(self, text="Online"):
        self.icon.configure(text="●", text_color=COLORS["green"])
        self.detail.configure(text=text, text_color=COLORS["green"])

    def set_offline(self):
        self.icon.configure(text="●", text_color=COLORS["text_muted"])
        self.detail.configure(text="Parado", text_color=COLORS["text_muted"])

    def set_error(self, text="Erro"):
        self.icon.configure(text="●", text_color=COLORS["red"])
        self.detail.configure(text=text, text_color=COLORS["red"])


class PXEGEMINIApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("PXEGEMINI v5.0 — Network Boot System")
        self.geometry("1100x750")
        self.configure(fg_color=COLORS["bg"])

        self.config = load_config()
        self.servers = {"dhcp": None, "tftp": None, "http": None}
        self.running = False

        self.iso_manager = ISOManager(self.config)

        self.setup_ui()
        self.setup_logging()
        self.bind("<F5>", lambda e: self.start_engine())
        self.bind("<Escape>", lambda e: self.stop_engine())
        self.bind("<Control-r>", lambda e: self._refresh_iso_list())

        # Auto-start engine after UI is drawn
        self.after(300, self.start_engine)

    def setup_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_main_area()
        self.show_page("dash")

    def _build_sidebar(self):
        sidebar = ctk.CTkFrame(self, width=200, corner_radius=0, fg_color=COLORS["card"], border_width=0)
        sidebar.grid(row=0, column=0, sticky="nsew", padx=(0, 1))
        sidebar.grid_rowconfigure(6, weight=1)
        sidebar.grid_columnconfigure(0, weight=1)

        # Branding area
        brand = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand.grid(row=0, column=0, padx=16, pady=(20, 4), sticky="w")
        ctk.CTkLabel(brand, text="PXEGEMINI", font=ctk.CTkFont(size=20, weight="bold"), text_color=COLORS["text_primary"]).pack(anchor="w")
        ctk.CTkLabel(brand, text="Network Boot System", font=ctk.CTkFont(size=11), text_color=COLORS["text_muted"]).pack(anchor="w")

        sep = ctk.CTkFrame(sidebar, height=1, fg_color=COLORS["card_border"])
        sep.grid(row=1, column=0, padx=16, pady=10, sticky="ew")

        # Nav buttons
        nav_items = [
            ("Dashboard", "dash", "dash"),
            ("ISO Manager", "iso", "iso"),
            ("Releases", "releases", "releases"),
            ("Settings", "settings", "settings"),
        ]
        self._btn_map = {}
        for i, (label, key, method_key) in enumerate(nav_items):
            btn = ctk.CTkButton(sidebar, text=label, font=ctk.CTkFont(size=13),
                                fg_color="transparent", hover_color="#1c2333",
                                text_color=COLORS["text_secondary"],
                                height=36, anchor="w",
                                command=lambda k=key: self.show_page(k))
            btn.grid(row=2 + i, column=0, padx=12, pady=2, sticky="ew")
            self._btn_map[key] = btn

        # Bottom status
        status_box = ctk.CTkFrame(sidebar, fg_color="transparent")
        status_box.grid(row=6, column=0, padx=12, pady=16, sticky="s")

        self.status_led = ctk.CTkLabel(status_box, text="●", text_color=COLORS["text_muted"], font=ctk.CTkFont(size=16))
        self.status_led.grid(row=0, column=0, padx=(0, 6))
        self.status_text = ctk.CTkLabel(status_box, text="OFFLINE", font=ctk.CTkFont(size=12, weight="bold"), text_color=COLORS["text_secondary"])
        self.status_text.grid(row=0, column=1)
        ctk.CTkLabel(status_box, text="v5.0", font=ctk.CTkFont(size=10), text_color=COLORS["text_muted"]).grid(row=1, column=0, columnspan=2, pady=(4, 0))

    def _build_main_area(self):
        container = ctk.CTkFrame(self, corner_radius=0, fg_color=COLORS["bg"])
        container.grid(row=0, column=1, padx=0, pady=0, sticky="nsew")

        self.pages = {}
        self._build_dash_page(container)
        self._build_iso_page(container)
        self._build_releases_page(container)
        self._build_settings_page(container)

    # ============ VISIBILITY OF SYSTEM STATUS ============

    def _build_dash_page(self, parent):
        page = ctk.CTkScrollableFrame(parent, fg_color=COLORS["bg"])
        self.pages["dash"] = page

        # Header
        header_frame = ctk.CTkFrame(page, fg_color="transparent")
        header_frame.pack(fill="x", padx=30, pady=(20, 10))
        ctk.CTkLabel(header_frame, text="Dashboard", font=ctk.CTkFont(size=28, weight="bold"), text_color=COLORS["text_primary"]).pack(anchor="w")
        ctk.CTkLabel(header_frame, text="Gerencie servidores e acompanhe clientes em tempo real.", font=ctk.CTkFont(size=13), text_color=COLORS["text_secondary"]).pack(anchor="w")

        # Heuristic: Visibility of system status — server status cards
        cards_frame = ctk.CTkFrame(page, fg_color="transparent")
        cards_frame.pack(fill="x", padx=30, pady=10)
        cards_frame.grid_columnconfigure((0, 1, 2), weight=1)

        self.card_dhcp = StatusCard(cards_frame, "DHCP / ProxyDHCP")
        self.card_dhcp.grid(row=0, column=0, padx=(0, 8), pady=5, sticky="ew")

        self.card_tftp = StatusCard(cards_frame, "TFTP")
        self.card_tftp.grid(row=0, column=1, padx=4, pady=5, sticky="ew")

        self.card_http = StatusCard(cards_frame, "HTTP")
        self.card_http.grid(row=0, column=2, padx=(8, 0), pady=5, sticky="ew")

        # Readiness box
        readiness_box = ctk.CTkFrame(page, height=48, fg_color=COLORS["card"], corner_radius=10, border_width=1, border_color=COLORS["card_border"])
        readiness_box.pack(padx=30, fill="x", pady=8)
        self.readiness_label = ctk.CTkLabel(readiness_box, text="  Verificando disponibilidade do sistema...", font=ctk.CTkFont(size=13), text_color=COLORS["text_secondary"])
        self.readiness_label.pack(pady=8, anchor="w")

        # ISO count badge
        self.iso_count_label = ctk.CTkLabel(page, text="", font=ctk.CTkFont(size=12), text_color=COLORS["accent"])
        self.iso_count_label.pack(pady=2)

        # Action buttons
        btn_row = ctk.CTkFrame(page, fg_color="transparent")
        btn_row.pack(pady=12, fill="x", padx=30)

        self.start_btn = ctk.CTkButton(btn_row, text="▶  START ENGINE", height=44, font=ctk.CTkFont(size=14, weight="bold"),
                                        fg_color=COLORS["green"], hover_color="#2ea043",
                                        command=self.start_engine)
        self.start_btn.pack(side="left", padx=4, fill="x", expand=True)

        self.stop_btn = ctk.CTkButton(btn_row, text="■  STOP ENGINE", height=44, font=ctk.CTkFont(size=14, weight="bold"),
                                       fg_color=COLORS["red"], hover_color="#da3633",
                                       command=self.stop_engine, state="disabled")
        self.stop_btn.pack(side="left", padx=(4, 4), fill="x", expand=True)

        self.fix_btn = ctk.CTkButton(btn_row, text="🛠  Fix Firewall / Rede", height=44, font=ctk.CTkFont(size=13, weight="bold"),
                                      fg_color=COLORS["card"], hover_color="#1c2333", text_color=COLORS["text_primary"],
                                      border_width=1, border_color=COLORS["card_border"],
                                      command=self.run_network_fix, width=200)
        self.fix_btn.pack(side="left", padx=(4, 0))

        # Keyboard hint
        ctk.CTkLabel(page, text="Atalhos: F5 = Start  |  Esc = Stop  |  Ctrl+R = Refresh ISO",
                     font=ctk.CTkFont(size=11), text_color=COLORS["text_muted"]).pack(pady=(5, 10))

        # Console
        console_label = ctk.CTkLabel(page, text="LOGS EM TEMPO REAL", font=ctk.CTkFont(size=11, weight="bold"), text_color=COLORS["text_muted"])
        console_label.pack(pady=(4, 0), anchor="w", padx=30)
        self.console = ctk.CTkTextbox(page, height=280, fg_color=COLORS["input_bg"],
                                        text_color=COLORS["green"], font=ctk.CTkFont(family="Consolas", size=12),
                                        border_width=1, border_color=COLORS["card_border"], corner_radius=10)
        self.console.pack(padx=30, pady=(4, 20), fill="both", expand=True)
        self.console.configure(state="disabled")
        self.console.insert("0.0", "PXEGEMINI v5.0 — Sistema inicializado.\n")

    # ============ RECOGNITION RATHER THAN RECALL ============

    def _build_iso_page(self, parent):
        page = ctk.CTkFrame(parent, fg_color=COLORS["bg"])
        self.pages["iso"] = page

        title = ctk.CTkLabel(page, text="ISO Manager", font=ctk.CTkFont(size=26, weight="bold"), text_color=COLORS["text_primary"])
        title.pack(pady=(16, 4))

        # Heuristic: Recognition — descriptive sublabel
        ctk.CTkLabel(page, text="Adicione ISOs de boot. O sistema detecta automaticamente o tipo (WinPE, Linux, UEFI).",
                     font=ctk.CTkFont(size=12), text_color=COLORS["text_secondary"]).pack(pady=(0, 12))

        # Top buttons with icons
        top_btns = ctk.CTkFrame(page, fg_color="transparent")
        top_btns.pack(pady=4)

        self.btn_add_iso = ctk.CTkButton(top_btns, text="+  Adicionar ISO", height=34, fg_color=COLORS["green"],
                                          hover_color="#2ea043", font=ctk.CTkFont(size=13, weight="bold"),
                                          command=self._add_iso_dialog)
        self.btn_add_iso.pack(side="left", padx=4)

        self.btn_add_folder = ctk.CTkButton(top_btns, text="  Scanear Pasta  ", height=34, fg_color=COLORS["card"],
                                             hover_color="#1c2333", text_color=COLORS["text_primary"],
                                             border_width=1, border_color=COLORS["card_border"],
                                             font=ctk.CTkFont(size=13),
                                             command=self._scan_folder)
        self.btn_add_folder.pack(side="left", padx=4)

        self.btn_scan_drives = ctk.CTkButton(top_btns, text="  Scanear Discos  ", height=34, fg_color=COLORS["card"],
                                              hover_color="#1c2333", text_color=COLORS["text_primary"],
                                              border_width=1, border_color=COLORS["card_border"],
                                              font=ctk.CTkFont(size=13),
                                              command=self._scan_drives)
        self.btn_scan_drives.pack(side="left", padx=4)

        # ISO list
        list_frame = ctk.CTkFrame(page, fg_color=COLORS["card"], corner_radius=12, border_width=1, border_color=COLORS["card_border"])
        list_frame.pack(padx=30, pady=8, fill="both", expand=True)

        # Table header
        list_header = ctk.CTkFrame(list_frame, fg_color=COLORS["card_border"], corner_radius=0)
        list_header.pack(fill="x", padx=0, pady=0)

        ctk.CTkLabel(list_header, text="ISO", width=280, anchor="w", font=ctk.CTkFont(weight="bold", size=12), text_color=COLORS["text_primary"]).pack(side="left", padx=14, pady=8)
        ctk.CTkLabel(list_header, text="Tipo", width=120, anchor="w", font=ctk.CTkFont(weight="bold", size=12), text_color=COLORS["text_primary"]).pack(side="left", padx=5, pady=8)
        ctk.CTkLabel(list_header, text="Tamanho", width=100, anchor="w", font=ctk.CTkFont(weight="bold", size=12), text_color=COLORS["text_primary"]).pack(side="left", padx=5, pady=8)

        self.iso_listbox = ctk.CTkScrollableFrame(list_frame, fg_color="transparent")
        self.iso_listbox.pack(fill="both", expand=True, padx=0, pady=0)

        # Bottom buttons
        bottom_btns = ctk.CTkFrame(page, fg_color="transparent")
        bottom_btns.pack(pady=8)

        self.btn_refresh = ctk.CTkButton(bottom_btns, text="  Atualizar Lista  ", height=34, command=self._refresh_iso_list,
                                          fg_color=COLORS["card"], hover_color="#1c2333", text_color=COLORS["text_primary"],
                                          border_width=1, border_color=COLORS["card_border"], font=ctk.CTkFont(size=13))
        self.btn_refresh.pack(side="left", padx=4)

        self.btn_remove_iso = ctk.CTkButton(bottom_btns, text="Remover Selecionada", height=34,
                                             fg_color=COLORS["card"], hover_color="#1c2333", text_color=COLORS["text_secondary"],
                                             border_width=1, border_color=COLORS["card_border"],
                                             command=self._remove_iso, font=ctk.CTkFont(size=13))
        self.btn_remove_iso.pack(side="left", padx=4)

        self.btn_regen_menu = ctk.CTkButton(bottom_btns, text="Regenerar Menu iPXE", height=34,
                                             fg_color=COLORS["card"], hover_color="#1c2333", text_color=COLORS["orange"],
                                             border_width=1, border_color=COLORS["card_border"],
                                             command=self._regen_menu, font=ctk.CTkFont(size=13))
        self.btn_regen_menu.pack(side="left", padx=4)

        self.iso_info = ctk.CTkLabel(page, text="Nenhuma ISO adicionada. Clique em 'Adicionar ISO' para começar.",
                                     text_color=COLORS["text_muted"], font=ctk.CTkFont(size=12))
        self.iso_info.pack(pady=4)

        self._iso_rows = {}

    def _build_releases_page(self, parent):
        page = ctk.CTkFrame(parent, fg_color=COLORS["bg"])
        self.pages["releases"] = page

        ctk.CTkLabel(page, text="Historico de Versoes", font=ctk.CTkFont(size=26, weight="bold"), text_color=COLORS["text_primary"]).pack(pady=(16, 4))

        # Heuristic: Help & Documentation — better formatted changelog
        history = ctk.CTkTextbox(page, fg_color=COLORS["card"], font=ctk.CTkFont(family="Consolas", size=13),
                                  wrap="word", border_width=1, border_color=COLORS["card_border"], corner_radius=12)
        history.pack(padx=30, pady=8, fill="both", expand=True)

        changelog = """
[v5.0] Multi-ISO Support (Estavel)
  +  Suporte a multiplas ISOs (WinPE, Linux live, UEFI)
  +  Scanner de todos os discos por qualquer ISO
  +  Detecao automatica de tipo (WinPE/Linux/UEFI)
  +  Menu iPXE gerado dinamicamente
  +  Adicionar/remover ISOs via UI
  +  Scanear pasta local ou discos inteiros

[v4.0] Otimizacao de Memoria e SMB Share
  !  Resolvido estouro de RAM no notebook
  +  Servidor SMB Compartilhado para Strelec
  +  Extração automatica da ISO para pasta

[v3.0] Estabilidade e Automacao Total
  +  Busca em todos os discos por ISOs Strelec
  +  Resolvido erro de "wimboot Not Found"

[v2.2] UEFI Power
  ~  Troca para snponly.efi (Drivers nativos)
  +  Resolvido "No more network devices"

[v2.1] Interface & Log
  +  Corrigido erro de cores no CTkFont
  +  Aba RELEASES adicionada
  +  Crash Logger integrado
"""
        history.insert("0.0", changelog.strip())
        history.configure(state="disabled")

    def _build_settings_page(self, parent):
        page = ctk.CTkFrame(parent, fg_color=COLORS["bg"])
        self.pages["settings"] = page

        ctk.CTkLabel(page, text="Configuracoes", font=ctk.CTkFont(size=26, weight="bold"), text_color=COLORS["text_primary"]).pack(pady=(16, 4))
        ctk.CTkLabel(page, text="Ajuste os parametros da rede e do sistema.", font=ctk.CTkFont(size=12), text_color=COLORS["text_secondary"]).pack(pady=(0, 16))

        card = ctk.CTkFrame(page, fg_color=COLORS["card"], corner_radius=12, border_width=1, border_color=COLORS["card_border"])
        card.pack(padx=40, pady=0, fill="both", expand=True, ipady=20)

        # IP
        ctk.CTkLabel(card, text="IP Estatico do Servidor", font=ctk.CTkFont(size=14, weight="bold"), text_color=COLORS["text_primary"]).pack(pady=(24, 2))
        # Heuristic: Recognition — hint text
        ctk.CTkLabel(card, text="IP fixo da maquina que vai rodar o PXE. Deve estar na mesma rede dos clientes.",
                     font=ctk.CTkFont(size=11), text_color=COLORS["text_muted"]).pack()
        self.entry_ip = ctk.CTkEntry(card, width=250, height=38, font=ctk.CTkFont(size=15), justify="center",
                                      fg_color=COLORS["input_bg"], border_width=1, border_color=COLORS["card_border"])
        self.entry_ip.insert(0, self.config.get("server_ip", "0.0.0.0"))
        self.entry_ip.pack(pady=8)

        # Heuristic: Error Prevention — inline IP validation label
        self.ip_validate_label = ctk.CTkLabel(card, text="", font=ctk.CTkFont(size=11), text_color=COLORS["red"])
        self.ip_validate_label.pack()
        self.entry_ip.bind("<KeyRelease>", lambda e: self._validate_ip_live())

        # ISO Dir
        ctk.CTkLabel(card, text="Pasta de busca ISO", font=ctk.CTkFont(size=14, weight="bold"), text_color=COLORS["text_primary"]).pack(pady=(16, 2))
        ctk.CTkLabel(card, text="Diretorio padrao para escanear ISOs ao clicar em 'Scanear Pasta'.",
                     font=ctk.CTkFont(size=11), text_color=COLORS["text_muted"]).pack()
        self.entry_iso_dir = ctk.CTkEntry(card, width=350, height=38, font=ctk.CTkFont(size=13), justify="center",
                                           fg_color=COLORS["input_bg"], border_width=1, border_color=COLORS["card_border"])
        self.entry_iso_dir.insert(0, self.config.get("iso_dir", "E:\\"))
        self.entry_iso_dir.pack(pady=8)

        # Proxy Mode
        self.proxy_var = ctk.BooleanVar(value=self.config.get("mode_proxy", True))
        self.chk_proxy = ctk.CTkSwitch(card, text="Modo ProxyDHCD (recomendado — evita conflito com roteador/DHCP existente)",
                                        variable=self.proxy_var, font=ctk.CTkFont(size=13), text_color=COLORS["text_secondary"])
        self.chk_proxy.pack(pady=24)
        # Heuristic: Help & Documentation — proxy hint
        ctk.CTkLabel(card, text="Desative apenas se esta maquina for o unico servidor DHCP da rede.",
                     font=ctk.CTkFont(size=11), text_color=COLORS["text_muted"]).pack()

        btn_save = ctk.CTkButton(card, text="SALVAR CONFIG", height=44, font=ctk.CTkFont(size=14, weight="bold"),
                                  fg_color=COLORS["accent"], hover_color="#388bfd",
                                  command=self.save_settings)
        btn_save.pack(pady=20, padx=60, fill="x")

    # ============ Heuristic: Recognition/Recall — live validation ============

    def _validate_ip_live(self):
        val = self.entry_ip.get().strip()
        if not val:
            self.ip_validation_label.configure(text="")
        elif is_valid_ip(val):
            self.ip_validation_label.configure(text="", text_color=COLORS["green"])
            # Heuristic: Flexibility and efficiency — auto-save indicator
        else:
            self.ip_validation_label.configure(text="Formato de IP invalido (ex: 192.168.0.21)", text_color=COLORS["red"])

    # ============ CONSISTENCY — nav highlighting ============

    def show_page(self, name):
        # Highlight active nav button
        for key, btn in self._btn_map.items():
            if key == name:
                btn.configure(fg_color="#1c2333", text_color=COLORS["text_primary"])
            else:
                btn.configure(fg_color="transparent", text_color=COLORS["text_secondary"])

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
            errors.append("Precisa de privilegios de Administrador")

        for port in [67, 69, 80, 4011]:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM if port in [67, 69, 4011] else socket.SOCK_STREAM) as s:
                try:
                    s.bind(('', port))
                except Exception:
                    errors.append(f"Porta {port} ocupada")

        if errors:
            msg = f"  ATENCAO: {' | '.join(errors)}"
            self.readiness_label.configure(text=msg, text_color=COLORS["red"])
            return False
        else:
            self.readiness_label.configure(text="  Sistema pronto para iniciar.", text_color=COLORS["green"])
            return True

    # ===================== ENGINE =====================

    def start_engine(self):
        """Inicia o engine em thread separada para nunca travar a GUI."""
        threading.Thread(target=self._start_work, daemon=True).start()

    def _start_work(self):
        """Thread de trabalho — nunca bloqueia o mainloop."""
        # Quick readiness check on main thread
        ready = True
        errors = []
        import ctypes
        if not ctypes.windll.shell32.IsUserAnAdmin():
            errors.append("Precisa de admin")
            ready = False

        # Only bind-check port 80 (most likely to conflict)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('', 80))
            except Exception:
                errors.append("Porta 80 ocupada")
                ready = False

        if not errors:
            for port in [67, 69, 4011]:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                    try:
                        s.bind(('', port))
                    except Exception:
                        errors.append(f"Porta {port} ocupada")
                        ready = False

        # Update readiness on main thread
        if errors:
            self.after(0, lambda: self.readiness_label.configure(
                text=f"  ATENCAO: {' | '.join(errors)}", text_color=COLORS["red"]))
            self.after(0, lambda: logging.warning(
                "Sistema nao esta pronto. Verifique os itens acima."))
            return
        else:
            self.after(0, lambda: self.readiness_label.configure(
                text="  Sistema pronto.", text_color=COLORS["green"]))

        # Update UI — "spinning up"
        self.after(0, lambda: self.card_dhcp.set_offline())
        self.after(0, lambda: self.card_tftp.set_offline())
        self.after(0, lambda: self.card_http.set_offline())
        self.after(0, lambda: self.start_btn.configure(state="disabled"))

        # Generate menu
        self.iso_manager.generate_menu()

        config = self.config.copy()
        server_ip = self.entry_ip.get()
        if not server_ip or not is_valid_ip(server_ip):
            self.after(0, lambda: logging.error(f"IP invalido: {server_ip}"))
            self.after(0, self.stop_engine)
            return

        config["server_ip"] = server_ip
        config["mode_proxy"] = self.proxy_var.get()

        try:
            self.servers["dhcp"] = DHCPD(config)
            self.servers["tftp"] = TFTPD(config)
            self.servers["http"] = HTTPD(config)

            threading.Thread(target=self.servers["dhcp"].listen, daemon=True).start()
            threading.Thread(target=self.servers["tftp"].listen, daemon=True).start()
            threading.Thread(target=self.servers["http"].listen, daemon=True).start()

        except Exception as e:
            logging.error(f"Falha ao iniciar servidores: {e}")
            self.after(0, self.stop_engine)
            return

        # Create SMB shares so WinPE guests can access:
        # 1. \\SSTR\ -> programs (Strelec tools, MInst, etc)
        # 2. \\IMG\   -> user's Macrium backup images
        extract_base = self.config.get("extract_dir", os.path.join("data", "extracted"))
        sstr_path = os.path.abspath(os.path.join(extract_base, "strelec", "SSTR"))
        # fallbacks for sstr_path
        if not os.path.isdir(sstr_path):
            sstr_path = os.path.abspath(os.path.join("data", "extracted", "strelec", "SSTR"))
        if not os.path.isdir(sstr_path):
            sstr_path = os.path.abspath("E:\\PXEGEMINI\\data\\extracted\\strelec\\SSTR")

        for share_name, share_path in [("SSTR", sstr_path), ("IMG", r"E:\Backup")]:
            subprocess.run(["net", "share", f"/delete", share_name], capture_output=True)
            if os.path.isdir(share_path):
                result = subprocess.run(
                    ["net", "share", f"{share_name}={os.path.normpath(share_path)}"],
                    capture_output=True, text=True
                )
                if result.returncode == 0:
                    logging.info(f"SMB Share {share_name} criado: {share_path}")
                else:
                    logging.warning(f"Falha ao criar SMB share {share_name}: "
                                    f"{result.stderr.strip() or result.stdout.strip()}")
            else:
                logging.info(f"Pasta para share {share_name} nao encontrada: {share_path} (pulando)")
        mode_text = "ProxyDHCP" if config["mode_proxy"] else "DHCP"
        self.after(0, lambda: self.card_dhcp.set_online(mode_text))
        self.after(0, lambda: self.card_tftp.set_online("Porta 69"))
        self.after(0, lambda: self.card_http.set_online(config["server_ip"]))
        self.after(0, lambda: self.status_led.configure(text_color=COLORS["green"]))
        self.after(0, lambda: self.status_text.configure(text="ONLINE"))
        self.after(0, lambda: self.stop_btn.configure(state="normal"))
        self.after(0, lambda: logging.info("PXEGEMINI Engine Iniciado."))
        self.after(0, lambda: logging.info(
            f"Modo: {mode_text} | UEFI: snponly.efi"))

        self.running = True

    def stop_engine(self):
        if not self.running:
            return
        self.running = False
        logging.info("Parando servidores...")

        # Remove SMB shares
        for share_name in ["SSTR", "IMG"]:
            subprocess.run(["net", "share", f"/delete", share_name], capture_output=True)

        # Set running=False flag on each server
        for key in ("dhcp", "tftp"):
            srv = self.servers.get(key)
            if srv:
                srv.running = False
        # HTTP: use shutdown() — safe because it's called from a *different* thread
        http_srv = self.servers.get("http")
        if http_srv:
            try:
                http_srv.stop()
            except Exception:
                pass



        # Close sockets to break select() loops in DHCP/TFTP
        for key in ("dhcp", "tftp"):
            srv = self.servers.get(key)
            if srv and hasattr(srv, 'sock'):
                try:
                    srv.sock.close()
                except Exception:
                    pass
            if srv and hasattr(srv, 'sock_binl') and srv.sock_binl:
                try:
                    srv.sock_binl.close()
                except Exception:
                    pass

        self.servers = {"dhcp": None, "tftp": None, "http": None}

        # Heuristic: Visibility — update cards
        self.card_dhcp.set_offline()
        self.card_tftp.set_offline()
        self.card_http.set_offline()

        self.status_led.configure(text_color=COLORS["text_muted"])
        self.status_text.configure(text="OFFLINE")
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        logging.info("Servidores parados.")

    # ============ Heuristic: User Control & Freedom ============

    def run_network_fix(self):
        if not messagebox.askokcancel("Fix Firewall/Rede",
                                       "Isso vai modificar regras do Firewall do Windows.\n"
                                       "Portas 67, 69, 80, 4011 serao liberadas.\n"
                                       "Continuar?"):
            logging.info("Fix cancelado pelo usuario.")
            return

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

    # ============ Heuristic: Error Prevention ============

    def save_settings(self):
        ip = self.entry_ip.get().strip()
        if not ip or not is_valid_ip(ip):
            # Heuristic: Error Recovery — clear message
            messagebox.showerror("IP Invalido",
                                 "O endereco IP esta em formato invalido.\n"
                                 "Exemplo valido: 192.168.0.21")
            logging.error(f"Tentativa de salvar IP invalido: {ip}")
            return

        self.config["server_ip"] = ip
        self.config["iso_dir"] = self.entry_iso_dir.get()
        self.config["mode_proxy"] = self.proxy_var.get()
        save_config(self.config)
        self.iso_manager.iso_dir = self.entry_iso_dir.get()
        logging.info("Configuracao salva com sucesso.")
        # Heuristic: Feedback on success
        messagebox.showinfo("Sucesso", "Configuracao salva com sucesso.")

    # ===================== ISO MANAGEMENT =====================

    def _add_iso_dialog(self):
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        files = filedialog.askopenfilenames(
            title="Selecionar ISO(s) para adicionar",
            filetypes=[("Arquivos ISO", "*.iso"), ("Todos os arquivos", "*.*")]
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
            self.after(0, lambda: logging.info(f"ISO '{iso_info['name']}' adicionada com sucesso!"))
            self.after(0, self._refresh_iso_list)
            self.after(0, self.iso_manager.generate_menu)
        else:
            self.after(0, lambda: logging.error(f"Falha ao adicionar '{iso_info['name']}': {result.get('error', 'desconhecido')}"))

    def _scan_folder(self):
        target_dir = self.config.get("iso_dir", "E:\\")
        threading.Thread(target=self._do_scan_folder, args=(target_dir,), daemon=True).start()

    def _do_scan_folder(self, folder):
        logging.info(f"Escaneando pasta: {folder}")
        isos = self.iso_manager.find_isos_in_dir(folder)
        if not isos:
            self.after(0, lambda: logging.warning(f"Nenhuma ISO encontrada em {folder}"))
            return

        self.after(0, lambda: logging.info(f"Encontradas {len(isos)} ISO(s) em {folder}"))
        for iso in isos:
            threading.Thread(target=self._do_add_iso, args=(iso,), daemon=True).start()
        self.after(2000, self._refresh_iso_list)

    def _scan_drives(self):
        if not messagebox.askokcancel("Scanear Discos",
                                       "Vou escanear todos os discos por arquivos .iso.\n"
                                       "Isso pode demorar alguns minutos.\n"
                                       "Continuar?"):
            logging.info("Scan de discos cancelado pelo usuario.")
            return
        threading.Thread(target=self._do_scan_drives, daemon=True).start()

    def _do_scan_drives(self):
        logging.info("Escaneando todos os discos por ISOs...")
        isos = self.iso_manager.find_all_isos()
        if not isos:
            self.after(0, lambda: logging.warning("Nenhuma ISO encontrada nos discos."))
            return

        # Deduplicate by path
        seen = set()
        unique = []
        for iso in isos:
            if iso["path"] not in seen:
                seen.add(iso["path"])
                unique.append(iso)

        self.after(0, lambda: logging.info(f"Encontradas {len(unique)} ISO(s) nos discos."))

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
        # Clear old
        for key, row in self._iso_rows.items():
            try:
                row.destroy()
            except Exception:
                pass
        self._iso_rows.clear()

        isos = self.iso_manager.list_added_isos()

        if not isos:
            empty_label = ctk.CTkLabel(self.iso_listbox, text="Nenhuma ISO adicionada ainda.\nClique em '+ Adicionar ISO' para comecar.",
                                       text_color=COLORS["text_muted"], font=ctk.CTkFont(size=13))
            empty_label.pack(pady=50)
            self._iso_rows["_empty"] = empty_label
            self.iso_info.configure(text="Nenhuma ISO adicionada.")
            self.iso_count_label.configure(text="")
            return

        self.iso_count_label.configure(text=f"{len(isos)} ISO(s) configurada(s) — menu sera atualizado automaticamente")

        # Color map for types — Heuristic: Recognition
        type_colors = {
            "wimboot": COLORS["green"],
            "linux": COLORS["accent"],
            "squashfs": COLORS["accent"],
            "uefi": COLORS["purple"],
            "unknown": COLORS["orange"],
        }

        for iso in isos:
            key = iso["key"]
            name_display = iso.get("name", key)
            iso_type = iso.get("type", "unknown")
            size_mb = iso.get("size_mb", 0)
            type_color = type_colors.get(iso_type, COLORS["text_secondary"])

            row = ctk.CTkFrame(self.iso_listbox, fg_color=COLORS["card"], corner_radius=8,
                                border_width=1, border_color=COLORS["card_border"])
            row.pack(fill="x", padx=6, pady=2)

            ctk.CTkLabel(row, text=name_display, width=280, anchor="w", font=ctk.CTkFont(size=12),
                         text_color=COLORS["text_primary"]).pack(side="left", padx=12)
            ctk.CTkLabel(row, text=f"[{iso_type}]", width=120, anchor="w", font=ctk.CTkFont(size=12, weight="bold"),
                         text_color=type_color).pack(side="left", padx=5)
            ctk.CTkLabel(row, text=f"{size_mb:.0f} MB", width=100, anchor="w",
                         font=ctk.CTkFont(size=11), text_color=COLORS["text_muted"]).pack(side="left", padx=5)

            rm_btn = ctk.CTkButton(row, text="Remover", width=64, height=26, fg_color=COLORS["card"],
                                    hover_color="#1c2333", border_width=1, border_color=COLORS["red"],
                                    text_color=COLORS["red"], font=ctk.CTkFont(size=11),
                                    command=lambda k=key: self._remove_iso_by_key(k))
            rm_btn.pack(side="right", padx=8)

            self._iso_rows[key] = row

    def _remove_iso(self):
        logging.info("Use o botao 'Remover' na lista para remover uma ISO.")

    def _remove_iso_by_key(self, key):
        # Heuristic: User Control & Freedom — confirmation
        if not messagebox.askokcancel("Remover ISO", f"Remover a ISO '{key}'?\n\nOs arquivos extraidos serao apagados."):
            return
        self.iso_manager.generate_menu()
        # Heuristic: Error Recovery — clear message
        if self.iso_manager.remove_iso(key):
            logging.info(f"ISO '{key}' removida com sucesso.")
            self._refresh_iso_list()
            self.iso_manager.generate_menu()
        else:
            logging.error(f"Falha ao remover ISO '{key}'. Pode estar em uso.")

    def _regen_menu(self):
        self.iso_manager.generate_menu()
        logging.info("menu.ipxe regenerado com sucesso.")


if __name__ == "__main__":
    app = PXEGEMINIApp()
    app.mainloop()
