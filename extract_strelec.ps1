# PXEGEMINI - Sergei Strelec Manual Extraction Script
$ErrorActionPreference = "SilentlyContinue"

Write-Host "--- Iniciando Busca Global da ISO Sergei Strelec ---"

# Scan all potential drives for the ISO
$drives = Get-PSDrive -PSProvider FileSystem | Select-Object -ExpandProperty Root
$iso = $null
foreach ($d in $drives) {
    $found = Get-ChildItem -Path $d -Filter "*strelec*.iso" -ErrorAction SilentlyContinue | Sort-Object Length -Descending | Select-Object -First 1
    if ($found) {
        $iso = $found
        break
    }
}

if (-not $iso) {
    Write-Error "ISO do Sergei Strelec não encontrada nos discos D:, E:, F:, G:, etc."
    exit 1
}

Write-Host "ISO Encontrada: $($iso.FullName) ($([math]::Round($iso.Length / 1GB, 2)) GB)"

# Mount the ISO
Write-Host "Montando imagem..."
$mount = Mount-DiskImage -ImagePath $iso.FullName -PassThru
$driveLetter = ($mount | Get-Volume).DriveLetter
if (-not $driveLetter) {
    # Fallback if Get-Volume fails
    $driveLetter = (Get-DiskImage -ImagePath $iso.FullName | Get-Volume).DriveLetter
}
$drive = $driveLetter + ":"

Write-Host "Montado na unidade: $drive"

# Prepare Target
$target = "E:\PXEGEMINI\data\strelec"
if (-not (Test-Path $target)) {
    New-Item -ItemType Directory -Path $target -Force
}

# 1. Main WIM Image (The biggest one is the system)
Write-Host "Localizando imagem WIM do sistema..."
$wim = Get-ChildItem -Path $drive -Filter "*.wim" -Recurse | Sort-Object Length -Descending | Select-Object -First 1
if ($wim) {
    Write-Host "Extraindo $($wim.Name)..."
    Copy-Item -Path $wim.FullName -Destination "$target\boot.wim" -Force
}

# 2. Boot SDI and BCD
Write-Host "Extraindo BCD e boot.sdi..."
$sdi = Get-ChildItem -Path $drive -Filter "boot.sdi" -Recurse | Select-Object -First 1
if ($sdi) { Copy-Item -Path $sdi.FullName -Destination "$target\boot.sdi" -Force }

$bcd = Get-ChildItem -Path $drive -Filter "BCD" -Recurse | Select-Object -First 1
if ($bcd) { Copy-Item -Path $bcd.FullName -Destination "$target\BCD" -Force }

# 3. Fonts for UEFI Stability
Write-Host "Extraindo fontes de boot..."
$fontTarget = "$target\Fonts"
New-Item -ItemType Directory -Path $fontTarget -Force
$fontFolder = Get-ChildItem -Path $drive -Directory -Filter "Fonts" -Recurse | Select-Object -First 1
if ($fontFolder) {
    Copy-Item -Path "$($fontFolder.FullName)\*" -Destination $fontTarget -Force
}

# 4. Boot managers
Write-Host "Extraindo gerenciadores de boot..."
if (Test-Path "$drive\bootmgr") { Copy-Item -Path "$drive\bootmgr" -Destination "$target\bootmgr" -Force }
$bootx64 = Get-ChildItem -Path $drive -Filter "bootx64.efi" -Recurse | Select-Object -First 1
if ($bootx64) { Copy-Item -Path $bootx64.FullName -Destination "$target\bootx64.efi" -Force }

# Dismount
Write-Host "Desmontando imagem..."
Dismount-DiskImage -ImagePath $iso.FullName

Write-Host "--- EXTRAÇÃO CONCLUÍDA COM SUCESSO EM $target ---"
