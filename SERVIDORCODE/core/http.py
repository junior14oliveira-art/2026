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

        # INTERCEPT: Virtual ISO Paths
        # Pattern: virtual/{key}/filename
        if relative.startswith("virtual/"):
            parts = relative.split('/', 2)
            if len(parts) >= 3:
                key = parts[1]
                filename = parts[2]
                extract_root = os.path.join(root, "data", "extracted", key)
                if os.path.isdir(extract_root):
                    path = os.path.join(extract_root, filename.replace('/', os.sep))
                else:
                    self.send_error(404, f"ISO extracted root not found for: {key}")
                    return None
            else:
                # Legacy / fallback for single ISO
                active_extract = getattr(self.server, "active_extract_dir", None)
                if active_extract:
                    path = os.path.join(active_extract, relative.replace("virtual/", "", 1).replace('/', os.sep))

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
        # Unsilencing for 404 debug
        logger = getattr(self.server, 'custom_logger', None)
        message = format % args
        if logger:
            if " 404 " in message:
                logger.warning(f"HTTP 404: {message}")
            else:
                # Still silence the 200/206 to avoid flooding
                pass

class ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True

class HTTPD:
    def __init__(self, config, logger=None):
        # We bind to 0.0.0.0 (all interfaces) to avoid connection timeouts on specific Windows adapters
        self.ip = '0.0.0.0'
        self.port = int(config.get('http_port', 80))
        self.logger = logger
        self.running = True
        self.server = None

    def _log(self, level: str, message: str, *args) -> None:
        if not self.logger:
            return
        getattr(self.logger, level.lower())(message, *args)

    def listen(self):
        try:
            self.server = ThreadedHTTPServer((self.ip, self.port), RangeHTTPRequestHandler)
            # Calculate root path robustly (two levels up from core/http.py)
            core_dir = os.path.dirname(os.path.abspath(__file__))
            self.server.document_root = os.path.dirname(core_dir)
            
            # Pass logger to the handler class
            self.server.custom_logger = self.logger
            
            self._log('info', 'Otimized HTTP Server ativo em http://%s:%s', self.ip, self.port)
            self._log('info', 'Raiz do documento: %s', self.server.document_root)
            self.server.serve_forever()
        except Exception as e:
            self._log('error', f"HTTP falhou: {e}")
            self.stop()

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
