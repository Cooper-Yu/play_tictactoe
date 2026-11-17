# X/O simulation review capture

This collector creates camera-rendered training candidates; it does not move a robot.
The first accepted capture run on 2026-11-17 produced 100 unique 848×480 PNGs:
80 containing 210 X + 213 O instances, 20 background images. All are `review_unsplit`.
No training has run. Dataset files are excluded by the existing `/data/` Git rule.

## Run in Ubuntu-22.04

Use a WSL-side Bash script. Source `/opt/ros/humble/setup.bash`, then
`/home/cooper/final_project_1063805/support/environment.bash` and
`/home/cooper/final_project_1063805/install/setup.bash` before `set -u`.
Set `ROS_DOMAIN_ID=191`, `ROS_LOCALHOST_ONLY=1`,
`GAZEBO_MASTER_URI=http://127.0.0.1:11619`, `LIBGL_ALWAYS_SOFTWARE=1`,
`LP_NUM_THREADS=4`, and `OMP_NUM_THREADS=1`.

```bash
timeout --signal=INT --kill-after=15 600 python3 tools/generate_xo_sim_batch.py \
  --output data/datasets/NEW_REVIEW_DIRECTORY --count 100
python3 tools/audit_xo_sim_batch.py data/datasets/NEW_REVIEW_DIRECTORY
```

An existing output directory or existing Gazebo server causes refusal.
The collector owns one tagged headless Classic server and always terminates its
owned processes in `finally`; camera, board and direct ink rendering are the only
active scene components. Course world/model files remain unchanged.

## Label and image checks

Meshes are 3D ribbons with rounded joins, projected using the received CameraInfo
and camera world pose. Labels include pen width and a rasterization margin; raw
images have no boxes. The auditor checks matching files, hashes, normalized labels,
projected box agreement, visible colored ink and edge fit, plus simulator cleanup.
Review `review/index.html`, full-resolution originals and contact sheets manually.
This is a structurally checked pilot, not proof of model accuracy or real transfer.

The first batch covers X straight/curved/gap/unequal/retrace, O circle/ellipse/gap/
handdrawn/retrace, blank/grid/triangle/square/V/slash backgrounds, size, mild rotation,
viewpoint, color and pen-width variations. It does not yet cover hands/robot occlusion,
realistic lighting variation, camera blur, cropped symbols or all approved edge cases.
Split by scene before later augmentation; keep real bag test isolation.

## Verified repairs

The ROS camera publishes `/xo_camera/xo_camera/image_raw` and matching camera_info.
An initial incorrect subscription yielded no images and was cleaned.
Bare COLLADA/SDF unlit material colors rendered white; these 100 monochrome debug
frames are excluded in a separate directory. A namespaced XML serialization briefly
failed Classic's loader; default COLLADA namespace + Lambert material + emissive SDF
was tested with three camera frames, then the corrected 100-frame batch.
The auditor handles antialiased edges using a color-to-background mixture rather
than demanding full-intensity pixels at every stroke endpoint.
