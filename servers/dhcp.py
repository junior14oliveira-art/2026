import socket
import struct
import time
from typing import Dict, Optional

from . import helpers

TYPE_DISCOVER = 1
TYPE_REQUEST = 3


class DHCPD:
    def __init__(self, config, logger=None):
        self.config = config
        self.logger = logger
        self.ip = self.config['server_ip']
        self.port = int(self.config['dhcp_port'])
        self.mode_proxy = self.config.get('mode_proxy', True)
        self.broadcast = helpers.compute_broadcast(self.ip, self.config.get('subnet_mask', "255.255.255.0"))
        self.reply_broadcast = '255.255.255.255'
        
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        
        # Dual socket for Proxy Mode capability
        self.sock_binl = None
        self.running = True
        self.leases: Dict[str, Dict[str, float]] = {}
        self.recent_clients = []

    def _log(self, level: str, message: str, *args) -> None:
        if self.logger:
            getattr(self.logger, level.lower())(message, *args)

    @staticmethod
    def _parse_options(raw: bytes) -> Dict[int, list]:
        options = {}
        index = 0
        while index < len(raw):
            code = raw[index]
            if code == 0:
                index += 1
                continue
            if code == 255:
                break
            if index + 1 >= len(raw):
                break
            length = raw[index + 1]
            start = index + 2
            end = start + length
            value = raw[start:end]
            options.setdefault(code, []).append(value)
            index = end
        return options

    @staticmethod
    def _option(options: Dict[int, list], code: int) -> Optional[bytes]:
        values = options.get(code)
        return values[0] if values else None

    @staticmethod
    def _option_text(options: Dict[int, list], code: int) -> str:
        value = DHCPD._option(options, code)
        if not value:
            return ''
        try:
            return value.decode('ascii', errors='ignore')
        except Exception:
            return ''

    @staticmethod
    def _arch(options: Dict[int, list]) -> Optional[str]:
        value = DHCPD._option(options, 93)
        if not value or len(value) < 2:
            return None
        return str(struct.unpack('!H', value[:2])[0])

    @staticmethod
    def _message_type(options: Dict[int, list]) -> Optional[int]:
        value = DHCPD._option(options, 53)
        return value[0] if value else None

    def _is_ipxe(self, options: Dict[int, list]) -> bool:
        vendor = self._option_text(options, 60).upper()
        user = self._option_text(options, 77).upper()
        return 'IPXE' in vendor or 'IPXE' in user

    def _should_serve(self, mac: str) -> bool:
        return True

    def _next_pool_ip(self) -> str:
        # Compatibility with PXEGEMINI config structure
        begin = helpers.ipv4_to_int(self.config.get('pool_begin', '192.168.0.200'))
        end = helpers.ipv4_to_int(self.config.get('pool_end', '192.168.0.250'))
        server_ip = self.config['server_ip']
        gateway = self.config.get('gateway') or ''
        leased = {details['ip'] for details in self.leases.values() if details['expire'] > time.time()}
        for value in range(begin, end + 1):
            ip = helpers.int_to_ipv4(value)
            if ip == server_ip or ip == gateway:
                continue
            if ip in leased:
                continue
            return ip
        raise RuntimeError('Sem IP livre no pool DHCP.')

    def _lease_for(self, mac: str) -> str:
        lease = self.leases.get(mac)
        if lease and lease['expire'] > time.time():
            return lease['ip']
        try:
            ip = self._next_pool_ip()
        except Exception:
            ip = self.config.get('pool_begin', '192.168.0.200') # fallback
        self.leases[mac] = {'ip': ip, 'expire': time.time() + 86400}
        return ip

    def _boot_file_for(self, mac: str, options: Dict[int, list], is_ipxe: bool) -> str:
        if is_ipxe:
            return 'menu.ipxe'

        arch = self._arch(options)

        # Prioridade UEFI: snponly.efi usa driver nativo da placa-mae
        # Funciona no Dell 5420 e Lenovo (UEFI only, sem legacy)
        if arch in ['6', '7', '9', '11'] or arch is None:
            # Arch None = cliente nao reportou architektura, usa snponly.efi como fallback
            return 'snponly.efi'

        # BIOS legacy
        return 'ipxe.efi'

    def _build_packet(self, request: bytes, message_type: int, lease_ip: str, boot_file: str, include_pxe_vendor: bool) -> bytes:
        packet = bytearray(300)
        packet[0] = 2
        packet[1] = request[1]
        packet[2] = request[2]
        packet[3] = request[3]
        packet[4:8] = request[4:8]
        packet[8:12] = request[8:12]
        
        # Force broadcast response flag for ProxyMode, else follow request
        if self.mode_proxy:
            packet[10:12] = b'\x80\x00'
            
        packet[24:28] = request[24:28]
        packet[28:44] = request[28:44]
        
        yiaddr = '0.0.0.0' if self.mode_proxy else lease_ip
        packet[16:20] = socket.inet_aton(yiaddr)
        packet[20:24] = socket.inet_aton(self.ip)
        
        boot_bytes = boot_file.encode('ascii', errors='ignore')
        packet[108:108 + len(boot_bytes)] = boot_bytes[:128]
        packet[236:240] = struct.pack('!I', 0x63825363)

        options = bytearray()
        options.extend(struct.pack('BBB', 53, 1, message_type))
        options.extend(struct.pack('BB', 54, 4) + socket.inet_aton(self.ip))
        options.extend(struct.pack('BB', 66, len(self.ip.encode('ascii'))) + self.ip.encode('ascii'))
        options.extend(struct.pack('BB', 67, len(boot_bytes)) + boot_bytes)
        
        if not self.mode_proxy:
            options.extend(struct.pack('BB', 51, 4) + struct.pack('!I', 86400))
            options.extend(struct.pack('BB', 1, 4) + socket.inet_aton(self.config.get('subnet_mask', "255.255.255.0")))
            ifpers_gw = self.config.get('gateway', '')
            if helpers.is_valid_ipv4(ifpers_gw):
                options.extend(struct.pack('BB', 3, 4) + socket.inet_aton(ifpers_gw))
            ifpers_dns = self.config.get('dns_server', '')
            if helpers.is_valid_ipv4(ifpers_dns):
                options.extend(struct.pack('BB', 6, 4) + socket.inet_aton(ifpers_dns))
                
        if self.mode_proxy and include_pxe_vendor:
            vendor = b'PXEClient'
            options.extend(struct.pack('BB', 60, len(vendor)) + vendor)
            # Standard PXE discovery option
            options.extend(bytes([43, 10, 6, 1, 8, 10, 4, 0, 80, 88, 69, 255]))
            
        options.append(255)
        packet[240:240 + len(options)] = options
        return bytes(packet[:240 + len(options)])

    def listen(self) -> None:
        try:
            self.sock.bind(('', self.port))
            if self.mode_proxy:
                self.sock_binl = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.sock_binl.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.sock_binl.bind(('', 4011))
                self.sock_binl.settimeout(0.5)
            self.sock.settimeout(0.5)
        except Exception as e:
            self._log('error', f"Bind falhou: {e}")
            return

        mode_label = 'ProxyDHCP' if self.mode_proxy else 'DHCP'
        self._log('info', '%s ativo em %s:%s', mode_label, self.ip, self.port)
        
        import select
        try:
            while self.running:
                sockets = [self.sock]
                if self.mode_proxy and self.sock_binl:
                    sockets.append(self.sock_binl)
                    
                try:
                    readable, _, _ = select.select(sockets, [], [], 0.5)
                except (OSError, ValueError):
                    break
                
                for s in readable:
                    try:
                        message, addr = s.recvfrom(2048)
                    except OSError as exc:
                        if not self.running:
                            break
                        continue
                        
                    if len(message) < 240:
                        continue
                        
                    client_mac = helpers.normalize_mac(':'.join(f'{byte:02X}' for byte in message[28:34]))
                    options = self._parse_options(message[240:])
                    msg_type = self._message_type(options)
                    
                    if msg_type not in (TYPE_DISCOVER, TYPE_REQUEST):
                        if msg_type != 8: # INFORM
                            continue
                            
                    vendor = self._option_text(options, 60)
                    user = self._option_text(options, 77)
                    
                    # Accept requests from PXE or iPXE
                    if 'PXECLIENT' not in vendor.upper() and 'IPXE' not in vendor.upper() and 'IPXE' not in user.upper():
                        continue
                        
                    lease_ip = self._lease_for(client_mac)
                    is_ipxe = self._is_ipxe(options)
                    boot_file = self._boot_file_for(client_mac, options, is_ipxe)
                    include_pxe_vendor = not is_ipxe
                    
                    if is_ipxe and msg_type == TYPE_REQUEST:
                        self._log('info', 'iPXE solicitando Boot: %s -> %s', client_mac, boot_file)
                        
                    if msg_type == TYPE_DISCOVER:
                        self._log('info', 'DHCP DISCOVER recebido de %s -> oferta %s | boot %s', client_mac, lease_ip, boot_file)
                        packet = self._build_packet(message, 2, lease_ip, boot_file, include_pxe_vendor)
                        s.sendto(packet, (self.reply_broadcast, 68))
                        self._log('info', 'DHCP OFFER enviado')
                        
                    elif msg_type == TYPE_REQUEST or msg_type == 8:
                        if msg_type == 8 and not self.mode_proxy:
                            continue # Ignore DHCPINFORM if we are the real DHCP
                        self._log('info', 'DHCP REQUEST recebido de %s', client_mac)
                        packet = self._build_packet(message, 5, lease_ip, boot_file, include_pxe_vendor)
                        # Proxy sends to client port directly
                        dest_ip = self.reply_broadcast if not self.mode_proxy else addr[0]
                        dest_port = 68
                        s.sendto(packet, (dest_ip, dest_port))
                        self._log('info', 'DHCP ACK enviado')
        finally:
            self.stop()

    def stop(self) -> None:
        self.running = False
        try:
            self.sock.close()
        except Exception:
            pass
        if getattr(self, 'sock_binl', None):
            try:
                self.sock_binl.close()
            except Exception:
                pass
