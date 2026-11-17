"""Read-only, loopback training monitor for local Ultralytics experiment directories."""
import argparse
import csv
import io
import json
import math
import mimetypes
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import yaml

ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
ASSET_SUFFIXES = {'.png', '.jpg', '.jpeg', '.csv', '.json', '.yaml', '.log'}


def read_json(path):
    """Read a possibly in-flight report without interrupting the dashboard."""
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def read_rows(path):
    """Ignore incomplete/non-finite CSV rows while an epoch is being saved."""
    try:
        rows = csv.DictReader(io.StringIO(path.read_text()))
        result = []
        for row in rows:
            try:
                values = {k.strip(): float(v) for k, v in row.items() if k and v is not None}
                if values.get('epoch', 0) > 0 and all(math.isfinite(v) for v in values.values()) and len(values) == len(row):
                    result.append(values)
            except (TypeError, ValueError):
                continue
        return result
    except OSError:
        return []


def tail_log(path):
    """Read at most the last 64 KiB, normalizing terminal progress updates."""
    try:
        with path.open('rb') as stream:
            stream.seek(max(0, path.stat().st_size - 65536))
            return ANSI.sub('', stream.read().decode('utf-8', errors='replace')).replace('\r', '\n')
    except OSError:
        return ''


def resolve_run(root, name):
    """Limit reads to a direct child experiment directory."""
    if not name or Path(name).name != name or name in {'.', '..'}:
        raise ValueError('Invalid run name')
    path = (root / name).resolve()
    if path.parent != root.resolve() or not path.is_dir():
        raise ValueError('Unknown run')
    return path


def is_training(run):
    """Find a trainer by explicit run arguments or its experiment working directory."""
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            cmd = (proc / 'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace')
            if not ('python' in cmd or 'yolo ' in cmd) or 'training_dashboard' in cmd:
                continue
            if not any(token in cmd for token in ('train_smoke.py', ' train ', 'train_yolo', 'train.py')):
                continue
            if str(run) in cmd or f'name={run.name}' in cmd or (proc / 'cwd').resolve() == run:
                return True
        except (OSError, PermissionError):
            continue
    return False


def snapshot(run):
    """Combine epoch metrics, live log progress and optional smoke instrumentation."""
    try:
        config = yaml.safe_load((run / 'args.yaml').read_text()) or {}
    except (OSError, yaml.YAMLError):
        config = read_json(run / 'requested_config.json')
    rows = read_rows(run / 'results.csv')
    report = read_json(run / 'smoke_report.json')
    log = tail_log(run / 'training.log')
    active = is_training(run)
    total = int(config.get('epochs') or 0)
    completed = int(rows[-1]['epoch']) if rows else 0
    finished = not active and (report.get('status') == 'completed' or bool(re.search(r'\d+ epochs completed', log)))
    failed = not active and ('Traceback (most recent call last)' in log or 'CUDA out of memory' in log) and not finished
    status = 'running' if active else 'completed' if finished else 'failed' if failed else 'inactive'
    # A final validation callback can report epoch+1; CSV is authoritative for completed training epochs.
    matches = list(re.finditer(r'(\d+)/(\d+)\s+[\d.]+G[^\n]*?\b(\d+)/(\d+)\b', log))
    batch = None
    if active and matches:
        m = matches[-1]
        if int(m[1]) > completed:
            batch = {'epoch': int(m[1]), 'done': int(m[3]), 'total': int(m[4])}
    durations = [rows[i]['time'] - rows[i-1]['time'] for i in range(1, len(rows)) if 'time' in rows[i] and 'time' in rows[i-1]]
    epoch_seconds = sum(durations[-5:]) / len(durations[-5:]) if durations else None
    remaining = max(0, total-completed-(batch['done']/batch['total'] if batch else 0))
    assets = sorted(str(p.relative_to(run)) for p in run.glob('*.jpg'))
    assets += sorted(str(p.relative_to(run)) for p in run.glob('*.png'))
    values = report.get('validation_metrics') or (rows[-1] if rows else {})
    observations = report.get('epochs') or []
    if not observations:
        observations = read_json(run/'epoch_observations.json') or []
    return {'run':run.name, 'path':str(run), 'status':status, 'epoch':completed,
            'total_epochs':total, 'batch':batch, 'rows':rows, 'config':config,
            'epoch_seconds':epoch_seconds, 'eta_seconds':epoch_seconds*remaining if active and epoch_seconds else None,
            'elapsed_training_seconds':rows[-1].get('time') if rows else None,
            'wall_seconds':report.get('total_wall_seconds'), 'metrics':values,
            'peak_reserved_gib':max((e.get('peak_reserved_gib',0) for e in observations),default=None),
            'test_evaluated':report.get('test_split_evaluated'), 'assets':assets,
            'preview_warning':bool(report.get('validation_prediction_check')),
            'log':'\n'.join([line for line in log.splitlines() if line.strip()][-65:]),
            'updated_at':time.time()}


def handler_for(root):
    """Create a read-only HTTP handler bound to the configured output root."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urlsplit(self.path)
            q = parse_qs(url.query)
            try:
                if url.path == '/':
                    return self.send_file(Path(__file__).parent/'training_dashboard/index.html')
                if url.path == '/api/runs':
                    runs = sorted((p for p in root.iterdir() if p.is_dir() and ((p/'args.yaml').exists() or (p/'requested_config.json').exists())), key=lambda p:p.stat().st_mtime, reverse=True)
                    return self.send_json({'runs':[p.name for p in runs]})
                run = resolve_run(root, q.get('run',[''])[0])
                if url.path == '/api/status':
                    return self.send_json(snapshot(run))
                if url.path == '/asset':
                    asset=(run/unquote(q.get('file',[''])[0])).resolve()
                    if not asset.is_relative_to(run) or asset.suffix.lower() not in ASSET_SUFFIXES:
                        raise ValueError('Invalid asset')
                    return self.send_file(asset)
                self.send_error(404)
            except (OSError, ValueError, TypeError):
                self.send_error(404, 'Requested training output unavailable')

        def send_json(self, value):
            data=json.dumps(value,ensure_ascii=False,allow_nan=False).encode()
            self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)

        def send_file(self,path):
            data=path.read_bytes()
            self.send_response(200);self.send_header('Content-Type',mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
            self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)

        def log_message(self, *_):
            pass
    return Handler


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]/'data/training')
    parser.add_argument('--port',type=int,default=8770)
    args=parser.parse_args()
    if not args.root.is_dir():
        parser.error('Training output root does not exist')
    print(f'Training dashboard: http://localhost:{args.port}/',flush=True)
    ThreadingHTTPServer(('127.0.0.1',args.port),handler_for(args.root.resolve())).serve_forever()
