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


## Expansion and grouped split

The approved pilot stays unchanged. The extension creates 900 new camera images
using a different seed, IDs 0100–0999 and 180 base scenes with five views each.
Additional X off-center crossings/jitter and O multiple gaps stay within the
approved positive rules. Slight camera pose changes, native camera Gaussian noise,
material colors and pen widths vary; these are capture conditions, not post-split
training augmentation. No real bag or robot motion is involved.

Use the same isolated environment described above:

```bash
timeout --signal=INT --kill-after=15 1800 python3 tools/generate_xo_sim_batch.py \
  --output data/datasets/xo_sim_extra_900_v1 --count 900 --seed 2026111800 \
  --start-index 100 --views-per-scene 5 --expanded
python3 tools/audit_xo_sim_batch.py data/datasets/xo_sim_extra_900_v1 \
  --expected 900 --no-review
python3 tools/test_xo_dataset_split.py
python3 tools/prepare_xo_dataset.py \
  --pilot data/datasets/xo_sim_review_100_v1 \
  --extra data/datasets/xo_sim_extra_900_v1 \
  --output data/datasets/xo_sim_v1 --seed 20261117
python3 tools/verify_xo_dataset.py data/datasets/xo_sim_v1 \
  --pilot data/datasets/xo_sim_review_100_v1
```

The preparer fingerprints actual mesh centerlines independently of pen width and
material, so repeated blank/grid layouts from different scene IDs merge into one
group. It checks that every five-view source scene has one geometry fingerprint.
All splits preserve complete groups; a seeded search balances label-variant
counts without model predictions or performance feedback. The target is exactly
700/150/150 images and 140/30/30 background images. Test samples are frozen after
this split, not used for later tuning. These tools never train a model.

`split_audit.json` records allocation and source-file preservation. The separate
verifier rereads all saved image/label/annotation pairs, validates YOLO bounds and
class IDs, checks image uniqueness and both geometry/source-scene disjointness,
and compares the pilot image and label bytes against the approved source.

Use the local HTTP review entry rather than opening HTML in Codex's code viewer.
The 1000-image gallery is paginated at 20 images per page. Only raw PNGs belong in
training; previews contain visible annotations and must not be used as inputs.


### Verified v1 result (2026-11-18)

1000 frames, 270 geometry groups (280 original scene IDs), 2005 X / 1973 O.
Train: 700 frames, 184 groups, 1448 X / 1401 O.
Validation: 150 frames, 42 groups, 263 X / 271 O.
Test: 150 frames, 44 groups, 294 X / 301 O.
Both geometry and original-scene cross-split overlap are zero. The approved
100 image/label pairs are byte-identical. Independent file verification passed.
The capture server had a legacy boost self-join abort during final teardown
after all frames were saved; owned processes were fully cleaned. Graceful
Classic shutdown is not certified by this data-generation run.
