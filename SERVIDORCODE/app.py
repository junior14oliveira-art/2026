import json
import os
import threading
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
        self.title("FAST HTTPDisk PXE Engine v2.0")
        self.geometry("1100x650")

        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.config_path = os.path.join(self.base_dir, 'config.json')
        
        with open(self.config_path) as f:
            self.config = json.load(f)

        self.engine = HookEngine(self.base_dir, self.config)
        self.services = []
        self.running = False
        
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_main_area()
        self.update_log("Sistema Pronto. Focado em UX e Heurísticas de Nielsen.")
        self.refresh_iso_list()

    def _build_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=250, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        
        ctk.CTkLabel(self.sidebar, text="PXE FAST", font=("Arial", 28, "bold")).pack(pady=30)
        
        # Status Box
        self.status_box = ctk.CTkFrame(self.sidebar, fg_color="#333333", height=100)
        self.status_box.pack(padx=20, fill="x", pady=10)
        
        self.status_lbl = ctk.CTkLabel(self.status_box, text="OFFLINE", font=("Arial", 20, "bold"), text_color="gray")
        self.status_lbl.pack(pady=10)
        
        self.start_btn = ctk.CTkButton(self.sidebar, text="INICIAR SERVIDOR", fg_color="#28a745", hover_color="#218838", command=self.start_server)
        self.start_btn.pack(padx=20, fill="x", pady=10)
        
        self.stop_btn = ctk.CTkButton(self.sidebar, text="PARAR SERVIDOR", fg_color="#dc3545", hover_color="#c82333", state="disabled", command=self.stop_server)
        self.stop_btn.pack(padx=20, fill="x", pady=10)

        self.refresh_btn = ctk.CTkButton(self.sidebar, text="RECARREGAR LISTA", fg_color="#17a2b8", hover_color="#138496", command=self.refresh_iso_list)
        self.refresh_btn.pack(padx=20, fill="x", pady=10, side="bottom")
        
        # Info
        info_txt = f"IP: {self.config.get('server_ip')}\nHTTP: {self.config.get('http_port')}\nTFTP: {self.config.get('tftp_port')}"
        ctk.CTkLabel(self.sidebar, text=info_txt, font=("Arial", 12), justify="left").pack(side="bottom", pady=20)

    def _build_main_area(self):
        self.main_area = ctk.CTkFrame(self, fg_color="transparent")
        self.main_area.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        self.main_area.grid_rowconfigure(0, weight=1)
        self.main_area.grid_columnconfigure(0, weight=1)
        
        # Upper: ISO List
        self.iso_frame = ctk.CTkScrollableFrame(self.main_area, label_text="Gerenciador de ISOs (data/isos)")
        self.iso_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
        
        # Lower: Log
        self.log_txt = ctk.CTkTextbox(self.main_area, height=180, font=("Consolas", 12))
        self.log_txt.grid(row=1, column=0, sticky="nsew")

    def refresh_iso_list(self):
        for child in self.iso_frame.winfo_children():
            child.destroy()
            
        iso_dir = self.engine.isos_dir
        for f in os.listdir(iso_dir):
            if f.lower().endswith('.iso'):
                self._add_iso_row(f)

    def _add_iso_row(self, iso_name):
        row = ctk.CTkFrame(self.iso_frame)
        row.pack(fill="x", pady=5, padx=5)
        
        key = os.path.splitext(iso_name)[0].lower().replace(" ", "")
        extracted_path = os.path.join(self.engine.extracted_dir, key)
        ready = os.path.isdir(extracted_path) and os.path.isfile(os.path.join(extracted_path, "boot.wim"))
        
        status_color = "#28a745" if ready else "#ffc107"
        status_text = "PRONTO" if ready else "PENDENTE"
        
        ctk.CTkLabel(row, text=iso_name, font=("Arial", 14), width=400, anchor="w").pack(side="left", padx=10)
        ctk.CTkLabel(row, text=status_text, text_color=status_color, font=("Arial", 12, "bold"), width=100).pack(side="left", padx=10)
        
        btn_text = "RE-SINCRONIZAR" if ready else "PREPARAR"
        btn = ctk.CTkButton(row, text=btn_text, width=120, command=lambda: self.prepare_iso_task(iso_name))
        btn.pack(side="right", padx=10)

    def prepare_iso_task(self, iso_name):
        self.update_log(f"Iniciando preparacao da ISO: {iso_name}...")
        def run():
            success = self.engine.prepare_iso(iso_name)
            if success:
                self.update_log(f"SUCESSO: ISO {iso_name} preparada para boot.")
            else:
                self.update_log(f"ERRO: Falha ao extrair ISO {iso_name}.")
            self.after(0, self.refresh_iso_list)
        threading.Thread(target=run, daemon=True).start()

    def update_log(self, text):
        self.log_txt.insert("end", f"> {text}\n")
        self.log_txt.see("end")

    class LoggerProxy:
        def __init__(self, ui): self.ui = ui
        def info(self, msg, *args): self.ui.after(0, lambda: self.ui.update_log("[INFO] " + (msg % args if args else msg)))
        def warning(self, msg, *args): self.ui.after(0, lambda: self.ui.update_log("[WARN] " + (msg % args if args else msg)))
        def error(self, msg, *args): self.ui.after(0, lambda: self.ui.update_log("[ERRO] " + (msg % args if args else msg)))

    def start_server(self):
        self.engine.rebuild_menu()
        logger = self.LoggerProxy(self)
        self.services = [DHCPD(self.config, logger), TFTPD(self.config, logger), HTTPD(self.config, logger)]
        
        def runner(srv):
            try: srv.listen()
            except Exception as e: self.update_log(f"Erro: {e}")

        for srv in self.services:
            threading.Thread(target=runner, args=(srv,), daemon=True).start()

        self.running = True
        self.status_lbl.configure(text="ONLINE", text_color="#28a745")
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.update_log("Motor PXE Ativo. Logs de rede habilitados.")

    def stop_server(self):
        for srv in self.services: srv.stop()
        self.services = []
        self.running = False
        self.status_lbl.configure(text="OFFLINE", text_color="gray")
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.update_log("Motor desligado.")

if __name__ == "__main__":
    app = FastPXEApp()
    app.mainloop()
