import os
import sys
import subprocess
import customtkinter
import shutil

def main():
    print("Starting PXEGEMINI Build Process...")
    
    # 1. Kill old process
    try:
        subprocess.run(["taskkill", "/F", "/IM", "PXE_GEMINI.exe", "/T"], capture_output=True)
    except:
        pass
    
    # 2. Get paths
    ctk_path = os.path.dirname(customtkinter.__file__)
    print(f"CustomTkinter located at: {ctk_path}")
    
    # 3. Build command
    # On Windows, PyInstaller --add-data uses ';'
    # We want to copy the whole customtkinter folder into the distribution
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--add-data", f"servers;servers",
        "--add-data", f"boot;boot",
        "--add-data", f"FIX_PXE.bat;.",
        "--add-data", f"{ctk_path};customtkinter",
        "--name", "PXE_GEM_V2", # Changing name slightly to avoid lock issues
        "main.py"
    ]
    
    print(f"Executing: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    
    print("\nBuild Successful!")
    print(f"Executable is located at: {os.path.join(os.getcwd(), 'dist', 'PXE_GEM_V2', 'PXE_GEM_V2.exe')}")

if __name__ == "__main__":
    main()
