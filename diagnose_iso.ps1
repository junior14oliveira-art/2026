# Listar TODOS os arquivos .wim na ISO do Strelec para diagnóstico
$out = "E:\PXEGEMINI\iso_diag.txt"
$log = @()

$log += "=== Procurando ISO do Strelec ==="
$drives = Get-PSDrive -PSProvider FileSystem | Select-Object -ExpandProperty Root
$iso = $null
foreach ($d in $drives) {
    $found = Get-ChildItem -Path $d -Filter "*strelec*.iso" -ErrorAction SilentlyContinue | Sort-Object Length -Descending | Select-Object -First 1
    if ($found) { $iso = $found; break }
}

if (-not $iso) { $log += "ISO NAO ENCONTRADA"; $log | Out-File $out; exit 1 }
$log += "ISO: $($iso.FullName) - $([math]::Round($iso.Length/1GB,2)) GB"

$log += "`n=== Montando ==="
$mount = Mount-DiskImage -ImagePath $iso.FullName -PassThru
$drive = ($mount | Get-Volume).DriveLetter + ":"
$log += "Drive: $drive"

$log += "`n=== WIM Files (sorted by size) ==="
$wims = Get-ChildItem -Path $drive -Filter "*.wim" -Recurse -ErrorAction SilentlyContinue | Sort-Object Length -Descending
foreach ($w in $wims) {
    $log += "$($w.FullName) = $([math]::Round($w.Length/1MB,0)) MB"
}

$log += "`n=== Root directories ==="
Get-ChildItem -Path $drive | ForEach-Object {
    $log += "$($_.Name)  $(if($_.PSIsContainer){'[DIR]'}else{[math]::Round($_.Length/1MB,1)+' MB'})"
}

$log += "`n=== SSTR folder ==="
if (Test-Path "$drive\SSTR") {
    Get-ChildItem "$drive\SSTR" | ForEach-Object {
        $log += "$($_.Name) = $(if($_.PSIsContainer){'[DIR]'}else{[math]::Round($_.Length/1MB,1)+' MB'})"
    }
}

$log += "`n=== BCD osdevice/path fields ==="
$bcdPaths = @("$drive\SSTR\BCD", "$drive\boot\BCD")
foreach ($bcdFile in $bcdPaths) {
    if (Test-Path $bcdFile) {
        $log += "-- BCD: $bcdFile --"
        $result = bcdedit /store $bcdFile /enum all 2>&1
        $result | Where-Object { $_ -match "osdevice|device|path|wim|sdi|description" } | ForEach-Object { $log += "  $_" }
    }
}

$log += "`n=== Dismounting ==="
Dismount-DiskImage -ImagePath $iso.FullName -ErrorAction SilentlyContinue
$log += "Done."

$log | Out-File $out -Encoding UTF8
Write-Host "Diagnostic saved to $out"
