@echo off
echo ========================================================
echo PXEGEMINI Antigravity - Firewall and Network Fixer
echo ========================================================
echo.
echo Stopping services that might conflict...
net stop ipexsvc >nul 2>&1
net stop tftpd32 >nul 2>&1

echo Clearing firewall rules for PXEGEMINI...
netsh advfirewall firewall delete rule name="PXE GEMINI Server HTTP" >nul 2>&1
netsh advfirewall firewall delete rule name="PXE GEMINI Server TFTP" >nul 2>&1
netsh advfirewall firewall delete rule name="PXE GEMINI Server DHCP" >nul 2>&1

echo Adding new Firewall bypass rules for PXEGEMINI...
netsh advfirewall firewall add rule name="PXE GEMINI Server HTTP" dir=in action=allow protocol=TCP localport=80 profile=any
netsh advfirewall firewall add rule name="PXE GEMINI Server TFTP" dir=in action=allow protocol=UDP localport=69 profile=any
netsh advfirewall firewall add rule name="PXE GEMINI Server DHCP" dir=in action=allow protocol=UDP localport=67 profile=any
netsh advfirewall firewall add rule name="PXE GEMINI Server ProxyDHCP" dir=in action=allow protocol=UDP localport=4011 profile=any

echo.
echo ========================================================
echo FIX SUCCESSFUL! Ports 67, 69, 80, and 4011 are open.
echo You can now press "START ENGINE" in the application.
echo ========================================================
pause
