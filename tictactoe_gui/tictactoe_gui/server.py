"""Loopback-only tablet HTTP service with one serialized simulation worker."""
import argparse
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import json
import queue
import secrets
import signal
import threading
from pathlib import Path
from urllib.parse import urlparse

from tictactoe_gui.geometry import prepare_strokes, load_illustration


class CanvasSession:
    """! @brief Serialize jobs; keep HTTP responsive while ROS plans and executes."""
    def __init__(self, output, worker):
        self.output = Path(output).expanduser().resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.jobs = queue.Queue(maxsize=1)
        self.stop = threading.Event()
        self.shutdown = threading.Event()
        self.token = secrets.token_urlsafe(24)
        previous = max((int(p.stem[4:]) for p in self.output.glob('job-*.json')
                        if p.stem[4:].isdigit()), default=0)
        self.state = dict(state='connecting', message='正在连接本地仿真', busy=False,
                          stroke=0, total=0, completed=0, job=previous, events=[])
        self.worker = worker

    def update(self, **values):
        with self.lock:
            self.state.update(values)

    def status(self):
        with self.lock:
            return copy.deepcopy(self.state)

    def submit(self, kind, strokes=None):
        prepared = prepare_strokes(strokes) if kind == 'draw' else []
        with self.lock:
            if self.state['busy'] or self.state['state'] in ('connecting', 'offline', 'blocked'):
                raise RuntimeError('尚未就绪或已有任务正在执行')
            self.stop.clear()
            job = self.state['job']+1
            self.state.update(state='queued', message='任务已提交', busy=True,
                              job=job, stroke=0, completed=0, total=len(strokes or []), events=[])
            self.jobs.put_nowait(dict(job=job, kind=kind, strokes=strokes, prepared=prepared))
        return job

    def request_stop(self):
        with self.lock:
            if self.state['busy']:
                self.stop.set()
                self.state.update(state='stopping', message='正在停止，等待实际停稳')

    def run(self):
        try:
            self.worker(self)
        except BaseException as error:
            self.update(state='offline', busy=False, message=str(error))


def make_handler(session):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, status, data, content_type='application/json; charset=utf-8'):
            body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.startswith('/api/asset/'):
                try:
                    return self.send(200, load_illustration(self.path.removeprefix('/api/asset/')))
                except ValueError as error:
                    return self.send(404, {'error':str(error)})
            if self.path == '/api/status':
                return self.send(200, session.status())
            if self.path == '/api/config':
                return self.send(200, dict(token=session.token, width_mm=144, height_mm=193,
                                           environment='sim'))
            resources = {'/': ('index.html', 'text/html; charset=utf-8'),
                         '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                         '/style.css': ('style.css', 'text/css; charset=utf-8')}
            if self.path not in resources:
                return self.send(404, {'error': 'Not found'})
            name, content_type = resources[self.path]
            self.send(200, files('tictactoe_gui').joinpath('web', name).read_bytes(), content_type)

        def do_POST(self):
            # A random per-session header and same-origin check prevent cross-site motion requests.
            origin = self.headers.get('Origin')
            expected = 'http://'+self.headers.get('Host', '')
            if (self.headers.get('X-Canvas-Token') != session.token
                    or (origin is not None and origin != expected)
                    or urlparse(expected).hostname not in ('localhost', '127.0.0.1')):
                return self.send(403, {'error': '请求来源无效'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 512000:
                    return self.send(413, {'error': '请求过大或为空'})
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError('请求必须是对象')
                if self.path == '/api/stop':
                    session.request_stop()
                    return self.send(202, {'accepted': True})
                if self.path not in ('/api/draw', '/api/reset'):
                    return self.send(404, {'error': 'Not found'})
                job = session.submit('draw' if self.path == '/api/draw' else 'reset', data.get('strokes'))
                self.send(202, {'job': job, 'accepted': True})
            except (ValueError, TypeError, KeyError) as error:
                self.send(400, {'error': str(error)})
            except (RuntimeError, queue.Full) as error:
                self.send(409, {'error': str(error)})
    return Handler


def main():
    from rclpy.utilities import remove_ros_args
    from tictactoe_gui.sim_worker import simulation_worker
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--output', default=str(Path.home()/'.local/share/play_tictactoe/canvas_sim'))
    args = parser.parse_args(remove_ros_args()[1:])
    session = CanvasSession(args.output, simulation_worker)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(session))
    thread = threading.Thread(target=session.run, name='canvas-ros', daemon=True)
    thread.start()
    def halt(signum, frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, halt)
    signal.signal(signal.SIGINT, halt)
    print(f'CANVAS_GUI http://localhost:{args.port} OUTPUT {session.output}', flush=True)
    try:
        server.serve_forever(poll_interval=.1)
    except KeyboardInterrupt:
        pass
    finally:
        session.stop.set();session.shutdown.set()
        thread.join(timeout=15)
        server.server_close()
        if thread.is_alive():
            raise RuntimeError('ROS worker did not confirm shutdown')


if __name__ == '__main__':
    main()
