import os
import re
import socket
import threading
from urllib.parse import unquote, urlparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import socketserver
import shutil

class RangeHTTPRequestHandler(BaseHTTPRequestHandler):
    """
    Extremely optimized HTTP request handler specifically designed for HTTPDisk PXE booting.
    Supports HTTP Range requests (206) efficiently so `httpdisk.exe` can randomly access ISO blocks.
    """
    server_version = 'PXE_FAST_HTTP/1.0'

    def send_head(self):
        root = self.server.document_root
        parsed = urlparse(self.path)
        relative = unquote(parsed.path.lstrip('/'))

        # Fallback security check
        if '..' in relative:
            self.send_error(403, "Forbidden")
            return None

        # Resolve path
        path = os.path.join(root, relative.replace('/', os.sep))

        # WinPE embedded scripts sometimes look inside hardcoded paths
        # If it doesn't exist natively, we will try to intercept ISO files mapped.
        if not os.path.exists(path):
            # Virtual Mapping: If it requests anything inside /virtual/, we redirect to the active ISO extracted root
            # Example: http://x/virtual/boot.wim
            if relative.startswith("virtual/"):
                active_extract = getattr(self.server, "active_extract_dir", None)
                if active_extract:
                    path = os.path.join(active_extract, relative.replace("virtual/", "", 1).replace('/', os.sep))
                    if not os.path.exists(path):
                        self.send_error(404, "Not Found")
                        return None
            else:
                self.send_error(404, "Not Found")
                return None

        if os.path.isdir(path):
            self.send_error(403, "Directory listing disabled in FAST HTTP")
            return None

        try:
            f = open(path, 'rb')
        except OSError:
            self.send_error(404, "File not found")
            return None

        fs = os.fstat(f.fileno())
        file_size = fs[6]
        
        # Range handling logic
        range_header = self.headers.get('Range')
        
        if range_header:
            match = re.match(r'bytes=(\d+)-(\d*)', range_header)
            if match:
                first_byte = int(match.group(1))
                last_byte = match.group(2)
                
                if last_byte:
                    last_byte = int(last_byte)
                else:
                    last_byte = file_size - 1
                
                if first_byte > last_byte or first_byte >= file_size:
                    self.send_error(416, "Requested Range Not Satisfiable")
                    f.close()
                    return None
                    
                length = last_byte - first_byte + 1
                
                self.send_response(206)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Range", f"bytes {first_byte}-{last_byte}/{file_size}")
                self.send_header("Content-Length", str(length))
                self.send_header("Last-Modified", self.date_time_string(fs.st_mtime))
                self.end_headers()
                
                f.seek(first_byte)
                return f, length

        # Regular request
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(file_size))
        self.send_header("Last-Modified", self.date_time_string(fs.st_mtime))
        self.end_headers()
        return f, file_size

    def do_GET(self):
        response = self.send_head()
        if response:
            f, length = response
            try:
                # Optimized block reading
                bytes_sent = 0
                while bytes_sent < length:
                    chunk_size = min(65536, length - bytes_sent)
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    bytes_sent += len(chunk)
            except Exception as e:
                pass # Client disconnected early, common in HTTPDisk
            finally:
                f.close()

    def do_HEAD(self):
        f = self.send_head()
        if f:
            f[0].close()

    def log_message(self, format, *args):
        # We silence logging because HTTPDisk makes thousands of small requests per second
        pass

class ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True

class HTTPD:
    def __init__(self, config, logger=None):
        self.ip = config.get('server_ip', '0.0.0.0')
        self.port = int(config.get('http_port', 80))
        self.root = os.path.abspath(config.get('boot_dir', '.'))
        self.logger = logger
        self.server = None
        self.thread = None

    def listen(self):
        try:
            self.server = ThreadedHTTPServer((self.ip, self.port), RangeHTTPRequestHandler)
            self.server.document_root = os.path.dirname(os.path.abspath(__file__)).replace('\\core', '') # Sets root to E:\PXEGEMINI\SERVIDORCODE
            if self.logger:
                self.logger.info(f"Otimized HTTP Server ativo em http://{self.ip}:{self.port}")
            self.server.serve_forever()
        except Exception as e:
            if self.logger:
                self.logger.error(f"Falha ao iniciar Servidor HTTP: {e}")

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
