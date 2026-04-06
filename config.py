import os
import json

DEFAULT_CONFIG = {
    "server_ip": "192.168.0.21",
    "http_port": 80,
    "tftp_port": 69,
    "dhcp_port": 67,
    "iso_dir": r"E:\\",
    "extract_dir": r"E:\PXEGEMINI\data\extracted",
    "boot_dir": r"E:\PXEGEMINI\boot",
    "mode_proxy": True,
    "pool_begin": "192.168.0.200",
    "pool_end": "192.168.0.250",
    "subnet_mask": "255.255.255.0",
    "gateway": "192.168.0.1",
    "dns_server": "8.8.8.8"
}

CONFIG_FILE = r"E:\PXEGEMINI\config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return DEFAULT_CONFIG

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)
