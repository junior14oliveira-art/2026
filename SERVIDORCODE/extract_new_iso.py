import os, subprocess, shutil

iso_src = r'E:\PXEGEMINI\Win11e10 19045.5608.250305-0902.22H2_RELEASE_SVC_PROD1_CLIENTMULTI_X64FRE_PT-BR.iso'
base = r'E:\PXEGEMINI\SERVIDORCODE'
iso_dst = os.path.join(base, 'data', 'isos', 'win11.iso')
ext_dir = os.path.join(base, 'data', 'extracted', 'win11')

os.makedirs(os.path.dirname(iso_dst), exist_ok=True)
os.makedirs(ext_dir, exist_ok=True)

if not os.path.exists(iso_dst):
    try: os.link(iso_src, iso_dst)
    except: shutil.copy2(iso_src, iso_dst)

ps_mount = f'Mount-DiskImage -ImagePath "{iso_src}" -PassThru | Get-Volume | Select-Object -ExpandProperty DriveLetter'
try:
    drive = subprocess.check_output(['powershell', '-Command', ps_mount]).decode().strip()
    if drive:
        print(f'Montado em {drive}:')
        src = f'{drive}:/'
        for root, dirs, files in os.walk(src):
            for f in ['bootmgr', 'boot.sdi', 'BCD', 'bootx64.efi', 'boot.wim']:
                if f in files and not os.path.exists(os.path.join(ext_dir, f)):
                    shutil.copy2(os.path.join(root, f), os.path.join(ext_dir, f))
                    print(f'Extraido: {f}')
        subprocess.run(['powershell', '-Command', f'Dismount-DiskImage -ImagePath "{iso_src}"'])
    else:
        print('Nao consegui a letra do drive.')
except Exception as e:
    print(f'Erro: {e}')
