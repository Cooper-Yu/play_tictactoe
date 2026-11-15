"""Check version-suffixed simulator discovery and duplicate-start rejection."""
import importlib.util
from pathlib import Path
import subprocess
import sys

MODULE = Path(__file__).resolve().parents[2]/'tools/simulation_session.py'
spec = importlib.util.spec_from_file_location('sim_session', MODULE)
session = importlib.util.module_from_spec(spec)
spec.loader.exec_module(session)


def test_versioned_processes_exclude_wrappers_and_zombies(tmp_path):
    for pid, name, binary, status in [(1,'gzclient-11.10.','gzclient-11.10.2','S'),
                                      (2,'gzclient','dash','S'),
                                      (3,'gzserver','gzserver','Z'),
                                      (4,'gzserver','gzserver','S')]:
        root=tmp_path/str(pid);root.mkdir()
        (root/'comm').write_text(name)
        (root/'exe').symlink_to('/usr/bin/'+binary)
        (root/'status').write_text('State: '+status+' (state)')
    assert sorted(session.simulator_processes(tmp_path))==[(1,'gzclient-11.10.'),(4,'gzserver')]


def test_actual_local_duplicate_refused_without_launch(tmp_path):
    # Applicable only when the authorized local Gazebo fixture is already active.
    if not session.simulator_processes():
        import pytest
        pytest.skip('No existing local Gazebo fixture')
    result=subprocess.run([sys.executable,str(MODULE),'--state-dir',str(tmp_path)],
                          capture_output=True,text=True,timeout=5)
    assert result.returncode != 0
    assert 'refusing a duplicate' in result.stderr
    assert not (tmp_path/'session.json').exists()


def test_visual_profile_targets_only_supplied_master(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    call=Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(session.subprocess,'run',call)
    environment={'GAZEBO_MASTER_URI':'http://127.0.0.1:11605'}
    assert session.disable_shadows(environment)
    assert call.call_args.kwargs['env']==environment
    assert call.call_args.args[0][-1]=='name: "default" shadows: false'
    call.return_value.returncode=1
    assert not session.disable_shadows(environment)


def test_readiness_repairs_only_known_stranded_states(monkeypatch):
    monkeypatch.syspath_prepend(str(MODULE.parent))
    import controller_readiness as readiness
    assert readiness.arm_operation('unconfigured',False) is None
    assert readiness.arm_operation('unconfigured',True)=='configure'
    assert readiness.arm_operation('inactive',True)=='activate'
    for state in ['active','finalized',None]:assert readiness.arm_operation(state,True) is None
