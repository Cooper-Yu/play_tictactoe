"""Gazebo-only airborne X and O acceptance, returning to the clear baseline each time."""
import argparse
import sys
from pathlib import Path
from rclpy.utilities import remove_ros_args
from simulation_support import SimulationHarness, write_report
from verify_xy_motion import run


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True)
    args=p.parse_args(remove_ros_args(sys.argv)[1:])
    h=SimulationHarness(args.output)
    report={'scenario':'airborne X and O in XY at fixed Z/orientation','simulation_only':True}
    clear_ready = False
    try:
        report['controllers']=h.preflight()
        report['clear']=h.named('clear')
        clear_ready = True
        h.record('baseline')
        for shape in ['cross','circle']:
            report[shape]={}
            run(h,'plan_'+shape,report[shape])
            report[shape]['restore']=h.replay('baseline')
            print('PASS '+shape,flush=True)
        h.call('delete_pose')
        report['passed']=True
    except BaseException as error:
        report.update(passed=False,error=repr(error))
        print('FAIL',repr(error),flush=True)
        if clear_ready and not h.execution.is_executing:
            try:report['recovery']=h.named('clear')
            except BaseException as e:report['recovery_error']=repr(e)
    finally:
        report['executions']=h.results
        h.close()
        write_report(Path(args.output)/'drawing_motion.json',report)
        print('REPORT',report.get('passed'),args.output,flush=True)
    if not report.get('passed'):sys.exit(1)


if __name__=='__main__':main()
