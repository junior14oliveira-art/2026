import http.server
import os
import threading
from socketserver import ThreadingMixIn
from urllib.parse import unquote, urlparse

from . import helpers

CHUNK = 128 * 1024  # 128 KB chunks


class _ThreadingHTTPServer(ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class HTTPD:
    def __init__(self, config, logger=None):
        self.ip = config.get('server_ip', '0.0.0.0')
        self.port = int(config.get('http_port', 80))
        self.netboot_directory = config.get('extract_dir', '.')
        self.boot_directory = config.get('boot_dir', 'boot')
        self.logger = logger
        self.server = None

    def _make_handler(self):
        root = self.netboot_directory
        boot_root = self.boot_directory
        logger = self.logger

        class RequestHandler(http.server.BaseHTTPRequestHandler):
            server_version = 'PXEGEMINIHTTP/2.1'

            def _resolve_path(self):
                parsed = urlparse(self.path)
                relative = unquote(parsed.path.lstrip('/'))
                if not relative:
                    return None

                # Boot assets live outside extract_dir. Keep them under /boot/
                # to mirror the second-stage HTTP handoff used by iPXE.
                if relative in {'menu.ipxe', 'boot.ipxe', 'autoexec.ipxe'}:
                    relative = f'boot/{relative}'
                if relative.startswith('boot/'):
                    boot_relative = relative[5:]
                    if not boot_relative:
                        return None
                    try:
                        return helpers.normalize_path(
                            boot_root, boot_relative.replace('/', os.sep))
                    except helpers.PathTraversalException:
                        return 'FORBIDDEN'

                if relative.startswith("strelec/"):
                    relative = relative.replace("strelec/", "strelec\\", 1)

                try:
                    full_path = helpers.normalize_path(
                        root, relative.replace('/', os.sep))
                except helpers.PathTraversalException:
                    return 'FORBIDDEN'

                # Intercept _raw.iso virtual routes
                if relative.endswith("_raw.iso") and "/" not in relative:
                    key = relative[:-8]
                    meta_path = os.path.join(root, key, ".pxegemini_meta")
                    if os.path.isfile(meta_path):
                        with open(meta_path, "r", encoding="utf-8") as f:
                            for line in f:
                                if line.startswith("path="):
                                    candidate = line.strip().split("=", 1)[1]
                                    if candidate and os.path.isfile(candidate):
                                        full_path = candidate
                                    break

                return full_path

            def _parse_range(self, file_size):
                """Parse Range header, return (start, end) or None."""
                range_hdr = self.headers.get('Range', '')
                if not range_hdr.startswith('bytes='):
                    return None
                try:
                    rng = range_hdr[6:]
                    start_s, end_s = rng.split('-', 1)
                    start = int(start_s) if start_s else 0
                    end   = int(end_s)   if end_s   else file_size - 1
                    end   = min(end, file_size - 1)
                    return start, end
                except Exception:
                    return None

            def _send_file(self, head_only=False):
                full_path = self._resolve_path()

                if full_path is None:
                    self.send_error(404, 'Not Found')
                    return
                if full_path == 'FORBIDDEN':
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
                rng = self._parse_range(file_size)

                if rng:
                    start, end = rng
                    length = end - start + 1
                    self.send_response(206)
                    self.send_header('Content-Range',
                                     'bytes {}-{}/{}'.format(start, end, file_size))
                    self.send_header('Content-Length', str(length))
                else:
                    start, length = 0, file_size
                    self.send_response(200)
                    self.send_header('Content-Length', str(file_size))

                self.send_header('Content-Type', 'application/octet-stream')
                self.send_header('Accept-Ranges', 'bytes')
                self.send_header('Connection', 'keep-alive')
                self.end_headers()

                if not head_only:
                    with open(full_path, 'rb') as fh:
                        fh.seek(start)
                        remaining = length
                        while remaining > 0:
                            data = fh.read(min(CHUNK, remaining))
                            if not data:
                                break
                            self.wfile.write(data)
                            remaining -= len(data)

                if logger:
                    code = 206 if rng else 200
                    logger.info('HTTP %d %s', code, self.path)

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
            self.logger.info('HTTP ativo em http://%s:%s/ [Range OK | boot=%s]',
                             self.ip, self.port, self.boot_directory)
        self.server.serve_forever(poll_interval=0.5)

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
