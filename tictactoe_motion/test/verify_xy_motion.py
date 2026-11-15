"""Gazebo acceptance for a simultaneous XY line, independent FK and actual TF checks."""
import argparse
import copy
import math
import sys
from pathlib import Path
from rclpy.utilities import remove_ros_args
from simulation_support import SimulationHarness, write_report
from tictactoe_motion.cartesian_planner import orientation_error, polyline_error, xyz, interpolate_joint_segment


def measure(samples, poses):
    assert len(samples) >= 3, 'Too few trajectory observations'
    sample_poses = []
    for sample in samples:
        p = type(poses[0])()
        p.position.x, p.position.y, p.position.z = sample['xyz']
        sample_poses.append(p)
    return {'samples': len(samples),
            'max_uncovered_waypoint_m': max(polyline_error(xyz(p), sample_poses) for p in poses),
            'max_path_error_m': max(polyline_error(s['xyz'], poses) for s in samples),
            'max_z_error_m': max(abs(s['xyz'][2]-poses[0].position.z) for s in samples),
            'max_orientation_error_rad': max(orientation_error(
                type(poses[0].orientation)(x=s['xyzw'][0], y=s['xyzw'][1], z=s['xyzw'][2], w=s['xyzw'][3]),
                poses[0].orientation) for s in samples)}


def run(h, service, report):
    start = h.node.cartesian_planner.start_pose()
    h.call(service)
    h.until(lambda: not h.node.is_planning, 20)
    report['validation'] = copy.deepcopy(h.node.cartesian_planner.last_report)
    report['guard'] = h.guard()
    poses = copy.deepcopy(h.node.cartesian_planner.poses)
    fk_samples = []
    jt = h.node.planned_trajectory.joint_trajectory
    rows = [list(jt.points[0].positions)]
    for previous, point in zip(jt.points, jt.points[1:]):
        rows.extend(interpolate_joint_segment(previous, point, fraction/10) for fraction in range(1, 10))
        rows.append(list(point.positions))
    for row in rows:
        p = h.fk(dict(zip(jt.joint_names, row)))
        q = p.orientation
        fk_samples.append({'xyz': xyz(p), 'xyzw': [q.x, q.y, q.z, q.w]})
    report['planned_geometry'] = measure(fk_samples, poses)
    report['result'] = h.execute()
    report['actual_geometry'] = measure(h.samples, poses)
    for key in ('planned_geometry', 'actual_geometry'):
        assert report[key]['max_path_error_m'] < 0.0005, report[key]
        assert report[key]['max_uncovered_waypoint_m'] < 0.0005, report[key]
        assert report[key]['max_z_error_m'] < 0.0005, report[key]
        assert report[key]['max_orientation_error_rad'] < 0.003, report[key]
    assert report['result']['position_error_m'] < 0.0003, report['result']
    assert math.dist(xyz(start), xyz(poses[0])) < 1e-9
    return poses


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    options = parser.parse_args(remove_ros_args(sys.argv)[1:])
    h = SimulationHarness(options.output)
    report = {'scenario': 'clear -> XY(+1cm,+1cm) -> restore clear', 'simulation_only': True}
    clear_ready = False
    try:
        report['controllers'] = h.preflight()
        report['clear'] = h.named('clear')
        clear_ready = True
        h.record('baseline')
        h.parameters(dx=0.01, dy=0.01)
        report['xy'] = {}
        run(h, 'plan_xy', report['xy'])
        report['restore'] = h.replay('baseline')
        h.call('delete_pose')
        report['passed'] = True
    except BaseException as error:
        report.update(passed=False, error=repr(error))
        print('FAIL', repr(error), flush=True)
        if clear_ready and not h.execution.is_executing:
            try:
                report['recovery'] = h.named('clear')
            except BaseException as recovery:
                report['recovery_error'] = repr(recovery)
    finally:
        report['executions'] = h.results
        h.close()
        write_report(Path(options.output)/'xy_motion.json', report)
        print('REPORT', report.get('passed'), options.output, flush=True)
    if not report.get('passed'):
        sys.exit(1)


if __name__ == '__main__':
    main()
