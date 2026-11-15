# Camera enhancement demo

ImageRaw subscribes to a ROS `sensor_msgs/msg/Image` topic and converts it with
cv_bridge to a BGR uint8 NumPy array. ImageEnhancer adjusts brightness in the
selected ROI. The comparison window shows the full original image on the left
and the enhanced region, enlarged with its aspect ratio preserved, on the right.

## Build and run

```bash
cd ~/ros2_ws
colcon build --packages-select tictactoe_perception --symlink-install
source install/setup.bash
# Default environment: real; topic /camera/D435/color/image_raw.
ros2 launch tictactoe_perception enhancement_demo.launch.py
# Local Gazebo: /camera1/image_raw, simulated /clock.
ros2 launch tictactoe_perception enhancement_demo.launch.py environment:=sim
# Override topic and initial brightness without editing YAML.
ros2 launch tictactoe_perception enhancement_demo.launch.py \
  camera_topic:=/custom_rgb initial_brightness_beta:=22
```

The launch file loads `config/common.yaml`, then `real.yaml` or `sim.yaml`, then
explicit launch overrides. The camera source must already be running; this
package does not start a sensor driver, simulation or robot movement. Use the same
ROS domain as the image publisher. For a bag, select the matching topic and
clock setup; the sim profile expects `/clock` from Gazebo or `ros2 bag play --clock`.

| Parameter | Meaning |
| --- | --- |
| `camera_topic` | Uncompressed ROS Image topic |
| `camera_reliability` | `best_effort` (default) or `reliable` |
| `camera_queue_depth` | Positive subscription queue depth |
| `initial_brightness_beta` | Initial offset in [-255, 255]; 0 leaves brightness unchanged |
| `window_name` | OpenCV window title |
| `log_images` | Print frame metadata when true; default false |
| `use_sim_time` | True in sim, false in real |

These are startup settings; restart the node to apply YAML changes. Drag the
Brightness slider at runtime to change beta; slider 255 corresponds to beta 0.
Drag the left image to select a live ROI. Invalid/zero-area selections retain the
previous ROI, and the default is the whole image. Brightness adjustment does not
recover missing image detail or prove pen/board contact.

The default QoS accepts best-effort and reliable camera publishers. If you select
`reliable`, the publisher must offer reliable delivery. Topic remapping is also
available through normal ROS arguments; bare `ros2 run` needs explicit parameter
files to use the YAML profiles. Rebuild after adding new launch/config files.
No record files or robot pose data belong in this package's config directory.
