Set-Location "E:\PXEGEMINI"

Write-Host "Installing PyInstaller..."
pip install pyinstaller

Write-Host "Locating CustomTkinter assets..."
$ctk_path = python -c "import customtkinter, os; print(os.path.dirname(customtkinter.__file__))"
Write-Host "CTK Path: $ctk_path"

Write-Host "Building PXEGEMINI via PyInstaller..."
python -m PyInstaller --noconfirm --onedir --windowed --add-data "servers;servers" --add-data "boot;boot" --add-data "FIX_PXE.bat;." --add-data "$($ctk_path);customtkinter" --name "PXE_GEMINI" main.py

Write-Host "Creating Desktop Shortcut..."
$WshShell = New-Object -comObject WScript.Shell
$DesktopPath = [Environment]::GetFolderPath('Desktop')
$Shortcut = $WshShell.CreateShortcut("$DesktopPath\PXE_GEMINI.lnk")
$Shortcut.TargetPath = "E:\PXEGEMINI\dist\PXE_GEMINI\PXE_GEMINI.exe"
$Shortcut.WorkingDirectory = "E:\PXEGEMINI\dist\PXE_GEMINI"
$Shortcut.Description = "Start Antigravity PXE Server"
$Shortcut.Save()

Write-Host "Build complete! Shortcut is on the Desktop."
