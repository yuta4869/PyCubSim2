# PyCubSim2

PyCubSim2 は、1台の PyCub と1台の机から始め、GUI 上でロボット、物体、
センサー、行動、外部エージェントを組み替えられる拡張シミュレーターです。
既存の `pycub_dual_tabletop` は変更せず、独立した環境として作成しています。

初期シーンには [rustlluk/pyCub](https://github.com/rustlluk/pyCub) の
`full.urdf` と3D資産を使っています。公式画像に近い「机の前に立つ iCub」を
初期状態にしていますが、公式の高水準 Python API をそのまま複製したものではなく、
シーン編集と統合GUIを追加した別アプリケーションです。

![PyCubSim2 default scene](docs/images/default_scene.png)

## 起動

macOS では、次のアプリを Finder からダブルクリックできます。

```text
/Users/yuta/research/PyCubSim2/PyCubSim2.app
```

ターミナルから起動する場合:

```bash
cd /Users/yuta/research/PyCubSim2
./launch.command
```

専用環境を作り直す場合:

```bash
cd /Users/yuta/research/PyCubSim2
conda env create -f environment.yml
conda activate pycubsim2
python run_sim.py
```

`launch.command` と `.app` は `pycubsim2` 環境を優先し、現在利用可能な
`pycub-homeostatic` 環境を次の候補として使います。

## GUI

### Scene

- `Add PyCub`: PyCub を追加し、最初の机の方向へ向けて配置
- `Add Table`: 机を追加
- `Add Object`: box、sphere、cylinder を寸法、質量、色、固定／動的で追加
- `Import 3D`: URDF、SDF、MJCF (`.xml`)、OBJ、STL を読込
- `Import Agent`: 3Dモデル、カメラ、Python行動を束ねた `agent.json` を読込
- `Duplicate` / `Remove`: 選択要素の複製／削除
- `Apply`: 名前、位置、姿勢、スケール、質量、寸法、色を反映

上部の `Open` / `Save` でシーン全体を JSON として読み書きできます。
`Reset` は PyCub 1台と机1台の初期状態へ戻します。
`Undo` / `Redo` は追加、削除、プロパティ変更、マップ／3D画面での配置変更を
戻す／やり直すための共通履歴です。macOSでは `Command + Z` /
`Command + Shift + Z` も使えます。
選択した種類／ファイル形式で反映できないプロパティは自動的に無効になります。
たとえば URDF の質量と材質はファイル側の定義を使います。

![Two PyCubs and an added object](docs/images/extensible_scene.png)

### Layout

`Layout` タブは、シーン全体を上から見た配置マップです。追加した台数や種類に
かかわらず、PyCub、机、物体、3Dモデル、Agent Bundleを同じマップで扱えます。

- 本体をクリック: 対象を選択し、Scene / Actions / Sensors と同期
- 本体をドラッグ: X-Y平面上で移動
- 選択対象から伸びる矢印先端をドラッグ: yawを変更
- マウスホイール／トラックパッドスクロール: yawを5度ずつ変更
- `Apply placement`: X、Y、Yawの数値を反映
- `Fit world camera`: 全要素が入るようWorldカメラを空間中心へ戻す

ドラッグ中も3D画面へ反映され、確定後は1回の `Undo` で元の配置へ戻ります。

### Actions

PyCub ごとに次の行動を選択できます。

- Manual pose
- Idle breathing
- Look around
- Right arm wave
- Left arm wave
- Both arms wave
- Whole-body tilt
- Random motion
- Keyframe action

`Start` と `Stop` は選択中の個体だけに作用します。手動関節スライダー、左右の
grip、世界座標を使う腕の IK (`Reach`) も個体ごとに独立しています。
手動・IK指令は即時反映され、時間変化する行動だけが周期実行されます。

`Load JSON action` では `actions/` のキーフレーム行動を読めます。
関節値は度、grip は `0.0`（開）から `1.0`（閉）です。

### Sensors

カメラ源は次から選べます。

- World camera
- Mac webcam 0
- 各 PyCub の Left eye / Right eye / Body camera
- 外部 Agent Bundle が定義したカメラ
- 一般の3Dモデルに付く Body camera

表示は `Sensor RGB`、`Sensor Depth`、`Segmentation` から選べます。
構造化センサーとして joint state、IMU、contact、24本の range ray を任意に
有効化できます。`Export sensor snapshot` は表示画像と同名の JSON を保存します。
PyCubを追加すると、その個体のLeft eye / Right eye / Body cameraもカメラ候補へ
即時追加されます。最初のPyCubだけに固定されてはいません。主カメラは3D画面上部の
選択ボックスまたはSensorsタブ、副画面は`Second view`行の選択ボックスで切り替えます。

Macカメラを初めて選ぶと、macOSのカメラ許可が表示されます。Webcam はRGBのみで、
depth と segmentation はシミュレーションカメラ用です。

Depthの内部配列 `depth_m` は、PyBulletのOpenGL depth bufferをnear/far平面から
逆射影した、カメラ光軸方向のメートル単位Z距離です。画面のDepth色は0.05 mから5 mまでの固定対数尺度で、
中央画素の実距離を `center 0.000 m` 形式で画面左上に表示します。背景などレイが
届かなかった場所は黒と `no return` になります。

| Left eye RGB | Left eye depth | Left eye segmentation |
| --- | --- | --- |
| ![RGB](docs/images/left_eye_rgb.png) | ![Depth](docs/images/left_eye_depth.png) | ![Segmentation](docs/images/left_eye_segmentation.png) |

### Camera

- `Camera`カーソル + 左ドラッグ: orbit
- `Camera`カーソル + Shift + 左ドラッグ: pan
- 中央ドラッグ／右ドラッグ: カーソルモードに関係なくpan
- マウスホイール／トラックパッドスクロール: zoom
- ダブルクリック: 選択要素へ focus
- `Select`カーソル + クリック: 3D画面内のPyCub、机、物体などを選択
- `Move`カーソル + ドラッグ: World / Top画面上で選択対象をX-Y移動
- Camera タブ: yaw、pitch、distance、shadow、画質
- Control + Tab／Shift + Control + Tab: 右側タブを前後移動

3D画面で選択した対象は黄色枠で示され、上部の `Info` / `Actions` / `Sensors` から
対象情報、可能な行動、機能の有効／無効へ直接移動できます。`World`の初期位置と
`Fit whole scene`は最初のPyCubではなく全要素の空間境界を基準にします。
`Top`と`Side`も常にシーン全体の中心を使います。

`Dual view`を有効にすると画面を左右に分割します。右画面には独立した
カメラ源と `World` / `Top` / `Side` / RGB / Depth / Segmentationを選べるため、
たとえば左にWorld、右に追加PyCubの右眼、または左にPyCubの眼、右にMac webcamを
同時表示できます。`Command + D`（Windows/Linuxは `Control + D`）でも切り替えられます。

標準の `Performance` でも表示領域の1.25倍、`Balanced`は1.65倍、
`Quality`は2倍を上限付きで描画して縮小するため、旧版の640 px引き伸ばしは
行いません。

## 3Dエージェント

単なるモデルは `Import 3D`、モデルと行動を一緒に追加する場合は
`Import Agent` を使います。サンプル:

```text
examples/agents/beacon_agent/
  agent.json
  beacon.urdf
  controller.py
```

サンプルを読み込んで Agent を選択し、Actions タブの `Start` を押すと、
上下動、旋回、首関節の行動が始まります。詳しい形式と Controller API は
[docs/AGENT_BUNDLES.md](docs/AGENT_BUNDLES.md) を参照してください。
ローカル Controller は通常の Python コードとして実行されるため、信頼できる
Bundle だけを読み込んでください。

![Imported Beacon Agent](docs/images/beacon_agent.png)

## 性能

標準は `Performance`、shadow 無効です。

- 静止中は3Dフレームを作り直さない
- 固定された PyCub と机だけなら、変化関節だけを直接更新
- 動的物体や動的モデルを追加すると、240 Hz の PyBullet 物理へ自動切替
- 行動中は壁時計に追従する可変ステップ更新
- `Balanced` / `Quality` と shadow は画質を上げる代わりにCPU負荷が増加

動的な接触実験では物体の `Fixed base` を無効にし、質量を `0` より大きくします。

## ヘッドレス実行

```bash
python run_sim.py --headless --steps 480 \
  --output artifacts/headless_preview.png

python run_sim.py --headless --steps 480 \
  --agent examples/agents/beacon_agent/agent.json \
  --output artifacts/agent_preview.png
```

オプション一覧:

```bash
python run_sim.py --help
```

## テスト

```bash
python -m unittest discover -s tests -v
```

初期シーン、複数PyCub、行動、IK、動的物理、RGB-D、segmentation、各種センサー、
保存／再読込、外部 Agent Controller、統合GUIを検証します。

## 構成

```text
pycubsim2/
  actions.py       内蔵行動とJSONキーフレーム
  config.py        シーン／要素／センサー設定
  gui.py           統合GUI
  layout_editor.py 任意要素対応の俯瞰配置マップ
  plugins.py       Agent BundleとControllerホスト
  sensors.py       RGB-D、segmentation、webcam
  simulation.py    PyBulletシーン、物理、カメラ、IK
assets/iCub/       公式 pyCub 由来の iCub URDF／mesh／skin
actions/           読込可能なサンプル行動
examples/agents/   外部3Dエージェントのサンプル
layouts/           保存シーン
```

## 出典とライセンス

iCubモデル資産は
[rustlluk/pyCub](https://github.com/rustlluk/pyCub)
commit `081ef65565355ca700604e40b94f8491c8e4d15a` の
`icub_pybullet/iCub` を基にしています。詳細は
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) と [LICENSE](LICENSE) を参照してください。
