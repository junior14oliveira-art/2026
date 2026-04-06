import urllib.request
urls = [
    "http://192.168.0.21/strelec/wimboot",
    "http://192.168.0.21/strelec/bootmgr",
    "http://192.168.0.21/strelec/bootx64.efi",
    "http://192.168.0.21/strelec/BCD",
    "http://192.168.0.21/strelec/boot.sdi",
    "http://192.168.0.21/strelec/boot.wim",
    "http://192.168.0.21/strelec/Fonts/segmono_boot.ttf",
    "http://192.168.0.21/strelec/Fonts/segoe_slboot.ttf",
    "http://192.168.0.21/strelec/Fonts/wgl4_boot.ttf",
    "http://192.168.0.21/strelec/Mapear_Programas.bat"
]

for url in urls:
    try:
        urllib.request.urlopen(url, timeout=2)
        print(f"OK: {url}")
    except Exception as e:
        print(f"FAIL: {url} -> {e}")
