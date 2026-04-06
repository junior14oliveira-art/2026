$isoPath = Get-ChildItem -Path D:,E:,F:,G: -Filter "*strelec*.iso" -Recurse -ErrorAction SilentlyContinue | Sort-Object Length -Descending | Select-Object -First 1 | Select-Object -ExpandProperty FullName
if (-not $isoPath) { exit 1 }

$mount = Mount-DiskImage -ImagePath $isoPath -PassThru
$drive = ($mount | Get-Volume).DriveLetter + ":"
$target = "E:\PXEGEMINI\data\extracted\strelec"

# Copia tudo garantindo a estrutura
robocopy $drive $target /E /Z /R:3 /W:1 /MT:8 /XF boot.wim boot.sdi bootmgr bootx64.efi BCD /XD Fonts

Dismount-DiskImage -ImagePath $isoPath
