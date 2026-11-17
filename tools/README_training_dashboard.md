# YOLO training dashboard

Run in WSL Ubuntu-22.04 from the repository:

```bash
python3 tools/training_dashboard.py --port 8770
```

Open http://localhost:8770/ in the Windows browser. Stop the server with Ctrl+C.
The server binds only to loopback and reads existing `data/training/<experiment>/`
directories; it does not launch training, modify models, or control the robot.
PyYAML is provided by the existing Ultralytics environment; no frontend download,
Node build, global installation or additional ROS package is needed.

The dashboard refreshes every two seconds while visible. It shows completed CSV
epochs, live batch progress from `training.log`, recent epoch duration, an ETA
when a matching trainer is running, losses, validation metrics, optional GPU
memory observations, image artifacts and a bounded log tail. Completed training
does not claim model readiness. Preview and label images are explicitly distinct.

For a new run, save Ultralytics output under `data/training/<name>/`, redirect
the trainer output to `training.log` there, and click Refresh experiments. Run the
trainer from that experiment directory or include its absolute path or
`name=<name>` in its process arguments so the monitor can identify it. Scripts
that hide the run identity are shown as inactive instead of inventing a live
status. The process check never kills or changes a process.

`results.csv` is authoritative for completed epoch counts. Incomplete CSV rows
are ignored and retried; final validation callbacks are not extra training
epochs. ETA is based on recent completed epoch durations and remains unavailable
until there is enough evidence. GPU memory is displayed only when the training
script supplies `epoch_observations.json` or a smoke report; it is not invented
from the whole GPU's unrelated usage. The three-epoch quality warning derives
from that run's saved prediction check.

Verify: `python3 -m unittest discover -s tools -p test_training_dashboard.py -v`.
The checks cover interrupted writes, directory traversal, post-training validation
callbacks and live batch/ETA parsing. Browser acceptance additionally checks the
actual smoke result, plot/image selection, logs, full-page scrolling and narrow
layout. No test split predictions are needed to verify this tool.
