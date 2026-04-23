import os
import socket
import struct
import time
from typing import Dict, Optional

from . import helpers

TYPE_DISCOVER = 1
TYPE_REQUEST = 3
IPXE_FEATURE_HTTP = 19


class DHCPD:
    def __init__(self, config, logger=None):
        self.config = config
        self.logger = logger
        self.ip = self.config['server_ip']
        self.port = int(self.config['dhcp_port'])
        self.mode_proxy = self.config.get('mode_proxy', True)
        self.compat_profile = str(self.config.get('compat_profile', 'auto')).lower()
        self.network_profile = str(self.config.get('network_profile', 'isolated')).lower()
        self.boot_dir = self.config.get('boot_dir', 'boot')
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
        self._pool_autofix_logged = False

    def _http_boot_url(self, path: str) -> str:
        normalized = path.lstrip('/')
        return f"http://{self.ip}:{self.config.get('http_port', 80)}/{normalized}"

    @staticmethod
    def _append_option(options: bytearray, code: int, value: Optional[bytes]) -> None:
        if value is None:
            return
        options.extend(struct.pack('BB', code, len(value)) + value)

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

    def _ipxe_features(self, options: Dict[int, list]) -> Dict[int, bytes]:
        payload = self._option(options, 175)
        if not payload:
            return {}
        return self._parse_options(payload)

    def _ipxe_has_feature(self, options: Dict[int, list], feature_code: int) -> bool:
        features = self._ipxe_features(options)
        value = features.get(feature_code, [b''])
        return bool(value and value[0][:1] not in (b'', b'\x00'))

    def _should_serve(self, mac: str) -> bool:
        return True

    def _effective_pool_range(self):
        mask = self.config.get('subnet_mask', "255.255.255.0")
        try:
            server_value = helpers.ipv4_to_int(self.ip)
            mask_value = helpers.ipv4_to_int(mask)
        except OSError:
            begin = helpers.ipv4_to_int(self.config.get('pool_begin', '192.168.0.200'))
            end = helpers.ipv4_to_int(self.config.get('pool_end', '192.168.0.250'))
            return begin, end, begin, end

        network = server_value & mask_value
        broadcast = (network | ((~mask_value) & 0xFFFFFFFF)) & 0xFFFFFFFF
        usable_start = network + 1
        usable_end = broadcast - 1

        if usable_start > usable_end:
            return server_value, server_value, server_value, server_value

        begin_cfg = self.config.get('pool_begin', '')
        end_cfg = self.config.get('pool_end', '')
        valid_cfg = helpers.is_valid_ipv4(begin_cfg) and helpers.is_valid_ipv4(end_cfg)
        if valid_cfg:
            begin = helpers.ipv4_to_int(begin_cfg)
            end = helpers.ipv4_to_int(end_cfg)
            if begin <= end and usable_start <= begin <= usable_end and usable_start <= end <= usable_end:
                return begin, end, usable_start, usable_end

        suggested = helpers.suggest_dhcp_range(self.ip, mask)
        begin = helpers.ipv4_to_int(suggested['pool_begin'])
        end = helpers.ipv4_to_int(suggested['pool_end'])
        if not self._pool_autofix_logged:
            self._log(
                'warning',
                'Pool DHCP fora da sub-rede %s/%s. Ajustando faixa para %s - %s.',
                self.ip,
                mask,
                suggested['pool_begin'],
                suggested['pool_end'],
            )
            self._pool_autofix_logged = True
        return begin, end, usable_start, usable_end

    def _next_pool_ip(self) -> str:
        begin, end, usable_start, usable_end = self._effective_pool_range()
        server_ip = self.config['server_ip']
        gateway = self.config.get('gateway') or ''
        gateway_value = None
        if helpers.is_valid_ipv4(gateway):
            value = helpers.ipv4_to_int(gateway)
            if usable_start <= value <= usable_end:
                gateway_value = value
        leased = {details['ip'] for details in self.leases.values() if details['expire'] > time.time()}
        for value in range(begin, end + 1):
            ip = helpers.int_to_ipv4(value)
            if ip == server_ip:
                continue
            if gateway_value is not None and value == gateway_value:
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
            begin, _, _, _ = self._effective_pool_range()
            ip = helpers.int_to_ipv4(begin) # fallback
        self.leases[mac] = {'ip': ip, 'expire': time.time() + 86400}
        return ip

    def _boot_file_for(self, mac: str, options: Dict[int, list], can_http_chain: bool) -> str:
        if can_http_chain:
            return self._http_boot_url('boot/boot.ipxe')

        arch = self._arch(options)
        profile = self.compat_profile
        uefi_like = arch in ['6', '7', '9', '11'] or arch is None

        def loader_exists(name: str) -> bool:
            return os.path.isfile(os.path.join(self.boot_dir, name))

        if not uefi_like:
            candidates = ['undionly.kpxe', 'ipxe.pxe']
        elif profile == 'dell':
            candidates = ['snponly.efi', 'ipxe.efi']
        elif profile == 'lenovo':
            candidates = ['ipxe.efi', 'snponly.efi']
        else:
            # Auto follows the iVentoy-style path that worked on this Dell x64 box:
            # use SNP first in UEFI, keep iPXE as fallback.
            candidates = ['snponly.efi', 'ipxe.efi']

        for loader in candidates:
            if loader_exists(loader):
                return loader

        return candidates[0]

    def _reply_targets(self, addr, ciaddr: bytes = b'\x00\x00\x00\x00') -> list:
        """Build the list of (ip, port) targets to send the reply to.

        During DISCOVER/OFFER the client has no IP (ciaddr=0), so we MUST
        broadcast. When the client already has an IP (ciaddr != 0) we can
        unicast, but broadcasting is always safe and simpler.
        """
        targets = []

        def add(ip: str, port: int) -> None:
            item = (ip, port)
            if ip and item not in targets:
                targets.append(item)

        client_has_ip = (ciaddr != b'\x00\x00\x00\x00')

        # Always include the limited broadcast — it works in all scenarios
        # and is required when the client does not yet have an IP.
        add('255.255.255.255', 68)

        if not self.mode_proxy:
            # Also include the subnet broadcast for non-proxy full-DHCP mode.
            add(self.broadcast, 68)

        # If the client already has an IP (i.e. DHCP REQUEST after OFFER),
        # we can unicast directly to it as well.
        if client_has_ip and addr and addr[0] and addr[0] != '0.0.0.0':
            add(addr[0], 68)

        return targets

    def _build_packet(
        self,
        request: bytes,
        request_options: Dict[int, list],
        message_type: int,
        lease_ip: str,
        boot_file: str,
        include_pxe_vendor: bool,
        is_ipxe: bool,
    ) -> bytes:
        packet = bytearray(300)
        packet[0] = 2
        packet[1] = request[1]
        packet[2] = request[2]
        packet[3] = request[3]
        packet[4:8] = request[4:8]
        packet[8:12] = request[8:12]
        
        # Force the broadcast flag (bit 15 of flags field).
        # The client has no IP during DISCOVER so it cannot receive unicast.
        # Setting this bit tells layer-2 to broadcast the reply,
        # ensuring Dell/HP UEFI firmware always receives the OFFER.
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
        for code in (93, 94, 97):
            self._append_option(options, code, self._option(request_options, code))
        
        if not self.mode_proxy:
            options.extend(struct.pack('BB', 51, 4) + struct.pack('!I', 86400))
            options.extend(struct.pack('BB', 1, 4) + socket.inet_aton(self.config.get('subnet_mask', "255.255.255.0")))
            if self.network_profile != 'isolated':
                ifpers_gw = self.config.get('gateway', '')
                if helpers.is_valid_ipv4(ifpers_gw):
                    options.extend(struct.pack('BB', 3, 4) + socket.inet_aton(ifpers_gw))
                ifpers_dns = self.config.get('dns_server', '')
                if helpers.is_valid_ipv4(ifpers_dns):
                    options.extend(struct.pack('BB', 6, 4) + socket.inet_aton(ifpers_dns))
            if is_ipxe:
                # Official iPXE guidance recommends setting no-pxedhcp when there
                # is no separate ProxyDHCP server. This avoids waiting for PXE
                # offers that will never arrive and helps autoboot continue.
                options.extend(struct.pack('BBB', 176, 1, 1))

        vendor = b'PXEClient'
        options.extend(struct.pack('BB', 60, len(vendor)) + vendor)
        if include_pxe_vendor:
            # Option 43: Vendor-encapsulated PXE options
            # Sub-option 6 (PXE_DISCOVERY_CONTROL) = 0x08 -> disable multicast+broadcast discovery
            # Sub-option 10 (PXE_MENU_PROMPT)      = short prompt
            # Sub-option 255 (end)
            # This is the critical block that Dell UEFI firmware validates before
            # sending DHCP REQUEST. Without correct option 43, the Dell drops the OFFER.
            pxe_menu_prompt = b'\x00PXE'
            vendor_encap = bytearray()
            vendor_encap += bytes([6, 1, 8])                                  # discovery control: use list only
            vendor_encap += bytes([10, len(pxe_menu_prompt)]) + pxe_menu_prompt  # menu prompt
            vendor_encap += bytes([255])                                       # end
            options.extend(struct.pack('BB', 43, len(vendor_encap)) + bytes(vendor_encap))

        options.append(255)
        packet[240:240 + len(options)] = options
        return bytes(packet[:240 + len(options)])

    def listen(self) -> None:
        try:
            self.sock.bind(('', self.port))
            # ALWAYS open port 4011 (BINL/ProxyDHCP), regardless of mode_proxy.
            # Dell and HP UEFI firmware sends a separate ProxyDHCP Discover
            # directly to port 4011 after receiving the DHCP Offer on port 68.
            # If nothing answers on 4011, the firmware gives up and the
            # DISCOVER loop repeats indefinitely.
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
                    except OSError as exc:
                        if not self.running:
                            break
                        continue
                        
                    if len(message) < 240:
                        continue
                        
                    client_mac = helpers.normalize_mac(':'.join(f'{byte:02X}' for byte in message[28:34]))
                    options = self._parse_options(message[240:])
                    msg_type = self._message_type(options)
                    vendor = self._option_text(options, 60)
                    user = self._option_text(options, 77)
                    arch = self._arch(options) or '-'
                    
                    if msg_type not in (TYPE_DISCOVER, TYPE_REQUEST):
                        if msg_type != 8: # INFORM
                            continue
                            
                    # Accept requests from PXE or iPXE
                    if 'PXECLIENT' not in vendor.upper() and 'IPXE' not in vendor.upper() and 'IPXE' not in user.upper():
                        continue
                        
                    lease_ip = self._lease_for(client_mac)
                    is_ipxe = self._is_ipxe(options)
                    has_http = self._ipxe_has_feature(options, IPXE_FEATURE_HTTP)
                    can_http_chain = is_ipxe and has_http
                    boot_file = self._boot_file_for(client_mac, options, can_http_chain)
                    include_pxe_vendor = not can_http_chain

                    # Detect if this request came in on the BINL port 4011
                    is_binl_port = (self.sock_binl is not None and s == self.sock_binl)

                    if is_ipxe and msg_type == TYPE_REQUEST:
                        feature_label = 'http=on' if has_http else 'http=off'
                        self._log('info', 'iPXE solicitando boot: %s | vendor=%s | user=%s | arch=%s | %s -> %s',
                                  client_mac, vendor or '-', user or '-', arch, feature_label, boot_file)

                    if msg_type == TYPE_DISCOVER:
                        self._log('info', 'DHCP DISCOVER %s | vendor=%s | user=%s | arch=%s | ipxe_http=%s | porta=%s -> oferta %s | boot %s',
                                  client_mac, vendor or '-', user or '-', arch, 'sim' if has_http else 'nao',
                                  '4011(BINL)' if is_binl_port else '67', lease_ip, boot_file)
                        packet = self._build_packet(message, options, 2, lease_ip, boot_file, include_pxe_vendor, can_http_chain)
                        ciaddr = message[12:16]
                        for target in self._reply_targets(addr, ciaddr):
                            try:
                                s.sendto(packet, target)
                            except Exception:
                                continue
                        self._log('info', 'DHCP OFFER enviado [porta=%s]', '4011' if is_binl_port else '67')

                    elif msg_type == TYPE_REQUEST or msg_type == 8:
                        if msg_type == 8 and not self.mode_proxy:
                            continue # Ignore DHCPINFORM if we are the real DHCP
                        self._log('info', 'DHCP REQUEST %s | vendor=%s | user=%s | arch=%s | ipxe_http=%s -> boot %s',
                                  client_mac, vendor or '-', user or '-', arch, 'sim' if has_http else 'nao', boot_file)
                        packet = self._build_packet(message, options, 5, lease_ip, boot_file, include_pxe_vendor, can_http_chain)
                        ciaddr = message[12:16]
                        for target in self._reply_targets(addr, ciaddr):
                            try:
                                s.sendto(packet, target)
                            except Exception:
                                continue
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
