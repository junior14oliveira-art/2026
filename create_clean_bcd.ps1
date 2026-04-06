$BcdPath = "E:\PXEGEMINI\data\extracted\strelec\clean_BCD"
if (Test-Path $BcdPath) { Remove-Item $BcdPath -Force }

Write-Host "Criando BCD limpo em $BcdPath"
bcdedit /createstore $BcdPath

# Ramdisk options (Device ID e Path)
$RamdiskGuid = "{7619dcc8-fafe-11d9-b411-000476eba25f}"
bcdedit /store $BcdPath /create $RamdiskGuid /d "Ramdisk Options" /device
bcdedit /store $BcdPath /set $RamdiskGuid ramdisksdidevice boot
bcdedit /store $BcdPath /set $RamdiskGuid ramdisksdipath "\boot.sdi"

# Criar a entrada do sistema (OS Loader para WinPE)
$out = bcdedit /store $BcdPath /create /d "PXEGEMINI - Windows PE" /application osloader
$OsLoaderGuid = [regex]::match($out, '\{[a-fA-F0-9-]+\}').Value
Write-Host "OS Loader GUID: $OsLoaderGuid"

bcdedit /store $BcdPath /set $OsLoaderGuid device "ramdisk=[boot]\boot.wim,$RamdiskGuid"
bcdedit /store $BcdPath /set $OsLoaderGuid path "\windows\system32\boot\winload.efi"
bcdedit /store $BcdPath /set $OsLoaderGuid osdevice "ramdisk=[boot]\boot.wim,$RamdiskGuid"
bcdedit /store $BcdPath /set $OsLoaderGuid systemroot "\windows"
bcdedit /store $BcdPath /set $OsLoaderGuid winpe yes
bcdedit /store $BcdPath /set $OsLoaderGuid detecthal yes
bcdedit /store $BcdPath /set $OsLoaderGuid nx optin
# Desabilitar display de graficos elaborados para maximizar a compatibilidade UEFI
bcdedit /store $BcdPath /set $OsLoaderGuid graphicsresolution 1024x768

# Criar Boot Manager e linkar para o OS Loader
bcdedit /store $BcdPath /create "{bootmgr}" /d "Windows Boot Manager"
bcdedit /store $BcdPath /set "{bootmgr}" timeout 30
bcdedit /store $BcdPath /set "{bootmgr}" displayorder $OsLoaderGuid
bcdedit /store $BcdPath /set "{bootmgr}" default $OsLoaderGuid

Write-Host "BCD Limpo gerado com sucesso!"
