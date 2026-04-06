import ctypes
import sys
import os

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

if __name__ == "__main__":
    try:
        if not is_admin():
            # Re-run the program with admin rights
            ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
        else:
            # Load and run the app
            from app_ui import PXEGEMINIApp
            app = PXEGEMINIApp()
            app.mainloop()
    except Exception as e:
        import traceback
        desktop = os.path.join(os.environ["USERPROFILE"], "Desktop")
        log_file = os.path.join(desktop, "PXE_GEMINI_CRASH.txt")
        with open(log_file, "w", encoding="utf-8") as f:
            f.write("--- PXEGEMINI FATAL ERROR REPORT ---\n")
            f.write(f"Error: {str(e)}\n\n")
            f.write(traceback.format_exc())
        
        # Simple message box to notify user
        ctypes.windll.user32.MessageBoxW(0, f"O programa travou ao iniciar.\nRelatório gerado no Desktop: PXE_GEMINI_CRASH.txt\n\nErro: {str(e)}", "Erro Fatal - PXEGEMINI", 0x10)
