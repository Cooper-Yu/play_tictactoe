# Real-robot cloud GUI assets

- xo_real.pt: project-trained YOLO26n X/O detector, mixed real/simulation fine-tuning.
- SHA-256: 83f4f856101527884a0309f7c6307cb1b8e25de083cae292e02c27cb691b3ef8.
- Inference: 640 px, confidence 0.25, one-to-many branch with NMS IoU 0.70.
- config/grid_points_real.json records the four internal 3x3 grid intersections in the
  424x240 camera image. Verify or replace this file after any camera/board movement.
- These assets do not authorize robot movement.

Cloud setup (isolated from the system Python; existing Torch/OpenCV are reused):

    cd ~/ros2_ws/src/play_tictactoe
    python3 -m pip install --target .cloud-python --no-deps -r tictactoe_gui/config/cloud-requirements.txt

Cloud startup, after MoveGroup is running:

    source ~/ros2_ws/install/setup.bash
    ros2 launch tictactoe_gui robot_games_real.launch.py public_url:="$(webpage_address)"

Open the webpage URL for calibration, append canvas for free drawing, or append
game/ for the game UI. All inference and coordination execute in the cloud.
No separate local GUI process is required.

## Native 9x9 small-mark detector (2026-11-21)

- xo_real_nine.pt: YOLO26n, initialized from xo_real.pt, 40 epochs on RTX 3090.
- SHA-256: 0f9b3d21602debf1772f743ac5073e8e84335750797aee49607c63ad8760d9da.
- Sources: 12 physical capture episodes, five photos each (0/2/4/6/8 marks).
  Episodes 00-07 train, 08-09 validation, 10-11 independent test. Failed attempts excluded.
- Native four-zone crops match the deployed inference path; visible padding neighbors
  are labeled, partially clipped crops excluded. New training crops repeated twice
  alongside 280 existing training entries; repetition is not additional independent data.
- Confidence .25, NMS IoU .70, imgsz640, end2end=False, no image enhancement.
- Selection: best and last tied at 8/10 exact validation frames, TP37/FN3/FP0;
  last frozen before independent testing. Test: 10/10 exact, TP40/FN0/FP0.
  Ten frames represent only two physical layouts and include correlated stages.
- Original 3x3 detector remains unchanged. Real game uses the optional --nine-weights
  only for size9, including camera and rectified detection previews.
- Labels were visually reviewed against staged photos and magnified mark crops;
  executed geometry provided projected box drafts. Native images remain 424x240.
- Raw archive SHA-256: 0f08085159b21236edaf5323bafa6d1b89dcd3557d50afc822d0be7f5e2dbbbd.
- Reproducibility tools: tools/prepare_real_nine_dataset.py and tools/evaluate_real_nine.py.
  Local data/training/yolo26n_real_nine_v1_20261121 retains args, curves, and checkpoints.
- These offline results are not a guarantee for dense boards, changed lighting,
  camera movement, arm occlusion, or every live game. Live game validation is separate.

## Zero-observation candidate for explicit live comparison (2026-11-22)

- xo_real_nine_zero_candidate.pt SHA256: 1efa1bca908cb9efb8c2d1d10bf8676eb8026f44ed21fbfe7bcf179fab25b036.
- 40-epoch fine-tune of deployed 9x9 detector; 12 real zero-pose capture layouts, grouped 8/2/2.
- New held-out reviewed cells: 24TP/0FN/0FP on 10 correlated frames from two layouts; 16 unreadable cell observations excluded. This is not full-board accuracy.
- Experimental full-frame historical 3x3 regression: 35/45 exact versus current 3x3 model 39/45. Not a default replacement for either production model.
- Included for user-authorized cloud game testing; launch with an explicit weights path. Existing xo_real.pt and xo_real_nine.pt unchanged.
