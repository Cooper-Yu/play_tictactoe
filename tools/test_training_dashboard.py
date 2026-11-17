"""Verify partial-write handling, run boundaries and progress interpretation."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import training_dashboard as dashboard


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.run=self.root/'trial';self.run.mkdir()
        (self.run/'args.yaml').write_text('epochs: 3\nbatch: 16\nimgsz: 640\n')

    def test_partial_epoch_row_ignored(self):
        path=self.run/'results.csv'
        path.write_text('epoch,time,train/box_loss\n1,10,.8\n2,14,\n')
        self.assertEqual(len(dashboard.read_rows(path)),1)

    def test_run_cannot_escape(self):
        for name in ['../trial','..','/tmp','unknown']:
            with self.assertRaises(ValueError):dashboard.resolve_run(self.root,name)
        self.assertEqual(dashboard.resolve_run(self.root,'trial'),self.run)

    @patch('training_dashboard.is_training',return_value=False)
    def test_final_eval_callback_not_a_training_epoch(self,_):
        (self.run/'results.csv').write_text('epoch,time\n1,10\n2,15\n3,20\n')
        (self.run/'smoke_report.json').write_text(json.dumps({'status':'completed','epochs':[{'epoch':4}]}))
        state=dashboard.snapshot(self.run)
        self.assertEqual(state['epoch'],3)
        self.assertEqual(state['status'],'completed')
        self.assertIsNone(state['eta_seconds'])

    @patch('training_dashboard.is_training',return_value=True)
    def test_live_batch_and_eta(self,_):
        (self.run/'results.csv').write_text('epoch,time\n1,10\n2,15\n')
        (self.run/'training.log').write_text('\x1b[K 3/3 2.48G .8 1 .01 70 640: 50% --- 22/44 10it/s')
        state=dashboard.snapshot(self.run)
        self.assertEqual(state['batch'],{'epoch':3,'done':22,'total':44})
        self.assertEqual(state['eta_seconds'],2.5)


if __name__=='__main__':unittest.main()
