# PXEGEMINI AGENT INSTRUCTIONS

This document provides a comprehensive overview of the **PXEGEMINI HTTPDisk Edition** project to guide any AI agent working on this codebase.

## 🚀 Project Overview
**PXEGEMINI** is a high-performance Python-based PXE (Pre-boot Execution Environment) server. Its primary goal is to allow technicians to boot ISO images (especially **Sergei Strelec WinPE**) over a network without needing to burn USB drives.

### Key Technology: HTTPDisk
Unlike traditional PXE methods that load the entire ISO into RAM (which fails for large ISOs like Strelec), this project uses **HTTPDisk**.
- The server serves the `.iso` file over HTTP.
- The client (WinPE) uses a special driver (`httpdisk.sys`) to mount that URL as a virtual local drive (usually `Y:`).
- This allows booting 12GB+ ISOs on machines with limited RAM.

---

## 📂 Directory Structure

- `main.py`: The main entry point. Handles Administrator privilege elevation.
- `app_ui.py`: The primary GUI built with `customtkinter`. It manages the state and service lifecycle.
- `iso_manager.py`: Core logic for:
    - Scanning local drives/folders for ISOs.
    - Extracting `boot.wim`, `BCD`, and `boot.sdi` from ISOs.
    - Generating the dynamic `menu.ipxe`.
- `config.py` / `config.json`: Persistent settings (IP, paths, ports, profiles).
- `servers/`: Implementation of network services:
    - `dhcp.py`: Supports both Standard DHCP and **ProxyDHCP** (port 4011) to work alongside existing routers.
    - `tftp.py`: Delivers iPXE bootloaders (`undionly.kpxe`, `ipxe.efi`).
    - `http.py`: Serves the ISO files and boot components. **Supports Range Requests** (crucial for HTTPDisk).
- `boot/`: Contains `wimboot`, `httpdisk` binaries, and template iPXE scripts.
- `data/extracted/`: Temporary storage for extracted WIM files from ISOs.
- `SERVIDORCODE/`: A modular/older version of the engine components, often used for reference or specific standalone tasks.

---

## 🛠️ Important Patterns & Logic

### 1. ISO Preparation Workflow
When an ISO is added/scanned:
1. `iso_manager.py` mounts/opens the ISO.
2. It locates `sources\boot.wim`.
3. It extracts the WIM and necessary boot files to `data/extracted/<iso_key>/`.
4. It updates `menu.ipxe` with a new entry that points to these files.

### 2. The iPXE Menu (`menu.ipxe`)
The menu is generated dynamically. A typical entry for WinPE/HTTPDisk looks like this:
```bash
kernel http://${server_ip}/wimboot
initrd http://${server_ip}/data/extracted/${iso_key}/boot/bcd BCD
initrd http://${server_ip}/data/extracted/${iso_key}/boot/boot.sdi boot.sdi
initrd http://${server_ip}/data/extracted/${iso_key}/sources/boot.wim boot.wim
boot
```
*(Note: The actual mounting happens inside the WinPE via `startnet.cmd` scripts injected/configured to use `httpdisk.exe`)*.

### 3. Network Profiles
- **Isolated**: For direct connection between server and client (Server handles full DHCP).
- **Mixed**: For use in existing networks (Uses ProxyDHCP to avoid IP conflicts).

---

## ⚠️ Critical Files for Debugging
- `pxegemini.log`: General application logs.
- `http_results.txt`: Results of HTTP server tests.
- `config.json`: Check this if the server starts on the wrong IP or can't find ISOs.

---

## 💡 Tips for the Agent
- **Admin Rights**: Most networking and file extraction operations REQUIRE Administrator privileges.
- **Port Conflicts**: If services fail to start, check if ports 67 (DHCP), 69 (TFTP), or 80/8080 (HTTP) are occupied by other software (like iVentoy or a local IIS/Apache).
- **Range Requests**: If HTTPDisk fails to mount in WinPE, ensure `servers/http.py` is correctly handling `Range` headers.
- **Pathing**: Always use absolute paths or carefully handled relative paths based on `os.path.dirname(os.path.abspath(__file__))`.
