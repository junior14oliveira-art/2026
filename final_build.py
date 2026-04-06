import os
import sys
import subprocess
import customtkinter

def build():
    print("Iniciando build do PXEGEMINI v2.1...")
    
    # Mover para o diretório do projeto
    os.chdir(r"E:\PXEGEMINI")
    
    # 1. Tentar matar processos antigos para liberar arquivos
    print("Limpando processos antigos...")
    try:
        subprocess.run(["taskkill", "/F", "/IM", "PXE_GEM_V2.exe", "/T"], capture_output=True)
        subprocess.run(["taskkill", "/F", "/IM", "PXE_GEMINI.exe", "/T"], capture_output=True)
    except:
        pass

    # 2. Localizar CustomTkinter de forma exata
    ctk_path = os.path.dirname(customtkinter.__file__)
    print(f"CustomTkinter detectado em: {ctk_path}")

    # 3. Comando do PyInstaller (Usando o formato de lista para evitar erros de espaço/aspas)
    # No Windows usamos ';' como separador para --add-data
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--add-data", "servers;servers",
        "--add-data", "boot;boot",
        "--add-data", "FIX_PXE.bat;.",
        "--add-data", f"{ctk_path};customtkinter",
        "--name", "PXE_GEM_V4",
        "main.py"
    ]

    print(f"Executando compilação...")
    result = subprocess.run(cmd)
    
    if result.returncode == 0:
        print("\n[SUCESSO] Build completa!")
        exe_path = os.path.join("dist", "PXE_GEM_V4", "PXE_GEM_V4.exe")
        print(f"Executável em: {os.path.abspath(exe_path)}")
    else:
        print(f"\n[ERRO] O PyInstaller falhou com código {result.returncode}")

if __name__ == "__main__":
    build()
