import customtkinter as ctk
import threading
import logging
import time
import os
import psutil
import socket
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
        self.title("PXEGEMINI - Antigravity Edition v4.0")
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

        self.btn_iso = ctk.CTkButton(self.sidebar, text="ISO MANAGER", command=lambda: self.show_page("iso"))
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
        
        # Header (Estética e Visibilidade de Status de Nielsen)
        header = ctk.CTkLabel(page, text="Network Boot Control", font=ctk.CTkFont(size=32, weight="bold"))
        header.pack(pady=(20, 5))
        sub_header = ctk.CTkLabel(page, text="Gerencie o motor PXE e acompanhe a frota cliente em tempo real.", font=ctk.CTkFont(size=14), text_color="gray")
        sub_header.pack(pady=(0, 20))

        # Readiness Box (Prevenção de Erros de Nielsen)
        self.readiness_box = ctk.CTkFrame(page, height=60, fg_color="#2c3e50", corner_radius=10)
        self.readiness_box.pack(padx=40, fill="x", pady=10)
        self.readiness_label = ctk.CTkLabel(self.readiness_box, text="Scanning System Readiness...", font=ctk.CTkFont(size=14, weight="bold"))
        self.readiness_label.pack(pady=15)

        # Action Buttons
        button_container = ctk.CTkFrame(page, fg_color="transparent")
        button_container.pack(pady=20, fill="x", padx=40)
        
        self.start_btn = ctk.CTkButton(button_container, text="▶ START ENGINE", height=50, font=ctk.CTkFont(size=16, weight="bold"), 
                                       fg_color="#2ecc71", hover_color="#27ae60", command=self.start_engine)
        self.start_btn.pack(side="left", padx=10, expand=True, fill="x")

        self.stop_btn = ctk.CTkButton(button_container, text="⏹ STOP ENGINE", height=50, font=ctk.CTkFont(size=16, weight="bold"), 
                                      fg_color="#e74c3c", hover_color="#c0392b", command=self.stop_engine, state="disabled")
        self.stop_btn.pack(side="right", padx=10, expand=True, fill="x")

        # Console (Feedback Real)
        console_label = ctk.CTkLabel(page, text="REAL-TIME LOGS", font=ctk.CTkFont(size=12, weight="bold"), text_color="#A0A0A0")
        console_label.pack(pady=(10, 0), anchor="w", padx=40)
        self.console = ctk.CTkTextbox(page, height=300, fg_color="#0a0a0a", text_color="#2ecc71", font=ctk.CTkFont(family="Consolas"))
        self.console.pack(padx=40, pady=(5, 20), fill="both", expand=True)
        self.console.insert("0.0", "PXEGEMINI Antigravity Boot System Initialized.\n")
        self.console.configure(state="disabled")

    def create_iso_page(self):
        page = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.pages["iso"] = page
        
        ctk.CTkLabel(page, text="ISO & Component Management", font=ctk.CTkFont(size=28, weight="bold")).pack(pady=20)
        
        card = ctk.CTkFrame(page, fg_color="#242424", corner_radius=15)
        card.pack(padx=40, pady=20, fill="both", expand=True)

        info_box = ctk.CTkTextbox(card, height=150, fg_color="transparent", font=ctk.CTkFont(size=15), wrap="word")
        info_box.pack(padx=20, pady=20, fill="both", expand=True)
        info_box.insert("0.0", "⚙️ Prevenção de Erros Sergei Strelec:\n\n1. Coloque 'STRELEC.ISO' na partição E:\\.\n2. Clique no 'AUTO-CONFIGURE STRELEC'.\n3. O sistema extrairá rigorosamente o BCD, Fontes e Módulos WIM para solucionar distorções e perdas UEFI.")
        info_box.configure(state="disabled")

        btn_auto = ctk.CTkButton(card, text="⚡ AUTO-CONFIGURE STRELEC", height=50, font=ctk.CTkFont(size=16, weight="bold"), command=self.run_strelec_config)
        btn_auto.pack(pady=20, padx=40, fill="x")

    def create_releases_page(self):
        page = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.pages["releases"] = page
        
        ctk.CTkLabel(page, text="🚀 Histórico de Evolução (Controle de Versões)", font=ctk.CTkFont(size=28, weight="bold")).pack(pady=20)
        
        history = ctk.CTkTextbox(page, fg_color="#141414", font=ctk.CTkFont(size=14), wrap="word")
        history.pack(padx=40, pady=10, fill="both", expand=True)
        
        changelog = """
# v4.0 (Atual) - Otimização de Memória e SMB Share
- Fix Crítico: Resolvido estouro de RAM no notebook (múltiplas cópias do wimboot).
- Feature: Servidor SMB Compartilhado para carregar programas do Strelec.
- Feature: Extração assíncrona automática dos 11 GB da ISO para a pasta SSTR.
- Fix: Aliases BCD e Fonts agora utilizam o padrão backslash do Strelec.
- Atalho: Novo ícone v4.0 com Executável único na área de trabalho.

# v3.0 - Estabilidade e Automação Total
- Feature: Novo sistema de busca interna em todos os discos por arquivos Strelec.
- Fix: Resolvido erro de "wimboot Not Found" em conexões HTTP.
- Fix: Ajustado o aliasing do BCD e Fonts para boot limpo em Dell/Lenovo.
- Atalho: Gerado novo ícone v3 no Desktop para acesso rápido.

# v2.2 - UEFI Power
- Troca do binário de inicialização para snponly.efi (Drivers nativos).
- Resolvido o erro "No more network devices".
- Início da busca global por ISOs.

# v2.1 - Interface & Log
- Corrigido erro de visualização de cores no CTkFont.
- Aba de RELEASES adicionada para controle de versões.
- Crash Logger integrado para diagnósticos fatais.
"""
        history.insert("0.0", changelog.strip())
        history.configure(state="disabled")

        btn_export = ctk.CTkButton(page, text="📤 EXPORT DEBUG LOGS", command=self.export_logs)
        btn_export.pack(pady=10)

    def export_logs(self):
        import shutil
        desktop = os.path.join(os.environ["USERPROFILE"], "Desktop")
        target = os.path.join(desktop, "PXEGEMINI_DEBUG_LOG.txt")
        # In a real app we'd get the actual log file, for now we save the console content
        content = self.console.get("1.0", "end")
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)
        logging.info(f"Logs exportados para o Desktop: {target}")

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
        
        # Proxy Mode
        self.proxy_var = ctk.BooleanVar(value=self.config.get("mode_proxy", True))
        self.chk_proxy = ctk.CTkSwitch(card, text="ProxyDHCP Mode (Evita conflito com DHCP Corporativo)", variable=self.proxy_var, font=ctk.CTkFont(size=14))
        self.chk_proxy.pack(pady=30)

        btn_save = ctk.CTkButton(card, text="💾 SAVE AND RESTART", height=50, font=ctk.CTkFont(size=16, weight="bold"), command=self.save_settings)
        btn_save.pack(pady=20, padx=80, fill="x")

    def show_page(self, name):
        for p in self.pages.values(): p.pack_forget()
        self.pages[name].pack(fill="both", expand=True)

    def setup_logging(self):
        root = logging.getLogger()
        handler = LogHandler(self.console)
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', "%H:%M:%S")
        handler.setFormatter(formatter)
        root.addHandler(handler)
        root.setLevel(logging.INFO)

    def check_readiness(self):
        # Nielsen Heuristic #5: Error Prevention
        errors = []
        # Check Admin
        import ctypes
        if not ctypes.windll.shell32.IsUserAnAdmin():
            errors.append("Admin Rights Needed")
        
        # Check Ports
        for port in [67, 69, 80, 4011]:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM if port in [67, 69, 4011] else socket.SOCK_STREAM) as s:
                try:
                    s.bind(('', port))
                except:
                    errors.append(f"Port {port} busy")
        
        if errors:
            self.readiness_label.configure(text=f"⚠️ CRITICAL: {', '.join(errors)}", text_color="#e74c3c")
            return False
        else:
            self.readiness_label.configure(text="✅ ALL SYSTEMS READY FOR IGNITION", text_color="#2ecc71")
            return True

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

        try:
            # Servers
            self.servers["dhcp"] = DHCPD(config)
            self.servers["tftp"] = TFTPD(config)
            self.servers["http"] = HTTPD(config)

            threading.Thread(target=self.servers["dhcp"].listen, daemon=True).start()
            threading.Thread(target=self.servers["tftp"].listen, daemon=True).start()
            threading.Thread(target=self.servers["http"].listen, daemon=True).start()
            
            logging.info("PXEGEMINI Engine Started Successfully.")
            logging.info(f"Target: UEFI/Legacy | Mode: {'Proxy' if config['mode_proxy'] else 'Standard'}")
            logging.info("UEFI Priority: snponly.efi (NATIVE DRIVERS) activated.")
        except Exception as e:
            logging.error(f"Failed to start engine: {e}")
            self.stop_engine()

    def stop_engine(self):
        self.running = False
        logging.info("Stopping servers...")
        
        # Proper socket closure to release ports
        for name, server in self.servers.items():
            if server and hasattr(server, 'sock'):
                try:
                    server.sock.close()
                except:
                    pass
        
        self.status_led.configure(text_color="gray")
        self.status_text.configure(text="OFFLINE")
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        logging.warning("Servers stopped. Ports released.")

    def run_network_fix(self):
        logging.info("Running Firewall & Network Fixer...")
        
        # Determine path for bundled files in PyInstaller
        import sys
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
            
        # Paths to check for FIX_PXE.bat
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
                logging.info(f"Fixer script launched from {bat_path}")
            except Exception as e:
                logging.error(f"Failed to launch fixer: {e}")
        else:
            logging.error(f"FIX_PXE.bat not found in any standard location.")

    def run_strelec_config(self):
        iso = self.iso_manager.find_strelec_iso()
        if iso:
            threading.Thread(target=self.iso_manager.extract_strelec, args=(iso,), daemon=True).start()
            self.iso_manager.generate_menu()
        else:
            logging.error("STRELEC.ISO not found in E:\ Drive.")

    def save_settings(self):
        self.config["server_ip"] = self.entry_ip.get()
        self.config["mode_proxy"] = self.proxy_var.get()
        save_config(self.config)
        logging.info("Configuration saved. Restart required for some changes.")

if __name__ == "__main__":
    app = PXEGEMINIApp()
    app.mainloop()
