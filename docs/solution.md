# PXEGEMINI - Strelec WinPE Boot Fix Documentation

## Problem Summary
MInst.exe programs don't open when booting Strelec via iPXE wimboot on Dell Latitude 5420.
Error: `Windows cannot find '\SSTR\MInst\MInst.exe'`

Same ISO boots fine via iVentoy.

## Root Cause Analysis

### Why iVentoy Works
From PXE-master README.md (lines 17-27):
```
iVentoy uses `httpdisk.sys` driver to mount the ISO file as a local drive (e.g. Y:)
through HTTP. The entire ISO directory structure becomes accessible.
```

**Result:** All 7,400+ files in SSTR folder are available → MInst.exe runs normally.

### Why Our wimboot Fails
The iPXE wimboot configuration only loads:
- `boot.wim` → X: (RAM disk)
- Individual initrd files (bootmgr, BCD, fonts, etc.)

The `SSTR/` folder with MInst.exe is NOT loaded into RAM.
The original boot.wim doesn't contain `X:\SSTR\` directory.

**Result:** When MInst shortcuts launch, `X:\SSTR\MInst\MInst.exe` doesn't exist.

## Solutions Tried

### 1. SMB Share Mapping (Partial Success)
- Created SMB share `\\192.168.0.21\SSTR` on server start
- Modified startnet.cmd to map SMB before launching programs
- Custom startnet.cmd embedded in boot.wim via DISM

**Limitation:** SMB authentication issues in WinPE environment.

### 2. httpdisk.sys Approach (Preferred - Same as iVentoy)
- Download httpdisk source: https://www.accum.se/~bosse/httpdisk/httpdisk-10.2.zip
- Integrate httpdisk into WinPE
- Mount ISO via HTTP as virtual disk Y:
- Access SSTR programs via Y:\SSTR\

**Status:** IMPLEMENTED (2026-04-07). httpdisk.sys and httpdisk.exe added as initrd entries, startnet.cmd updated to mount ISO via httpdisk.exe first, with SMB fallback.

## Files Modified
- `boot.wim` (in `strelec_httpdisk/`) - Injected httpdisk.sys to drivers, httpdisk.exe to System32, updated startnet.cmd, added registry key `Services\HttpDisk`
- `data/extracted/geminiiso/` - Copied httpdisk.sys and httpdisk.exe for HTTP serving
- `iso_manager.py` - Added httpdisk initrd lines to `_menu_wimboot()`
- `boot/menu.ipxe` - Static menu updated with httpdisk entries
- `docs/solution.md` - This file

## What was done (2026-04-07)
1. Mounted boot.wim via DISM at `C:\wim_httpdisk`
2. Injected `httpdisk.sys` into `Windows\System32\drivers\`
3. Injected `httpdisk.exe` into `Windows\System32\`
4. Added registry key `HKLM\ControlSet001\Services\HttpDisk` (Start=0, Type=1, ImagePath=httpdisk.sys)
5. Replaced `startnet.cmd` with httpdisk-first approach:
   - Loads httpdisk.sys as driver
   - Mounts `http://192.168.0.21/geminiiso/strelec.iso` as drive Y:
   - Launches `Y:\SSTR\MInst\MInst.exe`
   - Falls back to SMB mapping if httpdisk fails
6. Committed WIM changes via DISM

## Remaining
- Test on Dell Latitude 5420
- Verify httpdisk.exe can mount the ISO (may need a proper .iso file served via HTTP)
