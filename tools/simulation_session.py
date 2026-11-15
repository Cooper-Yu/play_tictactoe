"""Run one owned Piper Gazebo/MoveIt session and clean all versioned descendants."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import uuid


def simulator_processes(proc_root=Path('/proc')):
    """! @brief Include versioned Gazebo binaries, exclude zombies and shell wrappers."""
    rows = []
    for directory in proc_root.iterdir():
        if not directory.name.isdigit():
            continue
        try:
            name = (directory/'comm').read_text().strip()
            if not name.startswith(('gzclient', 'gzserver')):
                continue
            if not (directory/'exe').resolve().name.startswith(('gzclient', 'gzserver')):
                continue
            if (directory/'status').read_text().split('State:', 1)[1].lstrip().startswith('Z'):
                continue
            rows.append((int(directory.name), name))
        except (OSError, IndexError):
            pass
    return rows


def owned_processes(tag):
    result = []
    marker = ('PLAY_TICTACTOE_SESSION='+tag).encode()
    for directory in Path('/proc').iterdir():
        if not directory.name.isdigit() or int(directory.name) == os.getpid():
            continue
        try:
            if marker in (directory/'environ').read_bytes().split(b'\x00'):
                result.append(int(directory.name))
        except OSError:
            pass
    return result


def terminate_owned(tag):
    """! @brief Stop only processes still carrying this session's unguessable ownership tag."""
    for action, pause in ((signal.SIGINT, 3), (signal.SIGTERM, 2), (signal.SIGKILL, .2)):
        for pid in owned_processes(tag):
            try:
                os.kill(pid, action)
            except ProcessLookupError:
                pass
        time.sleep(pause)
    return owned_processes(tag)


def disable_shadows(env):
    """! @brief Apply a reversible visual-only profile to this session's Gazebo master."""
    try:
        result = subprocess.run(
            ['gz', 'topic', '-p', '/gazebo/default/scene', '-m',
             'name: "default" shadows: false'], env=env, capture_output=True,
            text=True, timeout=2)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--domain', type=int, default=187)
    parser.add_argument('--master-port', type=int, default=11605)
    parser.add_argument('--render-threads', type=int, choices=(1, 2, 4), default=2)
    parser.add_argument('--duration', type=float, default=900.)
    parser.add_argument('--with-moveit', action='store_true')
    parser.add_argument('--keep-shadows', action='store_true')
    parser.add_argument('--state-dir', required=True)
    args = parser.parse_args()
    if not 0 <= args.domain <= 232 or not 1024 <= args.master_port <= 65535 or not 0 < args.duration <= 3600:
        parser.error('Invalid domain, port or bounded duration')
    root = Path(args.state_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock = (Path.home()/'.ros/play_tictactoe_sim.lock')
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open('w') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Another managed simulation session already owns the lock')
        existing = simulator_processes()
        if existing:
            raise SystemExit(f'Existing Gazebo process(es); refusing a duplicate session: {existing}')
        tag = uuid.uuid4().hex
        env = dict(os.environ, ROS_DOMAIN_ID=str(args.domain), ROS_LOCALHOST_ONLY='1',
                   GAZEBO_MASTER_URI=f'http://127.0.0.1:{args.master_port}',
                   LIBGL_ALWAYS_SOFTWARE='1', LP_NUM_THREADS=str(args.render_threads),
                   OMP_NUM_THREADS='1', QT_X11_NO_MITSHM='1', PLAY_TICTACTOE_SESSION=tag)
        commands = [('gazebo', ['ros2', 'launch', 'piper_gazebo', 'piper_gazebo.launch.py'])]
        if args.with_moveit:
            commands.append(('moveit', ['ros2', 'launch', 'piper_with_gripper_moveit', 'move_group_sim.launch.py']))
        state = {'tag': tag, 'domain': args.domain, 'port': args.master_port, 'pids': [],
                 'render_threads': args.render_threads, 'state_dir': str(root)}
        stopped = False
        def stop(*_):
            nonlocal stopped
            stopped = True
        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)
        children = []
        logs = []
        try:
            for name, command in commands:
                log = (root/(name+'.log')).open('w')
                logs.append(log)
                child = subprocess.Popen(command, env=env, stdout=log,
                                         stderr=subprocess.STDOUT, start_new_session=True)
                children.append(child)
                state['pids'].append(child.pid)
            (root/'session.json').write_text(json.dumps(state, indent=2))
            print('SIMULATION_SESSION_STARTED '+json.dumps(state), flush=True)
            started = time.monotonic()
            deadline = started+args.duration
            display_applied = args.keep_shadows
            next_display_attempt = started+8.0
            while not stopped and time.monotonic() < deadline and not (root/'STOP').exists():
                if any(child.poll() is not None for child in children):
                    raise RuntimeError('Gazebo or MoveIt launch exited; inspect session logs')
                if not display_applied and time.monotonic() >= next_display_attempt:
                    display_applied = disable_shadows(env)
                    next_display_attempt = time.monotonic()+3.0
                    state['shadows_disabled'] = display_applied
                    (root/'session.json').write_text(json.dumps(state, indent=2))
                    if display_applied:
                        print('VISUAL_PROFILE_APPLIED shadows=false', flush=True)
                time.sleep(.2)
        finally:
            remaining = terminate_owned(tag)
            for child in children:
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
            for log in logs:
                log.close()
            state.update(remaining_pids=remaining, stopped=True)
            (root/'session.json').write_text(json.dumps(state, indent=2))
            print('SIMULATION_SESSION_STOPPED '+json.dumps({'remaining_pids': remaining}), flush=True)
            if remaining:
                raise RuntimeError('Owned simulation processes remain')


if __name__ == '__main__':
    main()
