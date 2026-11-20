"""A failed simulator preflight must never enter a recovery motion path."""
import importlib
from pathlib import Path
from unittest.mock import Mock
import sys
import pytest


@pytest.mark.parametrize('module_name',['verify_xy_motion','verify_drawing_motion'])
def test_no_recovery_motion_after_preflight_failure(module_name,tmp_path,monkeypatch):
    script_dir = Path(__file__).resolve().parents[2] / 'tictactoe_motion' / 'test'
    monkeypatch.syspath_prepend(str(script_dir))
    module=importlib.import_module(module_name)
    harness=Mock()
    harness.preflight.side_effect=RuntimeError('Simulation not certified')
    harness.results=[]
    monkeypatch.setattr(module,'SimulationHarness',lambda p:harness)
    monkeypatch.setattr(sys,'argv',['scenario','--output',str(tmp_path)])
    with pytest.raises(SystemExit):module.main()
    harness.named.assert_not_called()
    harness.call.assert_not_called()
    harness.close.assert_called_once()
