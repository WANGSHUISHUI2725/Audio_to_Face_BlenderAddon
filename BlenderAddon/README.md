# Audio2Face Local for Blender

This add-on runs NVIDIA Audio2Face 3D SDK locally and sends its 52 ARKit-compatible
blendshape channels to a Faceit control rig or matching Blender Shape Keys. Maintainer:
WangShuishui.

## Install

1. In Blender, open **Edit > Preferences > Add-ons > Install from Disk**.
2. Select the packaged `a2f_local.zip` and enable **Audio2Face Local**.
3. In the add-on preferences, choose the complete A2F model's `model.json`, your CUDA
   Toolkit directory (12.8-12.x), and TensorRT directory (10.13.x). The exporter and
   `audio2x.dll` are included in the ZIP; CUDA, TensorRT, and the model are downloaded
   separately from NVIDIA's official channels.

## Use

Open **3D View > Sidebar > Audio2Face**, choose a common audio file (WAV, MP3, M4A/AAC,
WMA, or another format supported by Windows Media Foundation), then run **Generate
Facial Animation**. Audio is decoded to mono 16 kHz automatically.

**Faceit Control Rig** is the default mode. It imports the 52 ARKit channels through
Faceit's official A2F mocap importer and bakes to the connected Faceit control rig, so
driver-controlled Shape Keys remain intact. Auto-Rig Pro body animation is not changed.
Use **Shape Keys** only for meshes without a Faceit control rig.

The add-on detects Faceit rigs from their `ctrl_rig_id` / `ctrl_rig_version` metadata and
checks that mesh Shape Key drivers reference the detected rig. **Detect Faceit Control
Rig** also writes the result into Faceit's own scene setting, so the Faceit Control Rig
panel and this add-on use the same rig.

Choose **Generate Animation** to generate JSON and import immediately, or **Generate
Faceit JSON** to create a file for Faceit's regular **Mocap > Audio2Face** importer. JSON
files are stored in the configured output folder; the folder can be changed in the add-on
preferences and opened from the Audio2Face panel.

Sampled curves use linear interpolation and are explicitly updated after bulk keyframe
creation to prevent invalid handles and overshoot.

The default duration limit is 60 seconds. Audio2Face samples facial motion at 60 FPS;
Faceit maps 3600 source samples to about 1800 Blender timeline frames in a 30 FPS scene.

Shape Key matching ignores case and separators, so names such as `jawOpen`, `jaw_open`,
and `Jaw.Open` match the same channel.
