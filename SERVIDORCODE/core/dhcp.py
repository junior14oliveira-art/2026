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
        
        # Dual socket for Proxy Mode / BINL capability
        # Always open port 4011 (BINL) so that Dell/HP UEFI firmware
        # that sends ProxyDHCP requests directly to port 4011 is served.
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

        # Better UEFI compatibility: Lenovo/Dell notebooks often prefer ipxe.efi
        # snponly.efi can sometimes fail if it's not the right driver mix.
        if arch in ['6', '7', '9', '11']:
            return 'ipxe.efi'

        # BIOS legacy or default fallback
        return 'ipxe.efi' # Always use ipxe.efi if possible as it is the most complete loader

    def _build_packet(self, request: bytes, message_type: int, lease_ip: str, boot_file: str, include_pxe_vendor: bool) -> bytes:
        packet = bytearray(300)
        packet[0] = 2
        packet[1] = request[1]
        packet[2] = request[2]
        packet[3] = request[3]
        packet[4:8] = request[4:8]
        packet[8:12] = request[8:12]
        
        # Force the broadcast flag always — client has no IP at DISCOVER time
        # and cannot receive unicast. Dell UEFI requires this unconditionally.
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
                
        # Critical for UEFI ROMS to see the PXE Service even in non-proxy mode
        vendor = b'PXEClient'
        options.extend(struct.pack('BB', 60, len(vendor)) + vendor)
        if include_pxe_vendor:
            # Option 43: Vendor-encapsulated PXE options (properly structured)
            # Sub-option 6 (PXE_DISCOVERY_CONTROL) = 0x08 -> use list only, no multicast
            # Sub-option 10 (PXE_MENU_PROMPT)      = prompt string
            # Sub-option 255 (end)
            # Dell UEFI validates this structure before accepting the OFFER.
            pxe_menu_prompt = b'\x00PXE'
            vendor_encap = bytearray()
            vendor_encap += bytes([6, 1, 8])
            vendor_encap += bytes([10, len(pxe_menu_prompt)]) + pxe_menu_prompt
            vendor_encap += bytes([255])
            options.extend(struct.pack('BB', 43, len(vendor_encap)) + bytes(vendor_encap))
            
        options.append(255)
        packet[240:240 + len(options)] = options
        return bytes(packet[:240 + len(options)])

    def listen(self) -> None:
        try:
            self.sock.bind(('', self.port))
            # ALWAYS open port 4011 (BINL/ProxyDHCP), regardless of mode_proxy.
            # Dell and HP UEFI sends a separate ProxyDHCP Discover to :4011
            # after receiving the DHCP Offer on port 68. Without a response
            # there, the firmware repeats DISCOVER indefinitely.
            try:
                self.sock_binl = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.sock_binl.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.sock_binl.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                self.sock_binl.bind(('', 4011))
                self.sock_binl.settimeout(0.5)
                self._log('info', 'BINL/ProxyDHCP socket aberto na porta 4011')
            except Exception as binl_err:
                self._log('warning', 'Nao foi possivel abrir porta 4011 (BINL): %s', binl_err)
                self.sock_binl = None
            self.sock.settimeout(0.5)
        except Exception as e:
            self._log('error', f"Bind falhou: {e}")
            return

        mode_label = 'ProxyDHCP' if self.mode_proxy else 'DHCP'
        self._log('info', '%s ativo em %s:%s | BINL porta 4011 %s', mode_label, self.ip, self.port,
                  'aberta' if self.sock_binl else 'FALHOU')

        import select
        try:
            while self.running:
                sockets = [self.sock]
                # Always include sock_binl (port 4011) if it was opened.
                if self.sock_binl:
                    sockets.append(self.sock_binl)
                    
                try:
                    readable, _, _ = select.select(sockets, [], [], 0.5)
                except (OSError, ValueError):
                    break
                
                for s in readable:
                    try:
                        message, addr = s.recvfrom(2048)
                    except OSError:
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
                    is_binl_port = (self.sock_binl is not None and s == self.sock_binl)

                    if is_ipxe and msg_type == TYPE_REQUEST:
                        self._log('info', 'iPXE solicitando Boot: %s -> %s', client_mac, boot_file)

                    if msg_type == TYPE_DISCOVER:
                        self._log('info', 'DHCP DISCOVER %s -> oferta %s | boot %s | porta=%s',
                                  client_mac, lease_ip, boot_file, '4011(BINL)' if is_binl_port else '67')
                        packet = self._build_packet(message, 2, lease_ip, boot_file, include_pxe_vendor)
                        # Always broadcast — client has no IP yet.
                        for dest in ('255.255.255.255', self.broadcast):
                            try:
                                s.sendto(packet, (dest, 68))
                            except OSError:
                                pass
                        self._log('info', 'DHCP OFFER enviado [porta=%s]', '4011' if is_binl_port else '67')

                    elif msg_type == TYPE_REQUEST or msg_type == 8:
                        if msg_type == 8 and not self.mode_proxy:
                            continue # Ignore DHCPINFORM if we are the real DHCP
                        self._log('info', 'DHCP REQUEST recebido de %s', client_mac)
                        packet = self._build_packet(message, 5, lease_ip, boot_file, include_pxe_vendor)
                        ciaddr = message[12:16]
                        client_has_ip = (ciaddr != b'\x00\x00\x00\x00')
                        if client_has_ip and addr[0] != '0.0.0.0':
                            targets = ['255.255.255.255', addr[0]]
                        else:
                            targets = ['255.255.255.255', self.broadcast]
                        for dest in targets:
                            try:
                                s.sendto(packet, (dest, 68))
                            except Exception:
                                pass
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
