"""Verify the loaded Classic world poses before using extracted base-frame geometry."""
import math
import os
from pathlib import Path
import subprocess


def verify_scene(profile):
    domain=('ROS_DOMAIN_ID='+os.environ['ROS_DOMAIN_ID']).encode()
    servers=[]
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():continue
        try:
            exe=(proc/'exe').resolve()
            if exe.name.startswith('gzserver') and domain in (proc/'environ').read_bytes().split(b'\0'):
                servers.append((proc,exe))
        except OSError:pass
    assert len(servers)==1,('Expected exactly one server in this ROS domain',len(servers))
    proc,exe=servers[0];env=os.environ.copy()
    for part in (proc/'environ').read_bytes().split(b'\0'):
        if part.startswith((b'LD_LIBRARY_PATH=',b'GAZEBO_MASTER_URI=')):
            key,value=part.decode().split('=',1);env[key]=value
    binaries=list(exe.parent.glob('gz-11*'));binary=binaries[0] if len(binaries)==1 else exe.parent/'gz'
    poses={}
    for model,expected in [('board',profile['board_world_pose']),('piper',profile['base_world_pose_required'])]:
        response=subprocess.run([str(binary),'model','-m',model,'-p'],env=env,capture_output=True,text=True,timeout=8)
        actual=[float(v) for v in response.stdout.strip().split()]
        assert response.returncode==0 and len(actual)==6,(model,response.stderr)
        assert all(math.isfinite(v) and abs(v-e)<1e-6 for v,e in zip(actual,expected)),(model,actual,expected)
        poses[model]=actual
    return poses
