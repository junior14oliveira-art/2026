import os
import ctypes
import subprocess

def create_shortcut():
    import winshell
    from win32com.client import Dispatch

    desktop = os.path.join(os.environ["USERPROFILE"], "Desktop")
    path = os.path.join(desktop, "PXE_GEMINI_V2.lnk")
    target = r"E:\PXEGEMINI\dist\PXE_GEM_V2\PXE_GEM_V2.exe"
    wDir = r"E:\PXEGEMINI\dist\PXE_GEM_V2"
    icon = r"E:\PXEGEMINI\dist\PXE_GEM_V2\PXE_GEM_V2.exe"

    shell = Dispatch('WScript.Shell')
    shortcut = shell.CreateShortCut(path)
    shortcut.Targetpath = target
    shortcut.WorkingDirectory = wDir
    shortcut.IconLocation = icon
    shortcut.save()

    print(f"Atalho criado em: {path}")

def launch_app():
    target = r"E:\PXEGEMINI\dist\PXE_GEM_V2\PXE_GEM_V2.exe"
    print(f"Lançando {target} como Administrador...")
    subprocess.run(["powershell", "-Command", f"Start-Process '{target}' -Verb RunAs"])

if __name__ == "__main__":
    try:
        # Trying to use powershell for shortcut if winshell/pywin32 not available
        ps_cmd = """
        $WshShell = New-Object -comObject WScript.Shell;
        $DesktopPath = [Environment]::GetFolderPath('Desktop');
        $Shortcut = $WshShell.CreateShortcut(\"$DesktopPath\\PXE_GEMINI_V2.lnk\");
        $Shortcut.TargetPath = \"E:\\PXEGEMINI\\dist\\PXE_GEM_V2\\PXE_GEM_V2.exe\";
        $Shortcut.WorkingDirectory = \"E:\\PXEGEMINI\\dist\\PXE_GEM_V2\";
        $Shortcut.Description = \"PXEGEMINI v2.1 Antigravity Edition\";
        $Shortcut.Save();
        """
        subprocess.run(["powershell", "-Command", ps_cmd], check=True)
        print("Atalho PXE_GEMINI_V2 criado com sucesso via PowerShell.")
        launch_app()
    except Exception as e:
        print(f"Erro: {e}")

