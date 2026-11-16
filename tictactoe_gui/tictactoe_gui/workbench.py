"""Loopback localization workstation; ROS ownership stays in one worker thread."""
import argparse
import copy
import json
import math
import queue
import secrets
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlparse, parse_qs


def enhance_frame(frame, query):
    """! @brief Reuse the verified Python enhancer for full frames or normalized ROIs."""
    import cv2
    import numpy as np
    from tictactoe_perception.image_enhancer import ImageEnhancer
    beta = int(query['beta'][0])
    if not -255 <= beta <= 255:
        raise ValueError('亮度偏移应在 -255..255')
    image = cv2.imdecode(np.frombuffer(frame, dtype=np.uint8), cv2.IMREAD_COLOR)
    roi = None
    if 'roi' in query:
        values = [float(value) for value in query['roi'][0].split(',')]
        if len(values) != 4 or not all(math.isfinite(v) and 0 <= v <= 1 for v in values):
            raise ValueError('ROI 必须为归一化矩形')
        x, y, w, h = values
        if w <= 0 or h <= 0 or x+w > 1.000001 or y+h > 1.000001:
            raise ValueError('ROI 超出图像')
        height, width = image.shape[:2]
        x1, y1 = int(x*width), int(y*height)
        x2, y2 = min(width, int((x+w)*width)), min(height, int((y+h)*height))
        if x2 <= x1 or y2 <= y1:
            raise ValueError('ROI 小于一个像素')
        roi = (x1, y1, x2-x1, y2-y1)
    mode = query.get('mode', ['brightness'])[0]
    if mode == 'ink':
        try:
            strength = float(query.get('strength', ['50'])[0])
            tolerance = float(query.get('tolerance', ['20'])[0])
        except ValueError:
            raise ValueError('无效的笔迹增强参数')
        enhanced = ImageEnhancer().enhance_ink(image, strength, tolerance, roi)
    elif mode == 'brightness':
        enhanced = ImageEnhancer().enhance(image, beta, roi)
    else:
        raise ValueError('未知图像增强模式')
    ok, encoded = cv2.imencode('.jpg', enhanced, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise ValueError('图像增强失败')
    return encoded.tobytes()


def validate_command(data, environment='sim'):
    """! @brief Validate browser requests before they reach the ROS queue."""
    kind = data.get('kind')
    if kind not in ('jog', 'preset', 'return', 'execute', 'record', 'delete', 'camera', 'reset', 'draw', 'canvas'):
        raise ValueError('未知操作')
    result = {'kind': kind}
    if kind == 'jog':
        axis = data.get('axis')
        distance = data.get('distance')
        if axis not in ('x', 'y', 'z'):
            raise ValueError('方向必须是 x / y / z')
        limit = .05 if environment == 'real' and axis in ('x', 'y') else .02
        if (isinstance(distance, bool) or not isinstance(distance, (int, float))
                or not math.isfinite(distance) or not 0 < abs(distance) <= limit):
            raise ValueError(f'单步距离必须在 0–{limit*1000:g} mm 内')
        result.update(axis=axis, distance=float(distance))
    if kind in ('jog', 'preset', 'return', 'reset', 'draw', 'canvas'):
        speed = data.get('speed', .1)
        if (isinstance(speed, bool) or not isinstance(speed, (int, float))
                or not math.isfinite(speed) or not .01 <= speed <= (.1 if environment == 'real' else .3)):
            raise ValueError('速度缩放超出当前环境范围')
        result['speed'] = float(speed)
    if kind == 'canvas':
        from tictactoe_gui.geometry import validate_strokes
        if environment != 'real':
            raise ValueError('此画布使用真机标定；仿真保留原画布入口')
        result['strokes'] = validate_strokes(data.get('strokes'))
    if kind == 'draw':
        if environment != 'real':
            raise ValueError('此绘图入口只使用真机标定配置；仿真请使用原画布入口')
        shape = data.get('shape')
        size = data.get('size', .012)
        center = data.get('center', [.5, .5])
        if shape not in ('x', 'o', 'grid', 'smile', 'docker', 'chair'):
            raise ValueError('未知的已校验绘图素材')
        if (isinstance(size, bool) or not isinstance(size, (int, float))
                or not math.isfinite(size) or not .008 <= size <= .06):
            raise ValueError('图形尺寸必须在 8–60 mm 内')
        if (not isinstance(center, (list, tuple)) or len(center) != 2
                or any(isinstance(v, bool) or not isinstance(v, (int, float))
                       or not math.isfinite(v) or not 0 <= v <= 1 for v in center)):
            raise ValueError('图形中心必须在画布范围 [0, 1] 内')
        if result['speed'] > .1:
            raise ValueError('真机绘图速度缩放上限为 10%')
        skip = data.get('skip_strokes', 0)
        if (isinstance(skip, bool) or not isinstance(skip, int) or not 0 <= skip <= 255
                or (skip and shape not in ('smile', 'docker', 'chair'))):
            raise ValueError('仅素材续画可指定有效的已完成笔画数')
        result.update(shape=shape, size=float(size), center=list(center), skip_strokes=skip)
    if kind in ('preset', 'record', 'return', 'delete'):
        name = data.get('name')
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise ValueError('记录名称必须为 1–80 个字符')
        result['name'] = name.strip()
        if kind == 'preset' and name not in ('zero', 'clear', 'clear2'):
            raise ValueError('未知预设位置')
        if kind == 'record':
            if not isinstance(data.get('overwrite', False), bool):
                raise ValueError('overwrite 必须为布尔值')
            result['overwrite'] = data.get('overwrite', False)
    if kind == 'camera':
        topic = data.get('topic')
        if not isinstance(topic, str) or not topic.startswith('/') or len(topic) > 256:
            raise ValueError('无效相机 topic')
        result['topic'] = topic
    return result


class WorkbenchSession:
    """! @brief Share immutable snapshots and a bounded command queue with HTTP."""
    def __init__(self, output, environment='sim'):
        if environment not in ('sim', 'real'):
            raise ValueError('Unknown workstation environment')
        self.environment = environment
        self.output = Path(output).expanduser().resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.jobs = queue.Queue(maxsize=1)
        self.stop = threading.Event()
        self.shutdown = threading.Event()
        self.token = secrets.token_urlsafe(24)
        self.frames = {}
        self.state = dict(state='connecting', message='正在连接仿真', busy=False,
                          environment=environment, pose=None, joints={}, fresh=False,
                          camera={}, topics=[], records={}, plan=None, comparison=None, job=0)
        self.state['storage'] = str(self.output)

    def update(self, **values):
        with self.lock:
            self.state.update(values)

    def status(self):
        with self.lock:
            return copy.deepcopy(self.state)

    def submit(self, data):
        command = validate_command(data, self.environment)
        with self.lock:
            if self.state['busy'] or self.state['state'] in ('connecting', 'offline', 'blocked', 'stopping'):
                raise RuntimeError('尚未就绪或已有操作正在进行')
            if command['kind'] == 'execute' and not self.state['plan']:
                raise RuntimeError('没有可执行的规划')
            self.stop.clear()
            command['job'] = self.state['job'] + 1
            self.state.update(busy=True, state='queued', message='操作已提交', job=command['job'])
            self.jobs.put_nowait(command)
        return command['job']

    def request_stop(self, reason='调用方请求停止', source='caller'):
        """! @brief Preserve the first stop cause until the stopped job is inspected."""
        event = None
        with self.lock:
            if self.state.get('last_stop', {}).get('job') != self.state['job']:
                event = dict(job=self.state['job'], reason=reason, source=source,
                             monotonic_s=time.monotonic())
                self.state['last_stop'] = event
            self.stop.set()
            cause = self.state.get('last_stop', {}).get('reason', reason)
            self.state.update(state='stopping', message='正在停止：'+cause)
        if event is not None:
            print('WORKBENCH_STOP '+json.dumps(event, ensure_ascii=False), flush=True)

    def frame(self, key):
        with self.lock:
            return self.frames.get(key)


def make_handler(session):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, status, data, content_type='application/json; charset=utf-8'):
            body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == '/api/status':
                return self.send(200, session.status())
            if url.path == '/api/config':
                return self.send(200, {'token': session.token, 'environment': session.environment,
                                       'canvas': session.status().get('canvas')})
            if url.path.startswith('/api/canvas/asset/'):
                from tictactoe_gui.geometry import load_illustration
                dimensions = session.status().get('canvas')
                if not dimensions:
                    return self.send(503, {'error': '画布标定尚未就绪'})
                try:
                    asset = load_illustration(url.path.rsplit('/', 1)[-1],
                                              board_width=dimensions['width_mm']/1000,
                                              board_height=dimensions['height_mm']/1000,
                                              flip=False)
                    return self.send(200, asset)
                except ValueError as error:
                    return self.send(404, {'error': str(error)})
            if url.path == '/api/frame':
                frame = session.frame('live')
                if frame and 'beta' in parse_qs(url.query):
                    try:
                        frame = enhance_frame(frame, parse_qs(url.query))
                    except ValueError as error:
                        return self.send(400, {'error': str(error)})
                return self.send(200, frame, 'image/jpeg') if frame else self.send(503, {'error': '尚无图像'})
            if url.path == '/api/snapshot':
                name = parse_qs(url.query).get('name', [''])[0]
                frame = session.frame('record:'+name)
                return self.send(200, frame, 'image/jpeg') if frame else self.send(404, {'error': '无关联截图'})
            static = {'/': ('workbench.html', 'text/html; charset=utf-8'),
                      '/canvas': ('canvas.html', 'text/html; charset=utf-8'),
                      '/canvas.js': ('canvas.js', 'text/javascript; charset=utf-8'),
                      '/canvas.css': ('canvas.css', 'text/css; charset=utf-8'),
                      '/workbench.js': ('workbench.js', 'text/javascript; charset=utf-8'),
                      '/workbench.css': ('workbench.css', 'text/css; charset=utf-8')}
            if url.path not in static:
                return self.send(404, {'error': 'Not found'})
            name, mime = static[url.path]
            self.send(200, files('tictactoe_gui').joinpath('web', name).read_bytes(), mime)

        def do_POST(self):
            expected = 'http://' + self.headers.get('Host', '')
            if (self.headers.get('X-Workbench-Token') != session.token
                    or self.headers.get('Origin', expected) != expected
                    or urlparse(expected).hostname not in ('localhost', '127.0.0.1')):
                return self.send(403, {'error': '请求来源无效'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= (512000 if self.path == '/api/canvas' else 4096):
                    raise ValueError('请求体过大或为空')
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError('请求必须为对象')
                if self.path == '/api/stop':
                    session.request_stop()
                    return self.send(202, {'accepted': True})
                if self.path == '/api/canvas':
                    return self.send(202, {'accepted': True,
                                           'job': session.submit(dict(data, kind='canvas'))})
                if self.path != '/api/command':
                    return self.send(404, {'error': 'Not found'})
                self.send(202, {'accepted': True, 'job': session.submit(data)})
            except (ValueError, TypeError) as error:
                self.send(400, {'error': str(error)})
            except (RuntimeError, queue.Full) as error:
                self.send(409, {'error': str(error)})
    return Handler


def main():
    from rclpy.utilities import remove_ros_args
    from tictactoe_gui.workbench_worker import workbench_worker
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--output', required=True)
    parser.add_argument('--environment', choices=('sim', 'real'), default='sim')
    args = parser.parse_args(remove_ros_args()[1:])
    session = WorkbenchSession(args.output, args.environment)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(session))
    def run():
        try:
            workbench_worker(session)
        except BaseException as error:
            session.update(state='offline', busy=False, message=str(error))
    thread = threading.Thread(target=run, name='workbench-ros', daemon=True)
    thread.start()
    def halt(signum, frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGINT, halt)
    signal.signal(signal.SIGTERM, halt)
    print(f'LOCALIZATION_GUI http://localhost:{args.port} OUTPUT {session.output}', flush=True)
    try:
        server.serve_forever(poll_interval=.1)
    except KeyboardInterrupt:
        pass
    finally:
        session.stop.set()
        session.shutdown.set()
        thread.join(timeout=15)
        server.server_close()
        if thread.is_alive():
            raise RuntimeError('ROS worker did not confirm shutdown')
