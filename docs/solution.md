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

**Status:** Implementation planned.

## Files Modified
- `boot.wim` - Added custom startnet.cmd for SMB mapping
- `boot/menu.ipxe` - Updated initrd entries for SSTR overlay
- `data/extracted/strelec/startnet.cmd` - Network discovery script
- `app_ui.py` - SMB share creation/deletion automation

## Next Steps
1. Finalize httpdisk integration (preferred)
2. Or fix SMB authentication completely
3. Test on Dell Latitude 5420
