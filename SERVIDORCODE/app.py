import json
import os
import threading
import sys
import customtkinter as ctk

from core.dhcp import DHCPD
from core.tftp import TFTPD
from core.http import HTTPD
from core.engine import HookEngine

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class FastPXEApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("FAST HTTPDisk PXE Engine")
        self.geometry("800x500")

        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.config_path = os.path.join(self.base_dir, 'config.json')
        
        with open(self.config_path) as f:
            self.config = json.load(f)

        self.engine = HookEngine(self.base_dir, self.config)
        self.services = []
        self.running = False

        self._build_ui()
        self.update_log("Sistema Pronto. Focado puramente em injeção HTTPDisk nativa.")

    def _build_ui(self):
        # Header
        header = ctk.CTkFrame(self, height=60, corner_radius=0)
        header.pack(fill="x")
        ctk.CTkLabel(header, text="FAST HTTPDisk PXE", font=("Arial", 24, "bold")).pack(pady=15)

        # Main
        main_fr = ctk.CTkFrame(self)
        main_fr.pack(fill="both", expand=True, padx=20, pady=20)

        # Status
        self.status_lbl = ctk.CTkLabel(main_fr, text="OFFLINE", font=("Arial", 18, "bold"), text_color="gray")
        self.status_lbl.pack(pady=10)

        # Buttons
        btn_fr = ctk.CTkFrame(main_fr, fg_color="transparent")
        btn_fr.pack(pady=10)
        
        self.start_btn = ctk.CTkButton(btn_fr, text="▶ INICIAR SERVIDOR", fg_color="green", hover_color="darkgreen", command=self.start_server)
        self.start_btn.pack(side="left", padx=10)

        self.stop_btn = ctk.CTkButton(btn_fr, text="⏹ PARAR", fg_color="red", hover_color="darkred", state="disabled", command=self.stop_server)
        self.stop_btn.pack(side="left", padx=10)

        # Log
        self.log_txt = ctk.CTkTextbox(main_fr, height=150)
        self.log_txt.pack(fill="both", expand=True, pady=10)

    def update_log(self, text):
        self.log_txt.insert("end", text + "\n")
        self.log_txt.see("end")

    class LoggerProxy:
        def __init__(self, ui): self.ui = ui
        def info(self, msg, *args): self.ui.update_log("[INFO] " + (msg % args if args else msg))
        def warning(self, msg, *args): self.ui.update_log("[WARN] " + (msg % args if args else msg))
        def error(self, msg, *args): self.ui.update_log("[ERRO] " + (msg % args if args else msg))

    def start_server(self):
        self.engine.rebuild_menu()
        self.update_log("Hooks e Menu iPXE recarregados.")

        logger = self.LoggerProxy(self)
        self.services = [
            DHCPD(self.config, logger),
            TFTPD(self.config, logger),
            HTTPD(self.config, logger)
        ]

        def runner(srv):
            try:
                srv.listen()
            except Exception as e:
                self.update_log(f"Erro no servico: {e}")

        for srv in self.services:
            # Tell HTTPD which folder is virtually active based on the menu logic. 
            # In FAST HTTP, we pass request via root directory, so we just set active_extract_dir for virtual linking.
            # We will default hook HTTP virtual links to the last extracted folder for simplicity in this MVP.
            if isinstance(srv, HTTPD):
                # Procura a primeira .iso disponivel e usa o target como active
                # Em um app full isso seria despachado dinamicamente via session
                for f in os.listdir(self.engine.isos_dir):
                    if f.endswith('.iso'):
                        srv.server.active_extract_dir = os.path.join(self.engine.extracted_dir, f.replace('.iso', '').lower())
                        break

            threading.Thread(target=runner, args=(srv,), daemon=True).start()

        self.running = True
        self.status_lbl.configure(text="ONLINE", text_color="green")
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.update_log("=> Servidor HTTPDisk operando.")

    def stop_server(self):
        for srv in self.services:
            srv.stop()
        self.services = []
        self.running = False
        self.status_lbl.configure(text="OFFLINE", text_color="gray")
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.update_log("=> Servidor Parado.")

if __name__ == "__main__":
    app = FastPXEApp()
    app.mainloop()
