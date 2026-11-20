# Real-robot cloud GUI assets

- xo_real.pt: project-trained YOLO26n X/O detector, mixed real/simulation fine-tuning.
- SHA-256: 83f4f856101527884a0309f7c6307cb1b8e25de083cae292e02c27cb691b3ef8.
- Inference: 640 px, confidence 0.25, one-to-many branch with NMS IoU 0.70.
- config/grid_points_real.json records the four internal 3x3 grid intersections in the
  424x240 camera image. Verify or replace this file after any camera/board movement.
- These assets do not authorize robot movement.

Cloud startup, after MoveGroup is running:

    source ~/ros2_ws/install/setup.bash
    ros2 launch tictactoe_gui robot_games_real.launch.py public_url:="$(webpage_address)"

Open the webpage URL for calibration, append canvas for free drawing, or append
game/ for the game UI. All inference and coordination execute in the cloud.
No separate local GUI process is required.
