import os, subprocess, shutil

iso = r'E:\PXEGEMINI\SERVIDORCODE\data\isos\Win11_Oficial.iso'
dst = r'E:\PXEGEMINI\SERVIDORCODE\data\extracted\win11_oficial'
os.makedirs(dst, exist_ok=True)

print('Montando ISO para busca completa...')
try:
    subprocess.run(['powershell', '-Command', f'Mount-DiskImage -ImagePath "{iso}"'], check=True)
    out = subprocess.check_output(['powershell', '-Command', f'(Get-DiskImage -ImagePath "{iso}" | Get-Volume).DriveLetter']).decode().strip()
    if out:
        dr = out + ':\\'
        print(f'Drive {dr} detectado. Buscando arquivos...')
        
        # Mapeamento para garantir que tenhamos tudo que o iPXE pede
        targets = {
            'bootmgr': 'bootmgr',
            'boot.sdi': 'boot.sdi',
            'BCD': 'BCD',
            'boot.wim': 'boot.wim',
            'bootx64.efi': 'bootx64.efi',
            'bootmgfw.efi': 'bootmgfw.efi'
        }
        
        for root, dirs, files in os.walk(dr):
            for f in files:
                for key, val in targets.items():
                    if f.lower() == val.lower():
                        shutil.copy2(os.path.join(root, f), os.path.join(dst, key))
                        print(f'OK: {f} -> {key}')

        # Fallback para UEFI
        if os.path.exists(os.path.join(dst, 'bootmgfw.efi')) and not os.path.exists(os.path.join(dst, 'bootx64.efi')):
            shutil.copy2(os.path.join(dst, 'bootmgfw.efi'), os.path.join(dst, 'bootx64.efi'))
            print('Criado bootx64.efi (Copia de bootmgfw.efi)')

    subprocess.run(['powershell', '-Command', f'Dismount-DiskImage -ImagePath "{iso}"'], check=True)
    print('Finalizado!')
except Exception as e:
    print(f'Erro: {e}')
