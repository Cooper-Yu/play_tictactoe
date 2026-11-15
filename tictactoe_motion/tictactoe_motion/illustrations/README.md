# Drawing materials

- `chair.json` / `chair.svg`: approximate centerline reconstruction of the official The Construct chair, with source-image gap repairs. Source: https://www.theconstruct.ai/wp-content/uploads/2020/09/Logo-The-Construct-512x512-1.png . Background, frame and decorative node disks are omitted. Some original paths are retraced to reduce pen lifts.
- `docker.json` / `docker.svg`: outline of the official Docker mark (one body, nine container outlines), sampled from https://www.docker.com/app/uploads/2026/05/docker-mark-deep-blue.svg . No area fill.
- `smile.json` / `smile.svg`: reconstructed outer circle, elliptical eyes and elliptical smile, based on the user reference. Two nearby paths per feature create thicker strokes without pressure control.

JSON points use normalized source coordinates, plus an explicit physical aspect ratio. SVG is a resolution-independent preview of the same pen paths; it does not restore details missing from a raster source. Brand source/ownership remains with the respective owners.

`IllustrationDrawing(actions).draw('chair', center=(.5,.5), width=.06, rotation=180)` uses a metric width in meters, uniform scaling and rotation in degrees. The 180-degree value is a simulation-view presentation choice, not camera calibration. `strokes(...)` previews and validates without movement. `export_svg(name, path)` exports an asset.

All batches are checked against the board before any movement. Acute reversals and long paths are separated into lifted strokes. Skipping an identical adjacent stroke endpoint avoids requesting a zero-length hover transfer. Real hardware still requires calibrated board/TCP and its own motion verification; these assets do not establish clearance or contact.

Simulation check: source Humble and the workspace overlay, keep the existing simulator and MoveIt running in their own domain, and run `python3 tictactoe_motion/test/verify_illustration.py --shape chair --output /tmp/your-owned-run --ros-args --params-file tictactoe_motion/config/common.yaml --params-file tictactoe_motion/config/sim.yaml --params-file tictactoe_motion/config/board_demo_sim.yaml -p poses_file:=/tmp/your-owned-run/poses_sim.json -p state_log_period:=0.0 -p cartesian_step:=0.0003`. Replace chair with docker or smile. The harness is simulation-only, verifies execution, writes evidence, virtually resets ink, and returns to zero on normal success. Cancellation does not trigger recovery motion.
