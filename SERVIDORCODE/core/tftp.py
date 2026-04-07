import os
import select
import socket
import struct
import time

from . import helpers


class TFTPD:
    def __init__(self, config, logger=None):
        self.ip = config.get('server_ip', '0.0.0.0')
        self.port = int(config.get('tftp_port', 69))
        self.netboot_directory = config.get('boot_dir', '.')
        self.logger = logger
        self.running = True
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind(('', self.port))
        self.server_socket.setblocking(False)
        self.sessions = {}

    def _log(self, level: str, message: str, *args) -> None:
        if not self.logger:
            return
        getattr(self.logger, level.lower())(message, *args)

    def _parse_rrq(self, packet: bytes):
        parts = packet[2:].split(b'\x00')
        values = [part for part in parts if part != b'']
        if len(values) < 2:
            raise ValueError('RRQ invalido')
        filename = values[0].decode('ascii', errors='ignore').lstrip('/')
        mode = values[1].decode('ascii', errors='ignore').lower()
        options = {}
        for index in range(2, len(values), 2):
            if index + 1 >= len(values):
                break
            key = values[index].decode('ascii', errors='ignore').lower()
            value = values[index + 1].decode('ascii', errors='ignore')
            options[key] = value
        return filename, mode, options

    @staticmethod
    def _packet_data(block: int, payload: bytes) -> bytes:
        return struct.pack('!HH', 3, block & 0xFFFF) + payload

    @staticmethod
    def _packet_oack(options: dict) -> bytes:
        payload = bytearray(struct.pack('!H', 6))
        for key, value in options.items():
            payload.extend(key.encode('ascii'))
            payload.extend(b'\x00')
            payload.extend(str(value).encode('ascii'))
            payload.extend(b'\x00')
        return bytes(payload)

    @staticmethod
    def _packet_error(code: int, message: str) -> bytes:
        return struct.pack('!HH', 5, code) + message.encode('ascii', errors='ignore') + b'\x00'

    def _send_packet(self, sock: socket.socket, state: dict, packet: bytes) -> None:
        sock.sendto(packet, state['addr'])
        state['last_packet'] = packet
        state['last_sent'] = time.time()
        state['retries'] = 0

    def _send_next_data(self, sock: socket.socket, state: dict) -> None:
        block = state['next_block']
        chunk = state['fh'].read(state['block_size'])
        packet = self._packet_data(block, chunk)
        self._send_packet(sock, state, packet)
        state['last_block'] = block
        state['next_block'] += 1
        state['final_block'] = len(chunk) < state['block_size']
        state['phase'] = 'data'

    def _cleanup(self, sock: socket.socket) -> None:
        state = self.sessions.pop(sock, None)
        if not state:
            return
        try:
            state['fh'].close()
        except Exception:
            pass
        try:
            sock.close()
        except Exception:
            pass

    def _handle_rrq(self, message: bytes, addr) -> None:
        filename, mode, options = self._parse_rrq(message)
        if mode != 'octet':
            self.server_socket.sendto(self._packet_error(0, 'Only octet supported'), addr)
            return
        path = helpers.normalize_path(self.netboot_directory, filename)
        if not os.path.isfile(path):
            self.server_socket.sendto(self._packet_error(1, 'File not found'), addr)
            self._log('warning', 'TFTP arquivo nao encontrado: %s', filename)
            return

        block_size = 512
        negotiated = {}
        if 'blksize' in options:
            try:
                requested = int(options['blksize'])
                block_size = max(512, min(requested, 1468))
                negotiated['blksize'] = block_size
            except ValueError:
                block_size = 512
        if 'tsize' in options:
            negotiated['tsize'] = os.path.getsize(path)

        client_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        client_sock.bind(('', 0))
        client_sock.setblocking(False)
        state = {
            'addr': addr,
            'fh': open(path, 'rb'),
            'path': path,
            'block_size': block_size,
            'next_block': 1,
            'last_block': 0,
            'final_block': False,
            'phase': 'oack' if negotiated else 'data',
            'last_packet': b'',
            'last_sent': time.time(),
            'retries': 0,
            'timeout': 1.5,
            'max_retries': 6,
        }
        self.sessions[client_sock] = state
        self._log('info', 'TFTP RRQ %s de %s | blksize=%s', filename, addr[0], block_size)
        if negotiated:
            self._send_packet(client_sock, state, self._packet_oack(negotiated))
        else:
            self._send_next_data(client_sock, state)

    def _handle_session_packet(self, sock: socket.socket) -> None:
        state = self.sessions.get(sock)
        if not state:
            return
        message, _ = sock.recvfrom(2048)
        opcode = struct.unpack('!H', message[:2])[0]
        if opcode != 4:
            return
        block = struct.unpack('!H', message[2:4])[0]
        if state['phase'] == 'oack':
            if block == 0:
                self._send_next_data(sock, state)
            return
        if block != (state['last_block'] & 0xFFFF):
            return
        if state['final_block']:
            self._log('info', 'TFTP serviu %s para %s', os.path.basename(state['path']), state['addr'][0])
            self._cleanup(sock)
            return
        self._send_next_data(sock, state)

    def _check_timeouts(self) -> None:
        now = time.time()
        for sock, state in list(self.sessions.items()):
            if now - state['last_sent'] <= state['timeout']:
                continue
            if state['retries'] >= state['max_retries']:
                self._log('warning', 'TFTP timeout em %s para %s', os.path.basename(state['path']), state['addr'][0])
                self._cleanup(sock)
                continue
            sock.sendto(state['last_packet'], state['addr'])
            state['last_sent'] = now
            state['retries'] += 1

    def listen(self) -> None:
        self._log('info', 'TFTP ativo em %s:%s', self.ip, self.port)
        try:
            while self.running:
                sockets = [self.server_socket] + list(self.sessions.keys())
                try:
                    readable, _, _ = select.select(sockets, [], [], 0.5)
                except (OSError, ValueError) as exc:
                    if not self.running or getattr(exc, 'winerror', None) == 10038:
                        break
                    raise
                for sock in readable:
                    if sock == self.server_socket:
                        try:
                            message, addr = self.server_socket.recvfrom(2048)
                        except OSError as exc:
                            if not self.running or getattr(exc, 'winerror', None) == 10038:
                                break
                            raise
                        opcode = struct.unpack('!H', message[:2])[0]
                        if opcode == 1:
                            try:
                                self._handle_rrq(message, addr)
                            except Exception as exc:
                                self._log('error', 'TFTP RRQ falhou: %s', exc)
                    else:
                        try:
                            self._handle_session_packet(sock)
                        except Exception as exc:
                            self._log('error', 'TFTP sessao falhou: %s', exc)
                            self._cleanup(sock)
                self._check_timeouts()
        finally:
            for sock in list(self.sessions.keys()):
                self._cleanup(sock)
            try:
                self.server_socket.close()
            except Exception:
                pass

    def stop(self) -> None:
        self.running = False
        try:
            self.server_socket.close()
        except Exception:
            pass
