import http.server
import os
import threading
from socketserver import ThreadingMixIn
from urllib.parse import unquote, urlparse

from . import helpers


class _ThreadingHTTPServer(ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class HTTPD:
    def __init__(self, config, logger=None):
        self.ip = config.get('server_ip', '0.0.0.0')
        self.port = int(config.get('http_port', 80))
        self.netboot_directory = config.get('extract_dir', '.')
        self.logger = logger
        self.server = None
        self.thread = None

    def _make_handler(self):
        root = self.netboot_directory
        logger = self.logger

        class RequestHandler(http.server.BaseHTTPRequestHandler):
            server_version = 'PXEGEMINIHTTP/2.0'

            def _send_file(self, head_only: bool = False) -> None:
                parsed = urlparse(self.path)
                relative = unquote(parsed.path.lstrip('/'))
                if not relative:
                    self.send_error(404, 'Not Found')
                    return
                
                # Handling custom strelec mapping
                if relative.startswith("strelec/"):
                    relative = relative.replace("strelec/", "strelec\\", 1)

                try:
                    full_path = helpers.normalize_path(root, relative.replace('/', os.sep))
                except helpers.PathTraversalException:
                    self.send_error(403, 'Forbidden')
                    if logger:
                        logger.warning('HTTP 403 %s', self.path)
                    return

                if not os.path.isfile(full_path):
                    self.send_error(404, 'Not Found')
                    if logger:
                        logger.warning('HTTP 404 %s', self.path)
                    return

                file_size = os.path.getsize(full_path)
                self.send_response(200)
                self.send_header('Content-Length', str(file_size))
                self.send_header('Content-Type', 'application/octet-stream')
                self.send_header('Connection', 'close')
                self.end_headers()

                if not head_only:
                    with open(full_path, 'rb') as handle:
                        while True:
                            chunk = handle.read(1024 * 128)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                if logger:
                    logger.info('HTTP 200 %s', self.path)

            def do_GET(self):
                self._send_file(head_only=False)

            def do_HEAD(self):
                self._send_file(head_only=True)

            def log_message(self, fmt, *args):
                return

        return RequestHandler

    def listen(self):
        handler = self._make_handler()
        self.server = _ThreadingHTTPServer((self.ip, self.port), handler)
        if self.logger:
            self.logger.info('HTTP ativo em http://%s:%s/', self.ip, self.port)
        self.server.serve_forever(poll_interval=0.5)

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
