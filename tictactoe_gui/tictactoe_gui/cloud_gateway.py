"""The Construct webpage gateway; retain the loopback ROS workstation backend."""
import argparse
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


def make_gateway(public_url, upstream_port=8765):
    """! @brief Forward only workstation routes through one explicit HTTPS origin."""
    parsed = urlsplit(public_url)
    if (parsed.scheme != 'https' or not parsed.hostname
            or not parsed.hostname.endswith('.robotigniteacademy.com')
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.port not in (None, 443) or not parsed.path.endswith('/webpage/')):
        raise ValueError('Use the exact HTTPS URL returned by webpage_address')
    origin = 'https://' + parsed.netloc
    routes = {'/', '/canvas', '/canvas.js', '/canvas.css',
              '/api/canvas', '/api/canvas/asset/chair', '/api/canvas/asset/docker',
              '/api/canvas/asset/smile', '/workbench.js', '/workbench.css', '/api/status', '/api/config',
              '/api/frame', '/api/snapshot', '/api/command', '/api/stop'}

    class Gateway(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def forward(self):
            path = urlsplit(self.path).path
            if path not in routes or (self.command == 'POST' and path not in
                                      ('/api/command', '/api/stop', '/api/canvas')):
                self.send_error(404)
                return
            body = None
            headers = {}
            if self.command == 'POST':
                if self.headers.get('Origin') != origin:
                    self.send_error(403, 'Invalid origin')
                    return
                try:
                    size = int(self.headers.get('Content-Length', '0'))
                    if not 0 < size <= (512000 if path == '/api/canvas' else 4096):
                        raise ValueError('Invalid body size')
                except ValueError:
                    self.send_error(400)
                    return
                body = self.rfile.read(size)
                headers = {'Origin': f'http://127.0.0.1:{upstream_port}',
                           'Content-Type': 'application/json',
                           'X-Workbench-Token': self.headers.get('X-Workbench-Token', '')}
            connection = HTTPConnection('127.0.0.1', upstream_port, timeout=5)
            try:
                connection.request(self.command, self.path, body=body, headers=headers)
                response = connection.getresponse()
                data = response.read()
                self.send_response(response.status)
                for name in ('Content-Type', 'Content-Security-Policy',
                             'X-Content-Type-Options'):
                    value = response.getheader(name)
                    if value:
                        self.send_header(name, value)
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except (OSError, TimeoutError):
                self.send_error(502, 'Workstation backend unavailable')
            finally:
                connection.close()

        do_GET = forward
        do_POST = forward
    return Gateway


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public-url', required=True)
    parser.add_argument('--port', type=int, default=7000)
    parser.add_argument('--upstream-port', type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('0.0.0.0', args.port),
                                 make_gateway(args.public_url, args.upstream_port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()