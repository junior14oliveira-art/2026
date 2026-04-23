import ctypes
import os
import sys


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


if __name__ == "__main__":
    try:
        if not is_admin():
            ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                sys.executable,
                " ".join(sys.argv),
                None,
                1,
            )
        else:
            from app_ui import PXEGEMINIApp

            app = PXEGEMINIApp()
            app.mainloop()
    except Exception as e:
        import traceback

        desktop = os.path.join(os.environ["USERPROFILE"], "Desktop")
        log_file = os.path.join(desktop, "PXE_GEMINI_HTTPDISK_CRASH.txt")
        with open(log_file, "w", encoding="utf-8") as f:
            f.write("--- PXEGEMINI HTTPDisk FATAL ERROR REPORT ---\n")
            f.write(f"Error: {str(e)}\n\n")
            f.write(traceback.format_exc())

        ctypes.windll.user32.MessageBoxW(
            0,
            f"O programa travou ao iniciar.\nRelatorio gerado no Desktop: PXE_GEMINI_HTTPDISK_CRASH.txt\n\nErro: {str(e)}",
            "Erro Fatal - PXEGEMINI HTTPDisk v5.7",
            0x10,
        )
        sys.exit(1)
