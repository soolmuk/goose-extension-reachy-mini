# goose-reachy-mini

<p align="right"><strong>Language:</strong> English | <a href="README.ko.md">한국어</a></p>

A safe, high-level MCP `stdio` extension that lets goose use Reachy Mini status,
camera, attention, motion, expression, dance, and short audio tools.

This project intentionally exposes **intent/preset-level tools** instead of raw
actuator, joint angle, torque, PID, keyframe, or pixel-coordinate APIs.

## Status

Initial implementation with mock mode support and graceful fallback behavior for
hardware-specific SDK mappings.

## Requirements

- Python 3.10+
- goose with MCP stdio extension support
- Optional for hardware: Reachy Mini / Reachy SDK and a connected robot

## Installation

```bash
pip install -e .
```

For local development:

```bash
pip install -e '.[test,dev]'
```

## Run in mock mode

Mock mode is enabled by default so the MCP server can run without hardware:

```bash
REACHY_MINI_MOCK=1 goose-reachy-mini --list-tools
REACHY_MINI_MOCK=1 goose-reachy-mini
```

`goose-reachy-mini` runs an MCP server over stdio. It will wait for MCP messages
when started directly.


## Reachy Mini Control App adapter

If you are running only the Reachy Mini Control App and not connecting goose
straight to the robot SDK, run the extension with the Control App adapter. The
adapter supports camera capture and, when allowed by policy, a safe subset of
high-level motion presets through the local Control App daemon. It also supports
Control App Direction-of-Arrival speech direction and daemon audio playback.
Raw audio recording, camera-based head/person tracking, and TTS remain unavailable
in this adapter for now.

By default the extension can auto-detect a running Control App daemon at
`http://127.0.0.1:8000` / `http://localhost:8000` and use it instead of the
built-in mock client. That means the extension follows whatever the Control App
is currently using: mockup simulation, MuJoCo simulation, Lite USB robot, or
wireless robot. You do **not** need separate goose settings for simulation vs
real hardware.

For current desktop Control App builds, the dashboard exposes camera specs over
HTTP but not raw snapshots, so the adapter defaults to the SDK `MediaManager`
WebRTC/IPC paths. A minimal explicit setup is:

```bash
REACHY_MINI_CONTROL_APP=1 \
REACHY_MINI_CONTROL_APP_MEDIA_BACKEND=auto \
goose-reachy-mini
```

If you want to force mock mode even while the Control App is running, disable
auto detection:

```bash
REACHY_MINI_CONTROL_APP_AUTO=0 \
REACHY_MINI_MOCK=1 \
goose-reachy-mini
```

The adapter launches the Control App / Reachy Mini Python environment as a
short-lived helper process to read one frame from the SDK `MediaManager`, then
returns that frame to goose. If the helper cannot be auto-discovered, set:

```bash
REACHY_MINI_CONTROL_APP_PYTHON="/path/to/control-app/.venv/bin/python3"
```

`REACHY_MINI_CONTROL_APP_MEDIA_BACKEND` can be:

- `auto` — try an HTTP endpoint if configured, then WebRTC, then local IPC
- `webrtc` — read the Control App WebRTC stream, best for the desktop app
- `local` — read the daemon local IPC camera stream
- `http` — read only the configured HTTP camera endpoint

`REACHY_MINI_CONTROL_APP_CAPTURE_SOURCE` controls what “current view” means:

- `auto` — in Control App simulation/mockup simulation, capture the visible UI so
  the webcam picture-in-picture overlay is included; in real robot mode, capture
  the robot camera stream.
- `camera` — always capture the raw Reachy/Control App media stream.
- `screen` — always capture the visible macOS screen via `screencapture`.

For screen capture on macOS, the Terminal/goose host process may need Screen
Recording permission in System Settings → Privacy & Security. Optional crop:

```bash
REACHY_MINI_CONTROL_APP_SCREEN_CROP="x,y,width,height"
```

When a direct HTTP camera endpoint exists, these response shapes are supported:

- direct JPEG/PNG snapshot bytes
- MJPEG / `multipart/x-mixed-replace` stream
- JSON containing a base64 image field such as `image_base64`, `frame`, or `image`
- an HTML page with an `img`, `video`, or `source` `src` that points to the stream

Optional settings:

- `REACHY_MINI_CONTROL_APP_TIMEOUT_SECONDS=5`
- `REACHY_MINI_CONTROL_APP_SIGNALING_PORT=8443`
- `REACHY_MINI_CONTROL_APP_AUTH_TOKEN=<bearer token if required for HTTP>`

If captures still return mock images, check `reachy_get_status`; it should show
`"control_app_mode": true` and `"mock_mode": false`. It also reports the
Control App's current runtime mode via `control_app_runtime_mode` and related
fields such as `control_app_simulation_enabled`, `control_app_mockup_sim_enabled`,
`control_app_media_released`, and `control_app_camera_specs_name`.

Control App motion presets are controlled separately:

- `REACHY_MINI_CONTROL_APP_PRESET_POLICY=simulation_only` (default) allows
  `look`, `look_at_image_region`, `gesture`, `turn_body`, `reset_pose`,
  expression fallbacks, dance fallbacks, and stop commands only when the daemon
  reports `simulation` or `mockup_simulation` mode.
- `REACHY_MINI_CONTROL_APP_PRESET_POLICY=off` disables these daemon motion
  presets.
- `REACHY_MINI_CONTROL_APP_PRESET_POLICY=always` enables them in real robot modes
  too. This is an explicit opt-in; use it only when the physical setup is safe.

The Control App preset adapter posts bounded `/api/move/goto` requests to the
local daemon. Expressions and dances initially use safe fallback gesture
sequences rather than arbitrary recorded-move paths.

Control App audio/attention support uses daemon-level APIs:

- `reachy_listen_direction` reads `/api/state/doa` and maps the reported angle to
  a safe direction preset.
- `reachy_look_toward_sound` combines DoA with a single safe `look` preset.
- `reachy_track_head` supports `mode="speaker"` only; camera-based `face` and
  `person` tracking remain unavailable.
- `reachy_play_audio` uploads a short validated audio clip to
  `/api/media/sounds/upload` and plays it with `/api/media/play_sound`. Optional
  wobble uses `/api/media/wobbling/enable` and schedules a later disable.
- `reachy_listen_audio_sample` and `reachy_say_text` remain unavailable for the
  Control App adapter unless a separate TTS path is added later.

## goose configuration

See [`config.example.yaml`](config.example.yaml):

```yaml
extensions:
  reachy-mini:
    type: stdio
    cmd: goose-reachy-mini
    args: []
    timeout: 30
    envs:
      REACHY_MINI_MOCK: "1"
    available_tools:
      - reachy_get_status
      - reachy_capture_image
      - reachy_describe_current_view
      - reachy_play_expression
```

Then start goose using your goose version's extension-loading workflow, for
example:

```bash
goose session --with-extension reachy-mini
```

The exact `--with-extension` argument may be an extension name or config path
depending on goose version. Use `goose --help` / `goose session --help` to verify.

## Public tools

- `reachy_get_status`
- `reachy_get_imu`
- `reachy_idle`
- `reachy_capture_image`
- `reachy_describe_current_view`
- `reachy_look_at_image_region`
- `reachy_track_head`
- `reachy_listen_direction`
- `reachy_look_toward_sound`
- `reachy_look`
- `reachy_gesture`
- `reachy_turn_body`
- `reachy_reset_pose`
- `reachy_play_expression`
- `reachy_stop_expression`
- `reachy_dance`
- `reachy_stop_dance`
- `reachy_listen_audio_sample`
- `reachy_play_audio`
- `reachy_say_text`

## Example prompts

- 현재 보이는 게 뭐야?
- 나를 보고 밝게 인사해줘.
- 고개를 왼쪽으로 살짝 돌려줘.
- 행복한 표정을 지어줘.
- 오른쪽 위를 봐줘.
- 지금 로봇 상태와 IMU 상태를 알려줘.

## Presets

### Look directions

`center`, `left`, `right`, `up`, `down`, `front_left`, `front_right`

Intensity is limited to `small` or `medium`.

### Image regions

`center`, `upper_left`, `upper_right`, `lower_left`, `lower_right`,
`person_candidate`, `object_candidate`

Raw pixel coordinates are not exposed.

### Gestures

`yes`, `yes_understanding`, `no`, `no_firm`, `curious_tilt_left`,
`curious_tilt_right`, `look_around_short`, `small_bounce`, `shy_tilt`,
`thinking_wobble_short`, `antenna_wave`, `antenna_perk_up`, `antenna_relax`

`times` is capped by `REACHY_MINI_MAX_GESTURE_TIMES` (default `3`).

### Expressions

Supported intent names include `happy`, `excited`, `greeting`, `welcoming`,
`thinking`, `curious`, `surprised`, `sad`, `yes`, `no`, `sleepy`, `random`, and
the other enum values documented in the implementation plan. Raw recorded-move
paths are not accepted.

### Dances

`random`, `happy_wiggle`, `celebration`, `silly`, `groove`

Repeat count is capped by `REACHY_MINI_MAX_DANCE_REPEAT` (default `3`).

## Safety policy

Environment variables:

- `REACHY_MINI_MOCK=1|0`
- `REACHY_MINI_MEDIA_BACKEND=default`
- `REACHY_MINI_CONTROL_APP=1|0`
- `REACHY_MINI_CONTROL_APP_AUTO=1|0`
- `REACHY_MINI_CONTROL_APP_URL=http://127.0.0.1:8000`
- `REACHY_MINI_CONTROL_APP_CAMERA_URL=http://127.0.0.1:PORT/camera-or-stream`
- `REACHY_MINI_CONTROL_APP_CAMERA_PATH=/camera`
- `REACHY_MINI_CONTROL_APP_MEDIA_BACKEND=auto|webrtc|local|http`
- `REACHY_MINI_CONTROL_APP_CAPTURE_SOURCE=auto|camera|screen`
- `REACHY_MINI_CONTROL_APP_SCREEN_CROP=x,y,width,height`
- `REACHY_MINI_CONTROL_APP_PYTHON=/path/to/control-app/.venv/bin/python3`
- `REACHY_MINI_CONTROL_APP_DAEMON_URL=http://127.0.0.1:8000`
- `REACHY_MINI_CONTROL_APP_SIGNALING_HOST=localhost`
- `REACHY_MINI_CONTROL_APP_SIGNALING_PORT=8443`
- `REACHY_MINI_CONTROL_APP_TIMEOUT_SECONDS=5`
- `REACHY_MINI_CONTROL_APP_MOTION_TIMEOUT_SECONDS=3`
- `REACHY_MINI_CONTROL_APP_PRESET_POLICY=simulation_only|off|always`
- `REACHY_MINI_CONTROL_APP_AUTH_TOKEN=<optional bearer token>`
- `REACHY_MINI_ENABLE_MOTION=true|false`
- `REACHY_MINI_ENABLE_CAMERA=true|false`
- `REACHY_MINI_ENABLE_AUDIO=true|false`
- `REACHY_MINI_ENABLE_TRACKING=true|false`
- `REACHY_MINI_MAX_GESTURE_TIMES=3`
- `REACHY_MINI_MAX_EXPRESSION_SECONDS=5`
- `REACHY_MINI_MAX_DANCE_REPEAT=3`
- `REACHY_MINI_MAX_TRACKING_SECONDS=30`
- `REACHY_MINI_MAX_AUDIO_SECONDS=10`
- `REACHY_MINI_TTS_BACKEND=<optional backend>`

Motion/expression/dance/tracking tools are blocked if motion is disabled or IMU
state is not stable. Camera tools are blocked when camera is disabled. Audio and
sound direction tools are blocked when audio is disabled.

## Privacy notice

Camera and microphone tools should be used only when the user explicitly requests
capture/listening. This extension does not provide continuous surveillance,
long-running recording, face identity recognition, speaker identity recognition,
or default always-on tracking.

## Excluded APIs

This extension does **not** expose:

- actuator ID control
- raw joint angle, torque, current, PID, gain, speed, or acceleration controls
- arbitrary yaw/pitch/roll pose input
- arbitrary keyframe sequences or recorded-move paths
- raw pixel coordinate control
- unlimited repeat loops or long-running tracking
- calibration, firmware, or daemon management

## Troubleshooting

- If hardware is not connected, use `REACHY_MINI_MOCK=1`.
- If `reachy_say_text` returns unavailable, configure an optional TTS backend or
  synthesize audio externally and call `reachy_play_audio`.
- If a motion tool is blocked, check `reachy_get_imu`, robot stability, and
  `REACHY_MINI_ENABLE_MOTION`.
- If goose cannot see a tool, check `available_tools` in the goose extension config.
