$bcd = "E:\PXEGEMINI\data\extracted\strelec\BCD"
$out = "E:\PXEGEMINI\bcd_dump.txt"

# Full dump
$result = bcdedit /store "$bcd" /enum all 2>&1
$result | Out-File $out -Encoding UTF8

# Print just the critical lines
Write-Host "=== BCD CRITICAL FIELDS ==="
$result | Where-Object { $_ -match "device|path|ramdisk|osdevice|description|identifier|locale" } | ForEach-Object { Write-Host $_ }
