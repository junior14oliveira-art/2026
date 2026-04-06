import os
import subprocess

def main():
    target = r"E:\PXEGEMINI\dist\PXE_GEM_V3\PXE_GEM_V3.exe"
    w_dir = r"E:\PXEGEMINI\dist\PXE_GEM_V3"
    
    ps_cmd = f"""
    $WshShell = New-Object -comObject WScript.Shell;
    $DesktopPath = [Environment]::GetFolderPath('Desktop');
    $Shortcut = $WshShell.CreateShortcut(\"$DesktopPath\\PXE_GEMINI_V3.lnk\");
    $Shortcut.TargetPath = \"{target}\";
    $Shortcut.WorkingDirectory = \"{w_dir}\";
    $Shortcut.Description = \"PXEGEMINI v3.0 Final Edition\";
    $Shortcut.Save();
    """
    
    print("Criando atalho V3 no Desktop...")
    subprocess.run(["powershell", "-Command", ps_cmd], check=True)
    
    print("Iniciando PXE_GEM_V3 como Administrador...")
    subprocess.run(["powershell", "-Command", f"Start-Process '{target}' -Verb RunAs"], check=True)

if __name__ == "__main__":
    main()
