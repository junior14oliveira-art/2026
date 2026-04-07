import json
import locale
import os
import re
import shutil
import socket
import struct
import subprocess
from typing import Dict, List, Optional


class PathTraversalException(Exception):
    pass


def normalize_path(base: str, filename: str) -> str:
    abs_path = os.path.abspath(base)
    joined = os.path.join(abs_path, filename)
    normalized = os.path.normpath(joined)
    if normalized.startswith(os.path.join(abs_path, '')) or normalized == abs_path:
        return normalized
    raise PathTraversalException('Path Traversal detected')


def normalize_mac(mac: str) -> str:
    hex_only = re.sub(r'[^0-9A-Fa-f]', '', mac or '').upper()
    if len(hex_only) != 12:
        return (mac or '').upper()
    return '-'.join(hex_only[i:i + 2] for i in range(0, 12, 2))


def ipv4_to_int(ip: str) -> int:
    return struct.unpack('!I', socket.inet_aton(ip))[0]


def int_to_ipv4(value: int) -> str:
    return socket.inet_ntoa(struct.pack('!I', value & 0xFFFFFFFF))


def prefix_to_mask(prefix: int) -> str:
    mask = 0
    for bit in range(prefix):
        mask |= 1 << (31 - bit)
    return int_to_ipv4(mask)


def mask_to_prefix(mask: str) -> int:
    value = ipv4_to_int(mask)
    return bin(value).count('1')


def compute_broadcast(ip: str, mask: str) -> str:
    ip_value = ipv4_to_int(ip)
    mask_value = ipv4_to_int(mask)
    return int_to_ipv4((ip_value & mask_value) | ((~mask_value) & 0xFFFFFFFF))


def suggest_dhcp_range(server_ip: str, subnet_mask: str) -> Dict[str, str]:
    server_value = ipv4_to_int(server_ip)
    mask_value = ipv4_to_int(subnet_mask)
    network = server_value & mask_value
    broadcast = (network | ((~mask_value) & 0xFFFFFFFF)) & 0xFFFFFFFF
    usable_start = network + 1
    usable_end = broadcast - 1
    preferred_start = network + 200
    preferred_end = preferred_start + 19
    if preferred_start < usable_start or preferred_end > usable_end:
        preferred_end = usable_end
        preferred_start = max(usable_start, usable_end - 19)
    reserved = min(preferred_start + 10, usable_end)
    if reserved == server_value:
        reserved = preferred_start
    return {
        'pool_begin': int_to_ipv4(preferred_start),
        'pool_end': int_to_ipv4(preferred_end),
        'broadcast': int_to_ipv4(broadcast),
        'reserved_ip': int_to_ipv4(reserved),
    }


def is_valid_ipv4(value: str) -> bool:
    if not value:
        return False
    try:
        socket.inet_aton(value)
        return True
    except OSError:
        return False


def list_network_adapters() -> List[Dict[str, str]]:
    adapters = _list_network_adapters_from_netipconfiguration()
    if adapters:
        return adapters
    return _list_network_adapters_from_ipconfig()


def _list_network_adapters_from_netipconfiguration() -> List[Dict[str, str]]:
    script = r"""
$items = Get-NetIPConfiguration | Where-Object { $_.NetAdapter.Status -eq 'Up' -and $_.IPv4Address } | ForEach-Object {
    [pscustomobject]@{
        Alias = $_.InterfaceAlias
        Description = $_.NetAdapter.InterfaceDescription
        IPv4Address = $_.IPv4Address.IPAddress
        PrefixLength = [int]$_.IPv4Address.PrefixLength
        SubnetMask = ([IPAddress](([uint32]0xFFFFFFFF) -shl (32 - [int]$_.IPv4Address.PrefixLength))).IPAddressToString
        Gateway = if ($_.IPv4DefaultGateway) { $_.IPv4DefaultGateway.NextHop | Select-Object -First 1 } else { '' }
        DnsServer = ($_.DnsServer.ServerAddresses | Where-Object { $_ -match '^\d{1,3}(\.\d{1,3}){3}$' } | Select-Object -First 1)
    }
}
$items | ConvertTo-Json -Depth 4
"""
    try:
        result = subprocess.run(
            ['powershell', '-NoProfile', '-Command', script],
            check=True,
            capture_output=True,
            text=True,
            encoding='utf-8',
        )
        raw = result.stdout.strip()
        if not raw:
            return []
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            parsed = [parsed]
        items: List[Dict[str, str]] = []
        for item in parsed:
            gateway = item.get('Gateway') or ''
            dns_server = item.get('DnsServer') or ''
            label = f"{item['Alias']} - {item['IPv4Address']}"
            label += f" - GW {gateway}" if gateway else ' - sem gateway'
            items.append({
                'label': label,
                'alias': item['Alias'],
                'description': item.get('Description', ''),
                'ip': item['IPv4Address'],
                'prefix_length': int(item['PrefixLength']),
                'subnet_mask': item['SubnetMask'],
                'gateway': gateway,
                'dns_server': dns_server,
            })
        items.sort(key=lambda entry: (0 if entry['gateway'] else 1, entry['alias'].lower()))
        return items
    except Exception:
        return []


def _list_network_adapters_from_ipconfig() -> List[Dict[str, str]]:
    try:
        result = subprocess.run(
            ['ipconfig'],
            check=True,
            capture_output=True,
            text=True,
            encoding=locale.getpreferredencoding(False),
            errors='ignore',
        )
    except Exception:
        return []

    adapters: List[Dict[str, str]] = []
    current: Optional[Dict[str, str]] = None
    pending_key: Optional[str] = None

    def extract_ipv4(text: str) -> str:
        match = re.search(r'(\d{1,3}(?:\.\d{1,3}){3})', text)
        return match.group(1) if match else ''

    def finish_current() -> None:
        nonlocal current
        if not current:
            return
        if current.get('ip') and not current.get('disconnected'):
            gateway = current.get('gateway', '')
            label = f"{current['alias']} - {current['ip']}"
            label += f" - GW {gateway}" if gateway else ' - sem gateway'
            current['label'] = label
            current['prefix_length'] = mask_to_prefix(current['subnet_mask']) if current.get('subnet_mask') else 24
            current.pop('disconnected', None)
            adapters.append(current)
        current = None

    for raw_line in result.stdout.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            pending_key = None
            continue

        if not raw_line.startswith(' '):
            if stripped.endswith(':') and 'windows ip configuration' not in stripped.lower() and 'configuração ip do windows' not in stripped.lower():
                finish_current()
                alias = stripped[:-1]
                alias = re.sub(
                    r'^(Ethernet adapter|Wireless LAN adapter|Adaptador Ethernet|Adaptador de Ethernet|Adaptador de LAN sem Fio|Adaptador de Rede sem Fio|Adaptador Wi-Fi)\s+',
                    '',
                    alias,
                    flags=re.IGNORECASE,
                )
                current = {
                    'label': '',
                    'alias': alias,
                    'description': '',
                    'ip': '',
                    'prefix_length': 24,
                    'subnet_mask': '',
                    'gateway': '',
                    'dns_server': '',
                    'disconnected': False,
                }
            pending_key = None
            continue

        if not current:
            continue

        lowered = stripped.lower()
        if 'media disconnected' in lowered or 'desconectada' in lowered:
            current['disconnected'] = True
            continue

        if 'ipv4' in lowered:
            current['ip'] = extract_ipv4(stripped)
            pending_key = None
            continue

        if 'subnet mask' in lowered or 'sub-rede' in lowered:
            current['subnet_mask'] = extract_ipv4(stripped)
            pending_key = None
            continue

        if 'default gateway' in lowered or 'gateway padr' in lowered:
            gateway = extract_ipv4(stripped)
            if gateway:
                current['gateway'] = gateway
                pending_key = None
            else:
                pending_key = 'gateway'
            continue

        if lowered.startswith('dns servers') or 'servidores dns' in lowered:
            dns_server = extract_ipv4(stripped)
            if dns_server:
                current['dns_server'] = dns_server
                pending_key = None
            else:
                pending_key = 'dns_server'
            continue

        if pending_key in ('gateway', 'dns_server'):
            candidate = extract_ipv4(stripped)
            if candidate:
                current[pending_key] = candidate
                pending_key = None

    finish_current()
    adapters.sort(key=lambda entry: (0 if entry.get('gateway') else 1, entry['alias'].lower()))
    return adapters


def port_in_use(ip: str, port: int, protocol: str) -> bool:
    protocol = protocol.lower()
    sock_type = socket.SOCK_STREAM if protocol == 'tcp' else socket.SOCK_DGRAM
    sock = socket.socket(socket.AF_INET, sock_type)
    try:
        sock.bind((ip, int(port)))
        return False
    except OSError:
        return True
    finally:
        sock.close()


def ensure_firewall_rule(name: str, protocol: str, port: int) -> None:
    subprocess.run(
        ['netsh', 'advfirewall', 'firewall', 'delete', 'rule', f'name={name}'],
        check=False,
        capture_output=True,
        text=True,
        encoding=locale.getpreferredencoding(False),
        errors='ignore',
    )
    subprocess.run(
        [
            'netsh', 'advfirewall', 'firewall', 'add', 'rule',
            f'name={name}',
            'dir=in',
            'action=allow',
            f'protocol={protocol.upper()}',
            f'localport={int(port)}',
            'profile=any',
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding=locale.getpreferredencoding(False),
        errors='ignore',
    )


def ensure_pxe_firewall_rules(http_port: int, tftp_port: int, dhcp_port: int) -> List[str]:
    rules = [
        ('PXE GEMINI Server HTTP', 'TCP', http_port),
        ('PXE GEMINI Server TFTP', 'UDP', tftp_port),
        ('PXE GEMINI Server DHCP', 'UDP', dhcp_port),
    ]
    created = []
    for name, protocol, port in rules:
        ensure_firewall_rule(name, protocol, port)
        created.append(f'{name} ({protocol}/{port})')
    return created


def ensure_directory(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def copy_if_different(source: str, destination: str) -> None:
    ensure_directory(os.path.dirname(destination))
    if not os.path.exists(destination):
        shutil.copy2(source, destination)
        return
    src_stat = os.stat(source)
    dst_stat = os.stat(destination)
    if src_stat.st_size != dst_stat.st_size or int(src_stat.st_mtime) > int(dst_stat.st_mtime):
        shutil.copy2(source, destination)


def parse_recent_macs(log_path: str) -> List[str]:
    if not os.path.exists(log_path):
        return []
    with open(log_path, 'r', encoding='utf-8', errors='ignore') as handle:
        content = handle.read()
    macs = []
    for match in re.findall(r'([0-9A-F]{2}(?:-[0-9A-F]{2}){5})', content.upper()):
        if match not in macs:
            macs.append(match)
    return macs
