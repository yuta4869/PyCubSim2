# Agent Bundle

Agent Bundle は、3Dモデル、カメラ定義、Python Controller を1つのディレクトリに
まとめる形式です。GUI の `Import Agent` から `agent.json` を選びます。

## 最小構成

```text
my_agent/
  agent.json
  robot.urdf
  controller.py
```

```json
{
  "format_version": 1,
  "name": "My Agent",
  "model": {
    "path": "robot.urdf",
    "fixed_base": true,
    "scale": 1.0
  },
  "spawn": {
    "position": [-0.3, 0.4, 0.05],
    "rpy_deg": [0, 0, 0]
  },
  "controller": "controller.py:Controller",
  "cameras": [
    {
      "name": "head_camera",
      "link": "head",
      "offset": [0.1, 0, 0],
      "forward": [1, 0, 0],
      "up": [0, 0, 1],
      "fov_deg": 70
    }
  ],
  "metadata": {}
}
```

`model.path` は manifest からの相対パスまたは絶対パスです。対応形式は
URDF、SDF、MJCF (`.xml`)、OBJ、STL です。

## 座標

- 距離: meter
- 姿勢: degree
- 右手系、`+Z` が上
- カメラの `offset`、`forward`、`up` は取付リンクのローカル座標
- `link` が空、または存在しない場合は base に取付

## Controller

```python
class Controller:
    def on_start(self, api):
        pass

    def update(self, api, dt_s, sensors):
        return {
            "joint_positions_deg": {"head_yaw": 20.0},
            "base_linear_velocity": [0.1, 0.0, 0.0],
            "base_angular_velocity": [0.0, 0.0, 0.2]
        }

    def on_stop(self, api):
        pass
```

`on_start` と `on_stop` は任意です。`update` は scene の `control_hz`
（標準60 Hz）で呼ばれます。例外が発生すると Controller は停止し、Actions
タブにエラーを表示します。

返却できる辞書フィールド:

- `joint_positions`: `{joint_name: radians}`
- `joint_positions_deg`: `{joint_name: degrees}`
- `base_linear_velocity`: `[vx, vy, vz]`
- `base_angular_velocity`: `[wx, wy, wz]`
- `base_position`: `[x, y, z]`
- `base_rpy_deg`: `[roll, pitch, yaw]`

位置指令と速度指令を同時に返す場合、位置指令がその更新の最終姿勢になります。

## Agent API

Controller へ渡される `api`:

- `api.entity_id`
- `api.simulation_time`
- `api.get_pose()`
- `api.set_pose(position, rpy_deg=None)`
- `api.set_base_velocity(linear, angular=(0, 0, 0))`
- `api.set_joint_positions(targets, degrees=False)`
- `api.capture_camera(mount="body", width=320, height=240)`
- `api.sensor_snapshot()`

`sensors` 引数は `api.sensor_snapshot()` と同形式で、有効化された joint state、
IMU、contact、range ray を含みます。

## セキュリティ

Controller は隔離環境ではなく、PyCubSim2 と同じローカル Python プロセスで
実行されます。ファイルアクセスやネットワークアクセスを含む任意コードを実行
できるため、内容を確認できる信頼済み Bundle だけを読み込んでください。

