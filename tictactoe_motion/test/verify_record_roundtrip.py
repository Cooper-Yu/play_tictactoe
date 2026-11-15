"""Gazebo acceptance: clear -> X+3cm -> record B -> zero -> replay B -> clear."""

import argparse
import json
import sys
from pathlib import Path

from rclpy.utilities import remove_ros_args
from simulation_support import SimulationHarness, write_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    options = parser.parse_args(remove_ros_args(sys.argv)[1:])
    output = Path(options.output).expanduser().resolve()
    harness = SimulationHarness(output)
    report = {'scenario': 'clear -> X+3cm -> B -> zero -> B -> clear', 'simulation_only': True}
    clear_ready = False
    try:
        report['controllers'] = harness.preflight()
        report['clear'] = harness.named('clear')
        clear_ready = True
        harness.parameters(axis='x', distance=0.03)
        harness.call('plan_step')
        harness.until(lambda: not harness.node.is_planning)
        report['step_guard'] = harness.guard()
        report['step'] = harness.execute()
        assert report['step']['position_error_m'] < 0.0003
        report['B'] = harness.record('B')
        print('PASS clear, X+3cm and B saved', flush=True)
        report['zero'] = harness.named('zero')
        report['B_replay'] = harness.replay('B')
        print('PASS zero and B replay: ' + json.dumps(report['B_replay']), flush=True)
        report['restore_clear'] = harness.named('clear')
        clear_ready = False
        harness.call('delete_pose')
        assert json.loads(harness.recording.recorder.poses_file.read_text()) == {}
        report['passed'] = True
    except BaseException as error:
        report['passed'] = False
        report['error'] = repr(error)
        if clear_ready and not harness.execution.is_executing:
            try:
                report['recovery_clear'] = harness.named('clear')
            except BaseException as recovery_error:
                report['recovery_error'] = repr(recovery_error)
        print('FAIL ' + repr(error), flush=True)
    finally:
        report['executions'] = harness.results
        harness.close()
        write_report(output / 'record_roundtrip.json', report)
        print('REPORT ' + str(output / 'record_roundtrip.json'), flush=True)
    if not report.get('passed'):
        sys.exit(1)


if __name__ == '__main__':
    main()