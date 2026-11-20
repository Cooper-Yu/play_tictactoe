"""Loopback-only tablet HTTP service with one serialized simulation worker."""
import argparse
from functools import partial

from tictactoe_coordinator.game_coordinator import WIN_LENGTHS
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import json
import queue
import secrets
import signal
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from tictactoe_gui.geometry import prepare_strokes, load_illustration


class CanvasSession:
    """! @brief Serialize jobs; keep HTTP responsive while ROS plans and executes."""
    def __init__(self, output, worker, *, vision_available=False):
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
                          stroke=0, total=0, completed=0, job=previous, events=[], game=None)
        self.worker = worker
        self.vision_available = vision_available
        self.latest_camera = None

    def update(self, **values):
        with self.lock:
            self.state.update(values)

    def status(self):
        with self.lock:
            return copy.deepcopy(self.state)

    def publish_camera(self, image):
        with self.lock:
            self.latest_camera = image
            self.state['camera_sequence'] = self.state.get('camera_sequence', 0) + 1

    def camera_image(self):
        with self.lock:
            return self.latest_camera

    def preview_frame(self):
        with self.lock:
            game = self.state["game"]
            return self.latest_camera, self.state.get("camera_sequence", 0), game["size"] if game else 0

    def submit(self, kind, strokes=None, game_request=None):
        prepared = prepare_strokes(strokes) if kind == 'draw' else []
        with self.lock:
            if self.state['busy'] or self.state['state'] in ('connecting', 'offline', 'blocked'):
                raise RuntimeError('尚未就绪或已有任务正在执行')
            current = self.state["game"]
            if kind == "draw" and current is not None:
                raise RuntimeError("请先用清屏退出当前对局")
            if kind == "game_next":
                if (current is None or current["revision"] != game_request["revision"]
                        or current["phase"] != "between_rounds"):
                    raise RuntimeError("当前无法进入第二局")
            if kind == "game_start" and game_request.get("input_source", "click") == "vision":
                if not self.vision_available:
                    raise RuntimeError("请先配置仿真 YOLO 权重")
                if game_request.get("mode", "classic") != "classic" or game_request["size"] != 3:
                    raise ValueError("视觉落子仅支持普通 3×3 井字棋")
            if kind in ("game_move", "game_vision_move"):
                row, col, revision = (game_request[k] for k in ("row", "col", "revision"))
                if (current is None or current["revision"] != revision
                        or current["phase"] != "player"):
                    raise RuntimeError("当前回合已变化，请等待页面刷新")
                source = "vision" if kind == "game_vision_move" else "click"
                if current.get("input_source", "click") != source:
                    raise RuntimeError("此落子入口与当前对局方式不匹配")
                if not (0 <= row < current["size"] and 0 <= col < current["size"]):
                    raise ValueError("格位超出棋盘")
                if current["board"][row][col]:
                    raise ValueError("该格已经落子")
            self.stop.clear()
            job = self.state['job']+1
            self.state.update(state='queued', message='任务已提交', busy=True,
                              job=job, stroke=0, completed=0, total=len(strokes or []), events=[])
            self.jobs.put_nowait(dict(job=job, kind=kind, strokes=strokes, prepared=prepared, game_request=game_request))
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


def make_handler(session, preview=None):
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
                                           environment='sim', vision_available=session.vision_available, game_modes=sorted({mode for mode, _ in WIN_LENGTHS})))
            path = urlparse(self.path).path
            if path == '/api/game/perception' and preview is not None:
                return self.send_preview()
            if path == '/api/game/camera':
                frame = session.camera_image()
                if frame is None:
                    return self.send(503, {'error': '暂未收到 Gazebo 相机图像'})
                return self.send(200, frame, 'image/jpeg')
            if path == '/api/game/frame':
                job = session.status().get('game_frame')
                evidence = session.output / f'job-{job}.png'
                if job is None or not evidence.is_file():
                    return self.send(404, {'error': '暂无棋盘照片'})
                return self.send(200, evidence.read_bytes(), 'image/png')
            resources = {'/game': ('game.html', 'text/html; charset=utf-8'),
                         '/game.js': ('game.js', 'text/javascript; charset=utf-8'),
                         '/game.css': ('game.css', 'text/css; charset=utf-8'),
                         '/': ('index.html', 'text/html; charset=utf-8'),
                         '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                         '/style.css': ('style.css', 'text/css; charset=utf-8')}
            if self.path not in resources:
                return self.send(404, {'error': 'Not found'})
            name, content_type = resources[self.path]
            self.send(200, files('tictactoe_gui').joinpath('web', name).read_bytes(), content_type)

        def send_preview(self):
            view = parse_qs(urlparse(self.path).query).get('view', ['rectified'])[0]
            camera, sequence, size = session.preview_frame()
            if camera is None:
                return self.send(503, {'error': '正在等待相机图像'})
            if view == 'detections' and not size:
                return self.send(409, {'error': '开局后可查看检测与格位'})
            try:
                image = preview.render(camera, sequence, size or 3, view)
            except ValueError as error:
                return self.send(400, {'error': str(error)})
            except Exception as error:
                print('GAME_PERCEPTION_FAILED', repr(error), flush=True)
                return self.send(503, {'error': str(error) if isinstance(error, RuntimeError)
                                       else '感知预览暂不可用'})
            if image is None:
                return self.send(503, {'error': '正在处理相机图像'})
            return self.send(200, image, 'image/jpeg')

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
                game_routes = {'/api/game/start': 'game_start', '/api/game/move': 'game_move',
                               '/api/game/next': 'game_next',
                               '/api/game/simulate-player': 'game_vision_move'}
                if self.path in game_routes:
                    kind = game_routes[self.path]
                    fields = {'game_start': ('size',), 'game_move': ('row', 'col', 'revision'),
                              'game_vision_move': ('row', 'col', 'revision'),
                              'game_next': ('revision',)}[kind]
                    if any(type(data.get(field)) is not int for field in fields):
                        raise ValueError('格数、格位和对局版本必须是整数')
                    if kind == 'game_start':
                        if data.get('input_source', 'click') not in ('click', 'vision'):
                            raise ValueError('未知落子方式')
                        mode = data.get('mode', 'classic')
                        if not isinstance(mode, str) or (mode, data['size']) not in WIN_LENGTHS:
                            raise ValueError('无效游戏模式或棋盘尺寸')
                        if (data.get('first', 'player') not in ('player', 'ai')
                                or data.get('mark', 'X') not in ('X', 'O')):
                            raise ValueError('无效的先后手或符号')
                    job = session.submit(kind, game_request=data)
                    return self.send(202, {'job': job, 'accepted': True})
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
    parser.add_argument('--fast-game', action='store_true')
    parser.add_argument('--preview-weights', default='')
    parser.add_argument('--preview-device', default='cpu')
    args = parser.parse_args(remove_ros_args()[1:])
    from tictactoe_gui.perception_preview import PerceptionPreview
    preview = PerceptionPreview(args.preview_weights, args.preview_device)
    session = CanvasSession(
        args.output, partial(simulation_worker, fast_game=args.fast_game, perception=preview),
        vision_available=preview.weights is not None and preview.weights.is_file(),
    )
    server = ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(session, preview))
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
