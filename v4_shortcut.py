import os
import subprocess

def main():
    target = r"E:\PXEGEMINI\dist\PXE_GEM_V4\PXE_GEM_V4.exe"
    w_dir = r"E:\PXEGEMINI\dist\PXE_GEM_V4"
    
    ps_cmd = f"""
    $WshShell = New-Object -comObject WScript.Shell;
    $DesktopPath = [Environment]::GetFolderPath('Desktop');
    $Shortcut = $WshShell.CreateShortcut(\"$DesktopPath\\PXE_GEMINI_V4.lnk\");
    $Shortcut.TargetPath = \"{target}\";
    $Shortcut.WorkingDirectory = \"{w_dir}\";
    $Shortcut.Description = \"PXEGEMINI v4.0 Final Edition\";
    $Shortcut.Save();
    """
    
    print("Criando atalho V4 no Desktop...")
    subprocess.run(["powershell", "-Command", ps_cmd], check=True)
    
    print("Mapeando temporariamente SMB Share caso o Windows feche...")
    subprocess.run(["powershell", "-Command", "New-SmbShare -Name 'STRELEC' -Path 'E:\\PXEGEMINI\\data\\extracted\\strelec' -ReadAccess 'Everyone' -ErrorAction SilentlyContinue"], check=False)
    
    print("Iniciando PXE_GEM_V4 como Administrador...")
    subprocess.run(["powershell", "-Command", f"Start-Process '{target}' -Verb RunAs"], check=True)

if __name__ == "__main__":
    main()
