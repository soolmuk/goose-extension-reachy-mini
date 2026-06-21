# goose-reachy-mini

<p align="right"><strong>Language:</strong> <a href="README.md">English</a> | 한국어</p>

goose가 Reachy Mini의 상태, 카메라, 주의/시선, 동작, 표정, 춤, 짧은 오디오 도구를 사용할 수 있게 해주는 안전한 고수준 MCP `stdio` 확장입니다.

이 프로젝트는 원시 액추에이터, 관절 각도, 토크, PID, 키프레임 또는 픽셀 좌표 API 대신 **의도/프리셋 수준의 도구**만 노출하도록 설계되었습니다.

## 상태

하드웨어별 SDK 매핑에 대한 mock 모드 지원과 graceful fallback 동작을 포함한 초기 구현입니다.

## 요구 사항

- Python 3.10+
- MCP stdio 확장을 지원하는 goose
- 하드웨어 사용 시 선택 사항: Reachy Mini / Reachy SDK 및 연결된 로봇

## 설치

```bash
pip install -e .
```

로컬 개발용 설치:

```bash
pip install -e '.[test,dev]'
```

## mock 모드로 실행

MCP 서버가 하드웨어 없이도 실행될 수 있도록 mock 모드가 기본으로 활성화되어 있습니다.

```bash
REACHY_MINI_MOCK=1 goose-reachy-mini --list-tools
REACHY_MINI_MOCK=1 goose-reachy-mini
```

`goose-reachy-mini`는 stdio를 통해 MCP 서버를 실행합니다. 직접 시작하면 MCP 메시지를 기다립니다.

## Reachy Mini Control App 어댑터

Reachy Mini Control App만 실행 중이고 goose를 로봇 SDK에 직접 연결하지 않는 경우, Control App 어댑터와 함께 확장을 실행하세요. 이 어댑터는 카메라 촬영을 지원하며, 정책상 허용된 경우 로컬 Control App 데몬을 통해 안전한 고수준 동작 프리셋 일부도 실행할 수 있습니다. 또한 Control App의 음성 방향 감지(DoA)와 데몬 오디오 재생을 지원합니다. 원시 오디오 녹음, 카메라 기반 머리/사람 트래킹, TTS는 아직 이 어댑터에서 사용할 수 없습니다.

기본적으로 확장은 `http://127.0.0.1:8000` / `http://localhost:8000`에서 실행 중인 Control App 데몬을 자동 감지하고, 내장 mock 클라이언트 대신 이를 사용할 수 있습니다. 즉, 확장은 Control App이 현재 사용하는 모드를 그대로 따릅니다: mockup 시뮬레이션, MuJoCo 시뮬레이션, Lite USB 로봇 또는 무선 로봇. 시뮬레이션과 실제 하드웨어를 위해 별도 goose 설정을 만들 필요가 없습니다.

현재 데스크톱 Control App 빌드는 HTTP로 카메라 사양을 노출하지만 원시 스냅샷은 노출하지 않으므로, 어댑터는 기본적으로 SDK `MediaManager` WebRTC/IPC 경로를 사용합니다. 최소 명시 설정은 다음과 같습니다.

```bash
REACHY_MINI_CONTROL_APP=1 \
REACHY_MINI_CONTROL_APP_MEDIA_BACKEND=auto \
goose-reachy-mini
```

Control App이 실행 중이어도 mock 모드를 강제로 사용하려면 자동 감지를 비활성화하세요.

```bash
REACHY_MINI_CONTROL_APP_AUTO=0 \
REACHY_MINI_MOCK=1 \
goose-reachy-mini
```

이 어댑터는 SDK `MediaManager`에서 프레임 하나를 읽기 위해 Control App / Reachy Mini Python 환경을 짧게 실행되는 헬퍼 프로세스로 띄운 뒤, 해당 프레임을 goose에 반환합니다. 헬퍼를 자동으로 찾지 못하면 다음을 설정하세요.

```bash
REACHY_MINI_CONTROL_APP_PYTHON="/path/to/control-app/.venv/bin/python3"
```

`REACHY_MINI_CONTROL_APP_MEDIA_BACKEND` 값:

- `auto` — 설정된 경우 HTTP 엔드포인트를 먼저 시도한 뒤 WebRTC, 로컬 IPC 순서로 시도
- `webrtc` — Control App WebRTC 스트림을 읽음. 데스크톱 앱에 가장 적합
- `local` — 데몬의 로컬 IPC 카메라 스트림을 읽음
- `http` — 설정된 HTTP 카메라 엔드포인트만 읽음

`REACHY_MINI_CONTROL_APP_CAPTURE_SOURCE`는 “현재 보이는 화면”의 의미를 제어합니다.

- `auto` — Control App 시뮬레이션/mockup 시뮬레이션에서는 웹캠 PIP 오버레이가 포함되도록 보이는 UI를 캡처하고, 실제 로봇 모드에서는 로봇 카메라 스트림을 캡처합니다.
- `camera` — 항상 원시 Reachy/Control App 미디어 스트림을 캡처합니다.
- `screen` — 항상 macOS의 보이는 화면을 `screencapture`로 캡처합니다.

macOS 화면 캡처의 경우 Terminal/goose 호스트 프로세스에 시스템 설정 → 개인정보 보호 및 보안의 화면 기록 권한이 필요할 수 있습니다. 선택적 crop 설정:

```bash
REACHY_MINI_CONTROL_APP_SCREEN_CROP="x,y,width,height"
```

직접 HTTP 카메라 엔드포인트가 있는 경우 다음 응답 형태를 지원합니다.

- 직접 JPEG/PNG 스냅샷 바이트
- MJPEG / `multipart/x-mixed-replace` 스트림
- `image_base64`, `frame`, `image` 같은 base64 이미지 필드를 포함한 JSON
- 스트림을 가리키는 `img`, `video`, `source`의 `src`가 포함된 HTML 페이지

선택 설정:

- `REACHY_MINI_CONTROL_APP_TIMEOUT_SECONDS=5`
- `REACHY_MINI_CONTROL_APP_SIGNALING_PORT=8443`
- `REACHY_MINI_CONTROL_APP_AUTH_TOKEN=<bearer token if required for HTTP>`

캡처 결과가 계속 mock 이미지로 반환된다면 `reachy_get_status`를 확인하세요. `"control_app_mode": true` 및 `"mock_mode": false`가 표시되어야 합니다. 또한 `control_app_runtime_mode`, `control_app_simulation_enabled`, `control_app_mockup_sim_enabled`, `control_app_media_released`, `control_app_camera_specs_name` 같은 관련 필드를 통해 Control App의 현재 런타임 모드를 보고합니다.

Control App 동작 프리셋은 별도 정책으로 제어됩니다.

- `REACHY_MINI_CONTROL_APP_PRESET_POLICY=simulation_only`(기본값)는 데몬이 `simulation` 또는 `mockup_simulation` 모드라고 보고할 때만 `look`, `look_at_image_region`, `gesture`, `turn_body`, `reset_pose`, 표정 fallback, 춤 fallback, stop 명령을 허용합니다.
- `REACHY_MINI_CONTROL_APP_PRESET_POLICY=off`는 데몬 동작 프리셋을 비활성화합니다.
- `REACHY_MINI_CONTROL_APP_PRESET_POLICY=always`는 실제 로봇 모드에서도 프리셋을 활성화합니다. 명시적인 opt-in 용도이므로 물리 환경이 안전할 때만 사용하세요.

Control App 프리셋 어댑터는 로컬 데몬의 `/api/move/goto`로 제한된 요청을 보냅니다. 표정과 춤은 초기 구현에서 임의 recorded-move 경로가 아니라 안전한 fallback 제스처 시퀀스를 사용합니다.

Control App 오디오/주의 기능은 데몬 수준 API를 사용합니다.

- `reachy_listen_direction`은 `/api/state/doa`를 읽고 보고된 각도를 안전한 방향 프리셋으로 변환합니다.
- `reachy_look_toward_sound`는 DoA와 단일 안전 `look` 프리셋을 조합합니다.
- `reachy_track_head`는 `mode="speaker"`만 지원합니다. 카메라 기반 `face`, `person` 트래킹은 아직 사용할 수 없습니다.
- `reachy_play_audio`는 검증된 짧은 오디오 클립을 `/api/media/sounds/upload`로 업로드하고 `/api/media/play_sound`로 재생합니다. 선택적 wobble은 `/api/media/wobbling/enable`을 사용하고 나중에 disable을 예약합니다.
- `reachy_listen_audio_sample`과 `reachy_say_text`는 별도 TTS 경로가 추가되기 전까지 Control App 어댑터에서 사용할 수 없습니다.

## goose 설정

[`config.example.yaml`](config.example.yaml)을 참고하세요.

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

그런 다음 사용하는 goose 버전의 확장 로딩 방식으로 goose를 시작하세요. 예:

```bash
goose session --with-extension reachy-mini
```

정확한 `--with-extension` 인자는 goose 버전에 따라 확장 이름 또는 설정 파일 경로일 수 있습니다. `goose --help` / `goose session --help`로 확인하세요.

## 공개 도구

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

## 예시 프롬프트

- 현재 보이는 게 뭐야?
- 나를 보고 밝게 인사해줘.
- 고개를 왼쪽으로 살짝 돌려줘.
- 행복한 표정을 지어줘.
- 오른쪽 위를 봐줘.
- 지금 로봇 상태와 IMU 상태를 알려줘.

## 프리셋

### 시선 방향

`center`, `left`, `right`, `up`, `down`, `front_left`, `front_right`

강도는 `small` 또는 `medium`으로 제한됩니다.

### 이미지 영역

`center`, `upper_left`, `upper_right`, `lower_left`, `lower_right`,
`person_candidate`, `object_candidate`

원시 픽셀 좌표는 노출하지 않습니다.

### 제스처

`yes`, `yes_understanding`, `no`, `no_firm`, `curious_tilt_left`,
`curious_tilt_right`, `look_around_short`, `small_bounce`, `shy_tilt`,
`thinking_wobble_short`, `antenna_wave`, `antenna_perk_up`, `antenna_relax`

`times`는 `REACHY_MINI_MAX_GESTURE_TIMES`로 제한됩니다(기본값 `3`).

### 표정

지원되는 의도 이름에는 `happy`, `excited`, `greeting`, `welcoming`, `thinking`, `curious`, `surprised`, `sad`, `yes`, `no`, `sleepy`, `random` 및 구현 계획에 문서화된 다른 enum 값이 포함됩니다. 원시 recorded-move 경로는 허용되지 않습니다.

### 춤

`random`, `happy_wiggle`, `celebration`, `silly`, `groove`

반복 횟수는 `REACHY_MINI_MAX_DANCE_REPEAT`로 제한됩니다(기본값 `3`).

## 안전 정책

환경 변수:

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

동작/표정/춤/트래킹 도구는 동작이 비활성화되어 있거나 IMU 상태가 안정적이지 않으면 차단됩니다. 카메라 도구는 카메라가 비활성화되어 있으면 차단됩니다. 오디오 및 소리 방향 도구는 오디오가 비활성화되어 있으면 차단됩니다.

## 개인정보 안내

카메라와 마이크 도구는 사용자가 명시적으로 캡처/듣기를 요청한 경우에만 사용해야 합니다. 이 확장은 지속 감시, 장시간 녹음, 얼굴 신원 인식, 화자 신원 인식 또는 기본 상시 트래킹 기능을 제공하지 않습니다.

## 제외된 API

이 확장은 다음을 노출하지 않습니다.

- 액추에이터 ID 제어
- 원시 관절 각도, 토크, 전류, PID, gain, 속도 또는 가속도 제어
- 임의 yaw/pitch/roll 자세 입력
- 임의 키프레임 시퀀스 또는 recorded-move 경로
- 원시 픽셀 좌표 제어
- 무제한 반복 루프 또는 장시간 트래킹
- 캘리브레이션, 펌웨어 또는 데몬 관리

## 문제 해결

- 하드웨어가 연결되어 있지 않으면 `REACHY_MINI_MOCK=1`을 사용하세요.
- `reachy_say_text`가 unavailable을 반환하면 선택적 TTS 백엔드를 설정하거나 외부에서 오디오를 합성한 뒤 `reachy_play_audio`를 호출하세요.
- 동작 도구가 차단되면 `reachy_get_imu`, 로봇 안정성, `REACHY_MINI_ENABLE_MOTION`을 확인하세요.
- goose가 도구를 볼 수 없으면 goose 확장 설정의 `available_tools`를 확인하세요.
