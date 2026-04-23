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

APP_VERSION = "5.7"

# ============================================================
# Paleta de cores unificada (Heuristica: Consistencia)
# ============================================================
C = {
    "bg":           "#0d1117",
    "card":         "#161b22",
    "border":       "#30363d",
    "accent":       "#58a6ff",
    "green":        "#3fb950",
    "red":          "#f85149",
    "orange":       "#d29922",
    "purple":       "#bc8cff",
    "text":         "#e6edf3",
    "text2":        "#8b949e",
    "muted":        "#484f58",
    "input":        "#0d1117",
    "hover":        "#1c2333",
}

# ============================================================
# Validacao de IP (corrigida - bug do return dentro do for)
# ============================================================
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
    return True  # fora do for


# ============================================================
# Handler de log -> widget de texto
# ============================================================
class LogHandler(logging.Handler):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def emit(self, record):
        msg = self.format(record)
        try:
            self.callback(msg)
        except Exception:
            pass


# ============================================================
# Card de status de servidor (Heuristica: Visibilidade)
# ============================================================
class StatusCard(ctk.CTkFrame):
    def __init__(self, parent, label):
        super().__init__(parent,
                         fg_color=C["card"], corner_radius=10,
                         border_width=1, border_color=C["border"])
        self.icon  = ctk.CTkLabel(self, text="●", font=ctk.CTkFont(size=22))
        self.icon.pack(pady=(12, 2))
        self.lbl   = ctk.CTkLabel(self, text=label,
                                  font=ctk.CTkFont(size=12, weight="bold"),
                                  text_color=C["text"])
        self.lbl.pack()
        self.detail = ctk.CTkLabel(self, text="Parado",
                                   font=ctk.CTkFont(size=11),
                                   text_color=C["muted"])
        self.detail.pack(pady=(0, 10))

    def set_online(self, text="Online"):
        self.icon.configure(text_color=C["green"])
        self.detail.configure(text=text, text_color=C["green"])

    def set_offline(self):
        self.icon.configure(text_color=C["muted"])
        self.detail.configure(text="Parado", text_color=C["muted"])

    def set_error(self, text="Erro"):
        self.icon.configure(text_color=C["red"])
        self.detail.configure(text=text, text_color=C["red"])


# ============================================================
# Linha de ISO na lista (Heuristica: Reconhecimento)
# ============================================================
class ISORow(ctk.CTkFrame):
    def __init__(self, parent, iso_info, on_remove, on_boot_test):
        super().__init__(parent,
                         fg_color=C["card"], corner_radius=8,
                         border_width=1, border_color=C["border"])
        key      = iso_info.get("key", "")
        name     = iso_info.get("name", key)
        iso_type = iso_info.get("type", "?")
        iso_path = iso_info.get("path", "")

        # Cor por tipo
        type_colors = {
            "wimboot":  C["green"],
            "linux":    C["accent"],
            "squashfs": C["purple"],
            "uefi":     C["orange"],
            "unknown":  C["muted"],
        }
        tc = type_colors.get(iso_type, C["muted"])

        # Layout: nome | tipo | caminho | botoes
        self.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self, text="●", text_color=tc,
                     font=ctk.CTkFont(size=16)).grid(
            row=0, column=0, padx=(10, 6), pady=8)

        name_frame = ctk.CTkFrame(self, fg_color="transparent")
        name_frame.grid(row=0, column=1, sticky="w", padx=4)
        ctk.CTkLabel(name_frame, text=name,
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=C["text"], anchor="w").pack(anchor="w")
        ctk.CTkLabel(name_frame,
                     text=f"{iso_type.upper()}  |  {iso_path or 'pasta local'}",
                     font=ctk.CTkFont(size=10),
                     text_color=C["text2"], anchor="w").pack(anchor="w")

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=0, column=2, padx=8)

        ctk.CTkButton(btn_frame, text="Remover", width=80, height=28,
                      fg_color=C["card"], hover_color=C["hover"],
                      text_color=C["red"], border_width=1,
                      border_color=C["border"],
                      font=ctk.CTkFont(size=11),
                      command=lambda: on_remove(key)).pack(side="left", padx=2)


# ============================================================
# Aplicacao principal
# ============================================================
class PXEGEMINIApp(ctk.CTk):

    def __init__(self):
        super().__init__()
        self.geometry("1100x760")
        self.configure(fg_color=C["bg"])

        self.config      = load_config()
        self.app_version = APP_VERSION
        self.config["app_version"] = APP_VERSION
        self.title(f"PXEGEMINI HTTPDisk Edition v{APP_VERSION}")

        # Variaveis de estado
        self.compat_var   = tk.StringVar(value=self.config.get("compat_profile", "auto"))
        self.network_var  = tk.StringVar(value=self.config.get("network_profile", "isolated"))
        self.auto_prep    = tk.BooleanVar(value=self.config.get("auto_prepare_on_adapter", True))
        self.proxy_var    = tk.BooleanVar(value=self.config.get("mode_proxy", True))
        self.adapter_var  = tk.StringVar(value="")

        self.servers      = {"dhcp": None, "tftp": None, "http": None}
        self.threads      = {}
        self.running      = False
        self._adapter_map = {}   # display -> info dict
        self._selected_adapter = ""
        self._iso_rows    = {}   # key -> ISORow widget

        self.iso_manager  = ISOManager(self.config)

        self._setup_logging()
        self._build_ui()

        self.bind("<F5>",      lambda e: self.start_engine())
        self.bind("<Escape>",  lambda e: self.stop_engine())
        self.bind("<Control-r>", lambda e: self._refresh_iso_list())

        self.after(200, self._refresh_adapters_initial)
        self.after(400, self.start_engine)

    # ----------------------------------------------------------
    # LOGGING
    # ----------------------------------------------------------

    def _setup_logging(self):
        self.logger = logging.getLogger("PXEGEMINI")
        self.logger.setLevel(logging.DEBUG)
        if not self.logger.handlers:
            fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                                    datefmt="%H:%M:%S")
            # Handler para arquivo
            try:
                fh = logging.FileHandler(
                    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "pxegemini.log"),
                    encoding="utf-8")
                fh.setFormatter(fmt)
                self.logger.addHandler(fh)
            except Exception:
                pass
            # Handler para UI (adicionado depois que o widget existir)
            self._pending_log_handler = fmt
        self.iso_manager.logger = self.logger

    def _attach_log_widget(self):
        fmt = getattr(self, "_pending_log_handler", None)
        if fmt and hasattr(self, "console"):
            def _append(msg):
                self.after(0, lambda m=msg: self._console_append(m))
            h = LogHandler(_append)
            h.setFormatter(fmt)
            self.logger.addHandler(h)

    def _console_append(self, msg):
        if not hasattr(self, "console"):
            return
        self.console.configure(state="normal")
        self.console.insert("end", msg + "\n")
        self.console.configure(state="disabled")
        self.console.see("end")

    # ----------------------------------------------------------
    # BUILD UI
    # ----------------------------------------------------------

    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_main()
        self.show_page("dash")
        self._update_version_labels()

    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=200, corner_radius=0,
                          fg_color=C["card"], border_width=0)
        sb.grid(row=0, column=0, sticky="nsew", padx=(0, 1))
        sb.grid_rowconfigure(6, weight=1)
        sb.grid_columnconfigure(0, weight=1)

        # Branding
        brand = ctk.CTkFrame(sb, fg_color="transparent")
        brand.grid(row=0, column=0, padx=16, pady=(20, 4), sticky="w")
        ctk.CTkLabel(brand, text="PXEGEMINI",
                     font=ctk.CTkFont(size=20, weight="bold"),
                     text_color=C["text"]).pack(anchor="w")
        ctk.CTkLabel(brand, text="HTTPDisk Edition",
                     font=ctk.CTkFont(size=11),
                     text_color=C["text2"]).pack(anchor="w")

        sep = ctk.CTkFrame(sb, height=1, fg_color=C["border"])
        sep.grid(row=1, column=0, padx=16, pady=8, sticky="ew")

        # Navegacao
        nav = [
            ("Dashboard",   "dash"),
            ("ISO Manager", "iso"),
            ("Releases",    "releases"),
            ("Settings",    "settings"),
        ]
        self._nav_btns = {}
        for i, (label, key) in enumerate(nav):
            btn = ctk.CTkButton(
                sb, text=label, font=ctk.CTkFont(size=13),
                fg_color="transparent", hover_color=C["hover"],
                text_color=C["text2"], height=36, anchor="w",
                command=lambda k=key: self.show_page(k))
            btn.grid(row=2 + i, column=0, padx=12, pady=2, sticky="ew")
            self._nav_btns[key] = btn

        # Status LED
        status_box = ctk.CTkFrame(sb, fg_color="transparent")
        status_box.grid(row=6, column=0, padx=12, pady=16, sticky="s")
        self.status_led  = ctk.CTkLabel(status_box, text="●",
                                        text_color=C["muted"],
                                        font=ctk.CTkFont(size=16))
        self.status_led.grid(row=0, column=0, padx=(0, 6))
        self.status_txt  = ctk.CTkLabel(status_box, text="OFFLINE",
                                        font=ctk.CTkFont(size=12, weight="bold"),
                                        text_color=C["text2"])
        self.status_txt.grid(row=0, column=1)
        self.sidebar_ver = ctk.CTkLabel(status_box,
                                        text=f"v{APP_VERSION}",
                                        font=ctk.CTkFont(size=10),
                                        text_color=C["muted"])
        self.sidebar_ver.grid(row=1, column=0, columnspan=2, pady=(4, 0))

    def _build_main(self):
        container = ctk.CTkFrame(self, corner_radius=0, fg_color=C["bg"])
        container.grid(row=0, column=1, sticky="nsew")
        self.pages = {}
        self._build_dash(container)
        self._build_iso_page(container)
        self._build_releases(container)
        self._build_settings(container)

    def show_page(self, key):
        for k, page in self.pages.items():
            page.place_forget()
        self.pages[key].place(relx=0, rely=0, relwidth=1, relheight=1)
        # Destaca botao ativo (Heuristica: Localizacao atual)
        for k, btn in self._nav_btns.items():
            btn.configure(
                fg_color=C["hover"] if k == key else "transparent",
                text_color=C["text"] if k == key else C["text2"])
        if key == "iso":
            self._refresh_iso_list()

    # ----------------------------------------------------------
    # PAGINA: DASHBOARD
    # ----------------------------------------------------------

    def _build_dash(self, parent):
        page = ctk.CTkScrollableFrame(parent, fg_color=C["bg"])
        self.pages["dash"] = page

        # Cabecalho
        hdr = ctk.CTkFrame(page, fg_color="transparent")
        hdr.pack(fill="x", padx=30, pady=(20, 10))
        ctk.CTkLabel(hdr, text="Dashboard",
                     font=ctk.CTkFont(size=28, weight="bold"),
                     text_color=C["text"]).pack(anchor="w")
        ctk.CTkLabel(hdr, text="Gerencie servidores e acompanhe o boot em tempo real.",
                     font=ctk.CTkFont(size=13),
                     text_color=C["text2"]).pack(anchor="w")

        # Cards de status (Heuristica: Visibilidade do estado)
        cards = ctk.CTkFrame(page, fg_color="transparent")
        cards.pack(fill="x", padx=30, pady=10)
        cards.grid_columnconfigure((0, 1, 2), weight=1)
        self.card_dhcp = StatusCard(cards, "DHCP / ProxyDHCP")
        self.card_dhcp.grid(row=0, column=0, padx=(0, 6), sticky="ew")
        self.card_tftp = StatusCard(cards, "TFTP")
        self.card_tftp.grid(row=0, column=1, padx=3, sticky="ew")
        self.card_http = StatusCard(cards, "HTTP")
        self.card_http.grid(row=0, column=2, padx=(6, 0), sticky="ew")

        # Readiness
        ready_box = ctk.CTkFrame(page, height=44, fg_color=C["card"],
                                 corner_radius=10, border_width=1,
                                 border_color=C["border"])
        ready_box.pack(padx=30, fill="x", pady=8)
        self.readiness_lbl = ctk.CTkLabel(
            ready_box,
            text="  Verificando sistema...",
            font=ctk.CTkFont(size=13), text_color=C["text2"])
        self.readiness_lbl.pack(pady=8, anchor="w")

        self.iso_count_lbl = ctk.CTkLabel(
            page, text="",
            font=ctk.CTkFont(size=12), text_color=C["accent"])
        self.iso_count_lbl.pack(pady=2)

        # Botoes de acao
        btn_row = ctk.CTkFrame(page, fg_color="transparent")
        btn_row.pack(pady=10, fill="x", padx=30)

        self.start_btn = ctk.CTkButton(
            btn_row, text="▶  START ENGINE", height=44,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=C["green"], hover_color="#2ea043",
            command=self.start_engine)
        self.start_btn.pack(side="left", padx=4, fill="x", expand=True)

        self.stop_btn = ctk.CTkButton(
            btn_row, text="■  STOP ENGINE", height=44,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=C["red"], hover_color="#da3633",
            command=self.stop_engine, state="disabled")
        self.stop_btn.pack(side="left", padx=4, fill="x", expand=True)

        self.fix_btn = ctk.CTkButton(
            btn_row, text="��  Fix Firewall", height=44,
            font=ctk.CTkFont(size=13),
            fg_color=C["card"], hover_color=C["hover"],
            text_color=C["text"], border_width=1,
            border_color=C["border"],
            command=self.run_network_fix, width=180)
        self.fix_btn.pack(side="left", padx=4)

        ctk.CTkLabel(page,
                     text="F5 = Start  |  Esc = Stop  |  Ctrl+R = Refresh ISO",
                     font=ctk.CTkFont(size=11),
                     text_color=C["muted"]).pack(pady=(4, 8))

        # Console de logs
        ctk.CTkLabel(page, text="LOGS EM TEMPO REAL",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=C["muted"]).pack(anchor="w", padx=30)
        self.console = ctk.CTkTextbox(
            page, height=260,
            fg_color=C["input"], text_color=C["green"],
            font=ctk.CTkFont(family="Consolas", size=12),
            border_width=1, border_color=C["border"],
            corner_radius=10)
        self.console.pack(padx=30, pady=(4, 20), fill="both", expand=True)
        self.console.configure(state="normal")
        self.console.insert("0.0",
            f"PXEGEMINI HTTPDisk v{APP_VERSION} - Pronto.\n")
        self.console.configure(state="disabled")

        self._attach_log_widget()

    def _update_version_labels(self):
        menu_version = int(self.config.get("menu_version", 0) or 0)
        last_menu = self.config.get("last_menu_generated", "") or "nunca"
        if hasattr(self, "sidebar_ver"):
            self.sidebar_ver.configure(text=f"v{APP_VERSION} | menu {menu_version}")
        if hasattr(self, "status_txt") and not self.running:
            self.status_txt.configure(text="OFFLINE")
        if hasattr(self, "readiness_lbl") and not self.running:
            self.readiness_lbl.configure(text=f"  Pronto. Menu {menu_version} | {last_menu}", text_color=C["text2"])

    def _is_virtual_adapter_name(self, name):
        lowered = (name or "").lower()
        blocked_tokens = (
            "loopback",
            "virtual",
            "vbox",
            "vmware",
            "hyper-v",
            "veth",
            "docker",
            "hamachi",
            "tunnel",
            "pseudo",
            "bluetooth",
            "isatap",
            "teredo",
        )
        return any(token in lowered for token in blocked_tokens)

    def _collect_network_adapters(self):
        adapters = []
        stats = psutil.net_if_stats()
        addresses = psutil.net_if_addrs()
        link_family = getattr(psutil, "AF_LINK", None)

        for name, entries in addresses.items():
            if self._is_virtual_adapter_name(name):
                continue

            ipv4 = None
            mac = ""
            for entry in entries:
                family = getattr(entry, "family", None)
                if family == socket.AF_INET and entry.address and not entry.address.startswith("127."):
                    ipv4 = entry
                elif family == link_family and entry.address:
                    mac = entry.address

            if not ipv4:
                continue

            stat = stats.get(name)
            is_up = bool(stat.isup) if stat else False
            adapters.append({
                "name": name,
                "ip": ipv4.address,
                "netmask": ipv4.netmask or self.config.get("subnet_mask", "255.255.255.0"),
                "mac": mac,
                "is_up": is_up,
                "status": "UP" if is_up else "DOWN",
                "display": f"{name} | {ipv4.address} | {'UP' if is_up else 'DOWN'}",
            })

        adapters.sort(key=lambda item: (not item["is_up"], item["name"].lower()))
        active = [item for item in adapters if item["is_up"]]
        return active if active else adapters

    def _refresh_adapters_initial(self, initial=False):
        if not hasattr(self, "adapter_menu"):
            return

        adapters = self._collect_network_adapters()
        self._adapter_map = {}

        if not adapters:
            self.adapter_menu.configure(values=["Nenhum adaptador IPv4 encontrado"], state="disabled")
            self.adapter_var.set("Nenhum adaptador IPv4 encontrado")
            self._selected_adapter = ""
            self.config["selected_adapter"] = ""
            self.config["selected_adapter_display"] = ""
            if hasattr(self, "adapter_status_label"):
                self.adapter_status_label.configure(text="Nenhum adaptador IPv4 encontrado.", text_color=C["orange"])
            self._update_version_labels()
            return

        values = []
        for adapter in adapters:
            self._adapter_map[adapter["display"]] = adapter
            values.append(adapter["display"])

        self.adapter_menu.configure(values=values, state="normal")

        preferred_display = self.config.get("selected_adapter_display", "")
        preferred_name = self.config.get("selected_adapter", "")
        choice = None
        for display, adapter in self._adapter_map.items():
            if display == preferred_display or adapter["name"] == preferred_name:
                choice = display
                break
        if choice is None:
            choice = next((display for display, adapter in self._adapter_map.items() if adapter["is_up"]), values[0])

        self.adapter_var.set(choice)
        self._apply_adapter_choice(choice, trigger_prepare=False, persist=False, log_selection=False)
        if not initial:
            logging.info("Lista de adaptadores atualizada.")

    def _apply_adapter_choice(self, choice, trigger_prepare=False, persist=True, log_selection=True):
        adapter = self._adapter_map.get(choice)
        if not adapter:
            return

        self._selected_adapter = adapter["name"]
        self.adapter_var.set(choice)

        if hasattr(self, "entry_ip"):
            self.entry_ip.delete(0, tk.END)
            self.entry_ip.insert(0, adapter["ip"])

        if hasattr(self, "adapter_status_label"):
            label_color = C["green"] if adapter["is_up"] else C["orange"]
            self.adapter_status_label.configure(
                text=f"{adapter['name']} | {adapter['ip']} | {adapter['status']} | mask {adapter['netmask']}",
                text_color=label_color,
            )

        if log_selection:
            logging.info("Adaptador selecionado: %s -> %s", adapter["name"], adapter["ip"])

        if persist:
            self._sync_ui_settings(validate_ip=False)
            try:
                save_config(self.config)
                self.iso_manager.generate_menu()
            except Exception as exc:
                logging.warning("Falha ao salvar configuracao do adaptador: %s", exc)

        self._validate_ip_live()
        self._update_version_labels()

        if trigger_prepare and self.auto_prep.get():
            self.after(0, self._scan_folder)
        elif persist and self.running:
            self._restart_engine_after_change()

    def _on_adapter_selected(self, choice):
        self._apply_adapter_choice(choice, trigger_prepare=True, persist=True, log_selection=True)

    def _sync_ui_settings(self, validate_ip=True):
        if hasattr(self, "entry_ip"):
            ip = self.entry_ip.get().strip()
        else:
            ip = self.config.get("server_ip", "0.0.0.0").strip()

        if validate_ip and (not ip or not is_valid_ip(ip)):
            raise ValueError("IP invalido")

        current_adapter = self._adapter_map.get(self.adapter_var.get())
        if current_adapter:
            self._selected_adapter = current_adapter["name"]
            self.config["subnet_mask"] = current_adapter["netmask"] or self.config.get("subnet_mask", "255.255.255.0")

        self.config["server_ip"] = ip
        self.config["iso_dir"] = self.entry_iso_dir.get().strip() or self.config.get("iso_dir", r"E:\\")
        self.config["mode_proxy"] = self.proxy_var.get()
        self.config["compat_profile"] = self.compat_var.get()
        self.config["network_profile"] = self.network_var.get()
        self.config["auto_prepare_on_adapter"] = self.auto_prep.get()
        self.config["selected_adapter"] = self._selected_adapter
        self.config["selected_adapter_display"] = self.adapter_var.get()
        self.config["app_version"] = APP_VERSION

        self.iso_manager.config.update(self.config)
        self.iso_manager.iso_dir = self.config["iso_dir"]
        self.iso_manager.extract_dir = self.config.get("extract_dir", self.iso_manager.extract_dir)
        self.iso_manager.boot_dir = self.config.get("boot_dir", self.iso_manager.boot_dir)
        return ip

    def _restart_engine_after_change(self):
        if not self.running:
            return
        logging.info("Reiniciando engine para aplicar alteracoes...")
        self.stop_engine()
        self.after(1000, self.start_engine)

    def _build_iso_page(self, parent):
        page = ctk.CTkScrollableFrame(parent, fg_color=C["bg"])
        self.pages["iso"] = page

        ctk.CTkLabel(page, text="ISO Manager", font=ctk.CTkFont(size=26, weight="bold"), text_color=C["text"]).pack(pady=(16, 4))
        ctk.CTkLabel(page, text="Adicione ISOs de boot. O sistema detecta automaticamente o tipo (WinPE, Linux, UEFI).",
                     font=ctk.CTkFont(size=12), text_color=C["text2"]).pack(pady=(0, 12))

        top_btns = ctk.CTkFrame(page, fg_color="transparent")
        top_btns.pack(pady=4)

        self.btn_add_iso = ctk.CTkButton(top_btns, text="+  Adicionar ISO", height=34, fg_color=C["green"],
                                          hover_color="#2ea043", font=ctk.CTkFont(size=13, weight="bold"),
                                          command=self._add_iso_dialog)
        self.btn_add_iso.pack(side="left", padx=4)

        self.btn_add_folder = ctk.CTkButton(top_btns, text="  Scanear Pasta  ", height=34, fg_color=C["card"],
                                             hover_color=C["hover"], text_color=C["text"],
                                             border_width=1, border_color=C["border"],
                                             font=ctk.CTkFont(size=13),
                                             command=self._scan_folder)
        self.btn_add_folder.pack(side="left", padx=4)

        self.btn_scan_drives = ctk.CTkButton(top_btns, text="  Scanear Discos  ", height=34, fg_color=C["card"],
                                              hover_color=C["hover"], text_color=C["text"],
                                              border_width=1, border_color=C["border"],
                                              font=ctk.CTkFont(size=13),
                                              command=self._scan_drives)
        self.btn_scan_drives.pack(side="left", padx=4)

        list_frame = ctk.CTkFrame(page, fg_color=C["card"], corner_radius=12, border_width=1, border_color=C["border"])
        list_frame.pack(padx=30, pady=8, fill="both", expand=True)

        list_header = ctk.CTkFrame(list_frame, fg_color=C["border"], corner_radius=0)
        list_header.pack(fill="x", padx=0, pady=0)

        ctk.CTkLabel(list_header, text="ISO", width=280, anchor="w", font=ctk.CTkFont(weight="bold", size=12), text_color=C["text"]).pack(side="left", padx=14, pady=8)
        ctk.CTkLabel(list_header, text="Tipo", width=120, anchor="w", font=ctk.CTkFont(weight="bold", size=12), text_color=C["text"]).pack(side="left", padx=5, pady=8)
        ctk.CTkLabel(list_header, text="Tamanho", width=100, anchor="w", font=ctk.CTkFont(weight="bold", size=12), text_color=C["text"]).pack(side="left", padx=5, pady=8)

        self.iso_listbox = ctk.CTkScrollableFrame(list_frame, fg_color="transparent")
        self.iso_listbox.pack(fill="both", expand=True, padx=0, pady=0)

        bottom_btns = ctk.CTkFrame(page, fg_color="transparent")
        bottom_btns.pack(pady=8)

        self.btn_refresh = ctk.CTkButton(bottom_btns, text="  Atualizar Lista  ", height=34, command=self._refresh_iso_list,
                                          fg_color=C["card"], hover_color=C["hover"], text_color=C["text"],
                                          border_width=1, border_color=C["border"], font=ctk.CTkFont(size=13))
        self.btn_refresh.pack(side="left", padx=4)

        self.btn_remove_iso = ctk.CTkButton(bottom_btns, text="Remover Selecionada", height=34,
                                             fg_color=C["card"], hover_color=C["hover"], text_color=C["text2"],
                                             border_width=1, border_color=C["border"],
                                             command=self._remove_iso, font=ctk.CTkFont(size=13))
        self.btn_remove_iso.pack(side="left", padx=4)

        self.btn_regen_menu = ctk.CTkButton(bottom_btns, text="Regenerar Menu iPXE", height=34,
                                             fg_color=C["card"], hover_color=C["hover"], text_color=C["orange"],
                                             border_width=1, border_color=C["border"],
                                             command=self._regen_menu, font=ctk.CTkFont(size=13))
        self.btn_regen_menu.pack(side="left", padx=4)

        self.iso_info = ctk.CTkLabel(page, text="Nenhuma ISO adicionada. Clique em 'Adicionar ISO' para começar.",
                                     text_color=C["muted"], font=ctk.CTkFont(size=12))
        self.iso_info.pack(pady=4)

        self._iso_rows = {}
        self._refresh_iso_list()

    def _build_releases(self, parent):
        page = ctk.CTkFrame(parent, fg_color=C["bg"])
        self.pages["releases"] = page

        ctk.CTkLabel(page, text="Historico de Versoes", font=ctk.CTkFont(size=26, weight="bold"), text_color=C["text"]).pack(pady=(16, 4))
        history = ctk.CTkTextbox(page, fg_color=C["card"], font=ctk.CTkFont(family="Consolas", size=13),
                                  wrap="word", border_width=1, border_color=C["border"], corner_radius=12)
        history.pack(padx=30, pady=8, fill="both", expand=True)

        changelog = f"""
[v{APP_VERSION} - hotfix 2026-04-23] Dell UEFI PXE Fix
  FIX  Porta 4011 (BINL/ProxyDHCP) agora sempre aberta, independente do
       modo (proxy ou DHCP completo). Dell/HP UEFI envia um segundo DISCOVER
       diretamente a :4011 apos o OFFER; sem resposta ali o firmware
       repetia DISCOVER infinitamente sem progredir para REQUEST.
  FIX  Option 43 (vendor-encapsulated-options) estava malformada.
       Dell UEFI valida a estrutura das sub-opcoes antes de aceitar o OFFER.
       Sub-opcao 6 (PXE_DISCOVERY_CONTROL=0x08) e sub-opcao 10 (menu prompt)
       agora enviadas com o formato correto.
  FIX  Broadcast flag (bit 15 do campo flags) agora sempre forcado.
       Cliente sem IP nao consegue receber unicast; flag condicional
       causava o Dell descartar silenciosamente o OFFER.
  FIX  _reply_targets: respostas agora vao para 255.255.255.255:68 primeiro;
       unicast direto ao cliente apenas quando ele ja possui IP (ciaddr != 0).
  FIX  Mesmas correcoes aplicadas em SERVIDORCODE/core/dhcp.py.
  ADD  INSTRUCTIONS_FOR_AGENT.md adicionado com documentacao completa do projeto.

[v{APP_VERSION}] HTTPDisk Edition
  +  Menu iPXE dinamico com suporte a HTTPDisk
  +  Selecao de adaptador de rede com preenchimento automatico do IP
  +  Filtro de adaptadores virtuais/loopback (Docker, Hyper-V, VBox, etc.)
  +  Botao de preparacao completa da biblioteca de ISOs (scanear pasta/discos)
  +  Controle de versao do menu e historico de versao na aba Releases
  +  Modo ProxyDHCP (porta 4011) para coexistir com roteadores existentes
  +  Perfis de compatibilidade: auto / dell / lenovo
  +  Perfis de rede: isolated / mixed
  +  Restart automatico dos servicos ao trocar de adaptador
  +  Atalhos de teclado: F5=Start, Esc=Stop, Ctrl+R=Refresh ISO

[v5.6] Selecao de adaptador e pool DHCP robusto
  +  Pool DHCP valida sub-rede e ajusta faixa automaticamente
  +  Gateway e DNS opcionais no perfil mixed
  +  Icone de status por servidor (DHCP / TFTP / HTTP)

[v5.3] HTTPDisk PEcmd Bypass
  +  Montagem automatica do HTTPDisk no WinPE via startnet.cmd
  +  Fallback para SMB quando httpdisk falha
  +  Injecao dos binarios httpdisk.sys/httpdisk.exe via wimboot initrd

[v5.0-v5.2] Boot chain UEFI iPXE + wimboot
  +  Suporte a snponly.efi para UEFI BIOS Dell
  +  Geracao de menu.ipxe com entradas por tipo (wimboot / linux / uefi)
  +  Servidor TFTP com negociacao de blksize e tsize
  +  Servidor HTTP com suporte completo a Range requests (necessario para HTTPDisk)
"""
        history.insert("0.0", changelog.strip())
        history.configure(state="disabled")

    def _build_settings(self, parent):
        page = ctk.CTkFrame(parent, fg_color=C["bg"])
        self.pages["settings"] = page

        ctk.CTkLabel(page, text="Configuracoes", font=ctk.CTkFont(size=26, weight="bold"), text_color=C["text"]).pack(pady=(16, 4))
        ctk.CTkLabel(page, text="Ajuste os parametros da rede e do sistema.", font=ctk.CTkFont(size=12), text_color=C["text2"]).pack(pady=(0, 16))

        card = ctk.CTkFrame(page, fg_color=C["card"], corner_radius=12, border_width=1, border_color=C["border"])
        card.pack(padx=40, pady=0, fill="both", expand=True, ipady=20)

        ctk.CTkLabel(card, text="IP Estático do Servidor", font=ctk.CTkFont(size=14, weight="bold"), text_color=C["text"]).pack(pady=(24, 2))
        ctk.CTkLabel(card, text="IP fixo da máquina que vai rodar o PXE. Deve estar na mesma rede dos clientes.",
                     font=ctk.CTkFont(size=11), text_color=C["muted"]).pack()
        self.entry_ip = ctk.CTkEntry(card, width=250, height=38, font=ctk.CTkFont(size=15), justify="center",
                                      fg_color=C["input"], border_width=1, border_color=C["border"])
        self.entry_ip.insert(0, self.config.get("server_ip", "0.0.0.0"))
        self.entry_ip.pack(pady=8)
        self.entry_ip.bind("<KeyRelease>", lambda e: self._validate_ip_live())

        self.ip_validate_label = ctk.CTkLabel(card, text="", font=ctk.CTkFont(size=11), text_color=C["red"])
        self.ip_validate_label.pack()

        ctk.CTkLabel(card, text="Adaptador de Rede", font=ctk.CTkFont(size=14, weight="bold"), text_color=C["text"]).pack(pady=(18, 2))
        ctk.CTkLabel(card, text="Escolha o adaptador ativo e o IP será preenchido automaticamente.",
                     font=ctk.CTkFont(size=11), text_color=C["muted"]).pack()
        self.adapter_menu = ctk.CTkOptionMenu(card, variable=self.adapter_var, values=["Carregando..."], width=320, height=34,
                                              command=self._on_adapter_selected)
        self.adapter_menu.pack(pady=6)
        self.adapter_status_label = ctk.CTkLabel(card, text="Nenhum adaptador selecionado.", font=ctk.CTkFont(size=11), text_color=C["muted"])
        self.adapter_status_label.pack()
        ctk.CTkButton(card, text="Atualizar adaptadores", height=30, fg_color=C["card"], hover_color=C["hover"],
                      text_color=C["text"], border_width=1, border_color=C["border"],
                      command=self._refresh_adapters_initial).pack(pady=(6, 0))

        ctk.CTkLabel(card, text="Pasta de busca ISO", font=ctk.CTkFont(size=14, weight="bold"), text_color=C["text"]).pack(pady=(16, 2))
        ctk.CTkLabel(card, text="Diretório padrão para escanear ISOs ao clicar em 'Scanear Pasta'.",
                     font=ctk.CTkFont(size=11), text_color=C["muted"]).pack()
        self.entry_iso_dir = ctk.CTkEntry(card, width=350, height=38, font=ctk.CTkFont(size=13), justify="center",
                                           fg_color=C["input"], border_width=1, border_color=C["border"])
        self.entry_iso_dir.insert(0, self.config.get("iso_dir", "E:\\"))
        self.entry_iso_dir.pack(pady=8)

        self.compat_var = ctk.StringVar(value=self.config.get("compat_profile", "auto"))
        ctk.CTkLabel(card, text="Perfil de compatibilidade", font=ctk.CTkFont(size=14, weight="bold"), text_color=C["text"]).pack(pady=(12, 2))
        self.compat_menu = ctk.CTkOptionMenu(card, variable=self.compat_var, values=["auto", "dell", "lenovo"], width=250, height=34)
        self.compat_menu.pack()

        self.network_var = ctk.StringVar(value=self.config.get("network_profile", "isolated"))
        ctk.CTkLabel(card, text="Perfil de rede", font=ctk.CTkFont(size=14, weight="bold"), text_color=C["text"]).pack(pady=(12, 2))
        self.network_menu = ctk.CTkOptionMenu(card, variable=self.network_var, values=["isolated", "mixed"], width=250, height=34)
        self.network_menu.pack()

        self.auto_prep = ctk.BooleanVar(value=self.config.get("auto_prepare_on_adapter", True))
        self.chk_auto_prep = ctk.CTkCheckBox(card, text="Preparar ISO automaticamente ao trocar adaptador",
                                             variable=self.auto_prep, font=ctk.CTkFont(size=13),
                                             text_color=C["text2"])
        self.chk_auto_prep.pack(pady=(16, 6))

        self.proxy_var = ctk.BooleanVar(value=self.config.get("mode_proxy", True))
        self.chk_proxy = ctk.CTkSwitch(card, text="Modo ProxyDHCP (recomendado quando já existe outro DHCP)",
                                       variable=self.proxy_var, font=ctk.CTkFont(size=13), text_color=C["text2"])
        self.chk_proxy.pack(pady=(4, 8))

        ctk.CTkLabel(card, text="Desative apenas se esta maquina for o unico servidor DHCP da rede.",
                     font=ctk.CTkFont(size=11), text_color=C["muted"]).pack()

        btn_save = ctk.CTkButton(card, text="SALVAR CONFIG", height=44, font=ctk.CTkFont(size=14, weight="bold"),
                                  fg_color=C["accent"], hover_color="#388bfd",
                                  command=self.save_settings)
        btn_save.pack(pady=20, padx=60, fill="x")

        self._refresh_adapters_initial(initial=True)

    def _validate_ip_live(self):
        val = self.entry_ip.get().strip()
        if not val:
            self.ip_validate_label.configure(text="")
        elif is_valid_ip(val):
            self.ip_validate_label.configure(text="", text_color=C["green"])
        else:
            self.ip_validate_label.configure(text="Formato de IP inválido (ex: 192.168.0.21)", text_color=C["red"])

    def check_readiness(self):
        errors = []
        import ctypes

        try:
            if not ctypes.windll.shell32.IsUserAnAdmin():
                errors.append("Precisa de privilegios de Administrador")
        except Exception:
            errors.append("Nao foi possivel validar privilegios de Administrador")

        http_port = int(self.config.get("http_port", 80))
        ports = [
            (http_port, socket.SOCK_STREAM),
            (int(self.config.get("dhcp_port", 67)), socket.SOCK_DGRAM),
            (int(self.config.get("tftp_port", 69)), socket.SOCK_DGRAM),
        ]
        if self.config.get("mode_proxy", True):
            ports.append((4011, socket.SOCK_DGRAM))
        for port, sock_type in ports:
            with socket.socket(socket.AF_INET, sock_type) as s:
                try:
                    s.bind(("", port))
                except Exception:
                    errors.append(f"Porta {port} ocupada")

        return errors

    def start_engine(self):
        if self.running:
            return
        threading.Thread(target=self._start_work, daemon=True).start()

    def _start_work(self):
        errors = self.check_readiness()
        if errors:
            self.after(0, lambda: self.readiness_lbl.configure(
                text=f"  ATENCAO: {' | '.join(errors)}", text_color=C["red"]))
            self.after(0, lambda: logging.warning("Sistema nao esta pronto. Verifique os itens acima."))
            self.after(0, lambda: self.start_btn.configure(state="normal"))
            self.after(0, lambda: self.stop_btn.configure(state="disabled"))
            return

        try:
            self._sync_ui_settings(validate_ip=True)
        except ValueError:
            self.after(0, lambda: messagebox.showerror(
                "IP Invalido",
                "O endereco IP esta em formato invalido.\nExemplo valido: 192.168.0.21",
            ))
            return

        self.iso_manager.generate_menu()

        try:
            self.servers["dhcp"] = DHCPD(self.config, logger=self.logger)
            self.servers["tftp"] = TFTPD(self.config, logger=self.logger)
            self.servers["http"] = HTTPD(self.config, logger=self.logger)

            threading.Thread(target=self.servers["dhcp"].listen, daemon=True).start()
            threading.Thread(target=self.servers["tftp"].listen, daemon=True).start()
            threading.Thread(target=self.servers["http"].listen, daemon=True).start()
        except Exception as exc:
            logging.error("Falha ao iniciar servidores: %s", exc)
            self.after(0, lambda: self.readiness_lbl.configure(text=f"  Erro ao iniciar: {exc}", text_color=C["red"]))
            self.after(0, self.stop_engine)
            return

        # SMB fallback para WinPE/Stretch/StrElec
        extract_base = self.config.get("extract_dir", os.path.join("data", "extracted"))
        sstr_path = os.path.abspath(os.path.join(extract_base, "strelec", "SSTR"))
        if not os.path.isdir(sstr_path):
            sstr_path = os.path.abspath(os.path.join(extract_base, "STRELEC", "SSTR"))
        if not os.path.isdir(sstr_path):
            sstr_path = os.path.abspath(os.path.join(extract_base, "strelec"))

        for share_name, share_path in [("SSTR", sstr_path), ("IMG", r"E:\Backup")]:
            try:
                subprocess.run(["net", "share", "/delete", share_name], capture_output=True, text=True)
                if os.path.isdir(share_path):
                    result = subprocess.run(
                        ["net", "share", f"{share_name}={os.path.normpath(share_path)}"],
                        capture_output=True,
                        text=True,
                    )
                    if result.returncode == 0:
                        logging.info("SMB Share %s criado: %s", share_name, share_path)
                    else:
                        logging.warning("Falha ao criar SMB share %s: %s", share_name, (result.stderr or result.stdout).strip())
            except Exception as exc:
                logging.warning("Nao foi possivel criar share %s: %s", share_name, exc)

        self.running = True
        mode_text = "ProxyDHCP" if self.config.get("mode_proxy", True) else "DHCP"
        self.after(0, lambda: self.card_dhcp.set_online(mode_text))
        self.after(0, lambda: self.card_tftp.set_online("Porta 69"))
        self.after(0, lambda: self.card_http.set_online(self.config.get("server_ip", "")))
        self.after(0, lambda: self.status_led.configure(text_color=C["green"]))
        self.after(0, lambda: self.status_txt.configure(text="ONLINE"))
        self.after(0, lambda: self.readiness_lbl.configure(text="  Sistema pronto.", text_color=C["green"]))
        self.after(0, lambda: self.start_btn.configure(state="disabled"))
        self.after(0, lambda: self.stop_btn.configure(state="normal"))
        self.after(0, self._update_version_labels)
        logging.info("PXEGEMINI Engine iniciado.")
        logging.info("Modo: %s | Compat: %s | Rede: %s", mode_text, self.config.get("compat_profile"), self.config.get("network_profile"))

    def stop_engine(self):
        if not self.running and not any(self.servers.values()):
            return

        self.running = False
        logging.info("Parando servidores...")

        for share_name in ["SSTR", "IMG"]:
            try:
                subprocess.run(["net", "share", "/delete", share_name], capture_output=True, text=True)
            except Exception:
                pass

        for key in ("dhcp", "tftp"):
            srv = self.servers.get(key)
            if srv:
                srv.running = False
                for attr in ("sock", "server_socket"):
                    sock = getattr(srv, attr, None)
                    if sock:
                        try:
                            sock.close()
                        except Exception:
                            pass
                if getattr(srv, "sock_binl", None):
                    try:
                        srv.sock_binl.close()
                    except Exception:
                        pass

        http_srv = self.servers.get("http")
        if http_srv:
            try:
                http_srv.stop()
            except Exception:
                pass

        self.servers = {"dhcp": None, "tftp": None, "http": None}
        self.after(0, lambda: self.card_dhcp.set_offline())
        self.after(0, lambda: self.card_tftp.set_offline())
        self.after(0, lambda: self.card_http.set_offline())
        self.after(0, lambda: self.status_led.configure(text_color=C["muted"]))
        self.after(0, lambda: self.status_txt.configure(text="OFFLINE"))
        self.after(0, lambda: self.start_btn.configure(state="normal"))
        self.after(0, lambda: self.stop_btn.configure(state="disabled"))
        self.after(0, self._update_version_labels)
        logging.info("Servidores parados.")

    def run_network_fix(self):
        if not messagebox.askokcancel(
            "Fix Firewall/Rede",
            "Isso vai modificar regras do Firewall do Windows.\nPortas 67, 69, 80, 4011 serao liberadas.\nContinuar?",
        ):
            logging.info("Fix cancelado pelo usuario.")
            return

        import ctypes
        import sys

        if getattr(sys, "frozen", False):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))

        paths_to_check = [
            os.path.join(base_path, "FIX_PXE.bat"),
            os.path.join(base_path, "_internal", "FIX_PXE.bat"),
            os.path.join(os.getcwd(), "FIX_PXE.bat"),
        ]

        bat_path = next((p for p in paths_to_check if os.path.exists(p)), None)
        if not bat_path:
            logging.error("FIX_PXE.bat nao encontrado.")
            return

        try:
            ctypes.windll.shell32.ShellExecuteW(None, "runas", bat_path, None, None, 1)
            logging.info("Fixer executado: %s", bat_path)
        except Exception as exc:
            logging.error("Falha ao rodar fixer: %s", exc)

    def save_settings(self):
        try:
            self._sync_ui_settings(validate_ip=True)
        except ValueError:
            messagebox.showerror(
                "IP Invalido",
                "O endereco IP esta em formato invalido.\nExemplo valido: 192.168.0.21",
            )
            logging.error("Tentativa de salvar IP invalido: %s", self.entry_ip.get().strip())
            return

        save_config(self.config)
        self.iso_manager.generate_menu()
        self._update_version_labels()
        logging.info("Configuracao salva com sucesso.")
        messagebox.showinfo("Sucesso", "Configuracao salva com sucesso.")

        if self.running:
            self._restart_engine_after_change()

    def _add_iso_dialog(self):
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        files = filedialog.askopenfilenames(
            title="Selecionar ISO(s) para adicionar",
            filetypes=[("Arquivos ISO", "*.iso"), ("Todos os arquivos", "*.*")],
        )
        root.destroy()

        if not files:
            return

        for f in files:
            iso_info = {
                "path": f,
                "name": os.path.basename(f),
                "size_mb": os.path.getsize(f) / (1024 * 1024),
            }
            threading.Thread(target=self._do_add_iso, args=(iso_info,), daemon=True).start()

    def _do_add_iso(self, iso_info):
        result = self.iso_manager.add_iso(iso_info)
        if result.get("success"):
            self.after(0, lambda: logging.info("ISO '%s' adicionada com sucesso!", iso_info["name"]))
            self.after(0, self._refresh_iso_list)
            self.after(0, self.iso_manager.generate_menu)
        else:
            self.after(0, lambda: logging.error(
                "Falha ao adicionar '%s': %s",
                iso_info["name"],
                result.get("error", "desconhecido"),
            ))

    def _scan_folder(self):
        target_dir = self.entry_iso_dir.get().strip() or self.config.get("iso_dir", r"E:\\")
        threading.Thread(target=self._do_scan_folder, args=(target_dir,), daemon=True).start()

    def _do_scan_folder(self, folder):
        logging.info("Escaneando pasta: %s", folder)
        isos = self.iso_manager.find_isos_in_dir(folder)
        if not isos:
            self.after(0, lambda: logging.warning("Nenhuma ISO encontrada em %s", folder))
            return

        self.after(0, lambda: logging.info("Encontradas %d ISO(s) em %s", len(isos), folder))
        for iso in isos:
            threading.Thread(target=self._do_add_iso, args=(iso,), daemon=True).start()
        self.after(2000, self._refresh_iso_list)

    def _scan_drives(self):
        if not messagebox.askokcancel(
            "Scanear Discos",
            "Vou escanear todos os discos por arquivos .iso.\nIsso pode demorar alguns minutos.\nContinuar?",
        ):
            logging.info("Scan de discos cancelado pelo usuario.")
            return
        threading.Thread(target=self._do_scan_drives, daemon=True).start()

    def _do_scan_drives(self):
        logging.info("Escaneando todos os discos por ISOs...")
        isos = self.iso_manager.find_all_isos()
        if not isos:
            self.after(0, lambda: logging.warning("Nenhuma ISO encontrada nos discos."))
            return

        seen = set()
        unique = []
        for iso in isos:
            if iso["path"] not in seen:
                seen.add(iso["path"])
                unique.append(iso)

        self.after(0, lambda: logging.info("Encontradas %d ISO(s) nos discos.", len(unique)))
        for iso in unique:
            threading.Thread(target=self._do_add_iso_scanned, args=(iso,), daemon=True).start()
        self.after(3000, self._refresh_iso_list)

    def _do_add_iso_scanned(self, iso):
        result = self.iso_manager.add_iso(iso)
        if result.get("success"):
            logging.info("ISO '%s' adicionada!", iso["name"])
        else:
            logging.error("Falha: %s - %s", iso["name"], result.get("error", "unknown"))
        self.after(0, self._refresh_iso_list)
        self.after(0, self.iso_manager.generate_menu)

    def _refresh_iso_list(self):
        for key, row in list(self._iso_rows.items()):
            try:
                row.destroy()
            except Exception:
                pass
        self._iso_rows.clear()

        isos = self.iso_manager.list_added_isos()
        if hasattr(self, "iso_count_lbl"):
            self.iso_count_lbl.configure(text=f"{len(isos)} ISO(s) configurada(s)" if isos else "")

        if not hasattr(self, "iso_listbox"):
            return

        for child in self.iso_listbox.winfo_children():
            try:
                child.destroy()
            except Exception:
                pass

        if not isos:
            empty_label = ctk.CTkLabel(
                self.iso_listbox,
                text="Nenhuma ISO adicionada ainda.\nClique em 'Adicionar ISO' para comecar.",
                text_color=C["muted"],
                font=ctk.CTkFont(size=13),
            )
            empty_label.pack(pady=50)
            self._iso_rows["_empty"] = empty_label
            if hasattr(self, "iso_info"):
                self.iso_info.configure(text="Nenhuma ISO adicionada.")
            return

        if hasattr(self, "iso_info"):
            self.iso_info.configure(text="Selecione uma acao ou atualize a lista.")

        type_colors = {
            "wimboot": C["green"],
            "linux": C["accent"],
            "squashfs": C["accent"],
            "uefi": C["orange"],
            "unknown": C["orange"],
        }

        for iso in isos:
            key = iso["key"]
            name_display = iso.get("name", key)
            iso_type = iso.get("type", "unknown")
            size_mb = iso.get("size_mb", 0)
            type_color = type_colors.get(iso_type, C["text2"])

            row = ctk.CTkFrame(
                self.iso_listbox,
                fg_color=C["card"],
                corner_radius=8,
                border_width=1,
                border_color=C["border"],
            )
            row.pack(fill="x", padx=6, pady=2)

            ctk.CTkLabel(row, text=name_display, width=280, anchor="w", font=ctk.CTkFont(size=12), text_color=C["text"]).pack(side="left", padx=12)
            ctk.CTkLabel(row, text=f"[{iso_type}]", width=120, anchor="w", font=ctk.CTkFont(size=12, weight="bold"), text_color=type_color).pack(side="left", padx=5)
            ctk.CTkLabel(row, text=f"{size_mb:.0f} MB", width=100, anchor="w", font=ctk.CTkFont(size=11), text_color=C["text2"]).pack(side="left", padx=5)

            rm_btn = ctk.CTkButton(
                row,
                text="Remover",
                width=64,
                height=26,
                fg_color=C["card"],
                hover_color=C["hover"],
                border_width=1,
                border_color=C["red"],
                text_color=C["red"],
                font=ctk.CTkFont(size=11),
                command=lambda k=key: self._remove_iso_by_key(k),
            )
            rm_btn.pack(side="right", padx=8)

            self._iso_rows[key] = row

    def _remove_iso(self):
        logging.info("Use o botao 'Remover' na lista para remover uma ISO.")

    def _remove_iso_by_key(self, key):
        if not messagebox.askokcancel(
            "Remover ISO",
            f"Remover a ISO '{key}'?\n\nOs arquivos extraidos serao apagados.",
        ):
            return

        if self.iso_manager.remove_iso(key):
            logging.info("ISO '%s' removida com sucesso.", key)
            self._refresh_iso_list()
            self.iso_manager.generate_menu()
        else:
            logging.error("Falha ao remover ISO '%s'. Pode estar em uso.", key)

    def _regen_menu(self):
        self.iso_manager.generate_menu()
        self._update_version_labels()
        logging.info("menu.ipxe regenerado com sucesso.")


if __name__ == "__main__":
    app = PXEGEMINIApp()
    app.mainloop()

