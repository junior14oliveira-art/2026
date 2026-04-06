$OriginalBCD = "E:\PXEGEMINI\data\extracted\strelec\BCD"
$ModBCD = "E:\PXEGEMINI\data\extracted\strelec\mod_BCD"

if (Test-Path $ModBCD) { Remove-Item $ModBCD -Force }
Copy-Item $OriginalBCD $ModBCD

# Procurar os GUIDs relevantes
Write-Host "Realizando Patch Manual no BCD do Strelec..."

# Encontrar Device ID(s) de Ramdisk
$ramdisks = bcdedit /store $ModBCD /enum device | Select-String "identifier" | ForEach-Object { ($_.Line -split " +")[1] }
foreach ($r in $ramdisks) {
    bcdedit /store $ModBCD /set $r ramdisksdipath "\boot.sdi" > $null
    Write-Host "Patched Ramdisk $r to \boot.sdi"
}

# Encontrar entradas OSLoader (que apontam para os WIMs)
$osloaders = bcdedit /store $ModBCD /enum osloader | Select-String "identifier" | ForEach-Object { ($_.Line -split " +")[1] }
foreach ($o in $osloaders) {
    # Pegar o ramdisk guid atual
    $osdevice = (bcdedit /store $ModBCD /enum $o | Select-String "osdevice").Line
    if ($osdevice -match "ramdisk=\[boot\].*,({.*})") {
        $rguid = $matches[1]
        bcdedit /store $ModBCD /set $o osdevice "ramdisk=[boot]\boot.wim,$rguid" > $null
        bcdedit /store $ModBCD /set $o device "ramdisk=[boot]\boot.wim,$rguid" > $null
        Write-Host "Patched OSLoader $o to \boot.wim com ramdisk $rguid"
    }
}

Write-Host "Patch concluido com sucesso em $ModBCD"
