# Audio to Face Blender Add-on

Audio2Face Local is a Windows Blender add-on that runs NVIDIA Audio2Face 3D SDK locally
and imports 52-channel ARKit facial animation into Blender. It supports Faceit control
rigs, direct Shape Key animation, persistent Faceit-compatible JSON export, Unicode
paths, and common audio formats supported by Windows Media Foundation.

Maintainer: WangShuishui

## Repository contents

- `BlenderAddon/a2f_local/`: Blender add-on source.
- `BlenderAddon/a2f_local.zip`: installable add-on package for the current version.
- `BlenderAddon/tests/`: small unit-test suite for channel mapping and JSON generation.
- `Engine/src/`: source for the local Audio2Face exporter.
- `Engine/CMakeLists.txt` and `Engine/build.ps1`: Windows exporter build files.

CUDA, TensorRT, generated models, the NVIDIA Audio2Face SDK checkout, Maya/Unreal
reference plug-ins, Faceit, Auto-Rig Pro, local test media, and generated animation JSON
are deliberately excluded from version control.

## Install

1. Download `BlenderAddon/a2f_local.zip`.
2. In Blender, use **Edit > Preferences > Add-ons > Install from Disk**.
3. Enable **Audio2Face Local**.
4. Configure the model, CUDA, and TensorRT paths in the add-on preferences.

See [BlenderAddon/README.md](BlenderAddon/README.md) for usage details.

## Build requirements

- Windows 10 or 11
- Visual Studio 2022 C++ build tools
- CMake 3.24 or newer
- NVIDIA Audio2Face 3D SDK
- CUDA 12.8 or newer, below CUDA 13
- TensorRT 10.13

Clone and build the NVIDIA SDK separately, then run:

```powershell
.\Engine\build.ps1 -SdkRoot C:\path\to\Audio2Face-3D-SDK
.\BlenderAddon\package.ps1
```

## Tests

```powershell
python -m unittest discover -s BlenderAddon/tests -v
```

## Licensing

The bundled `audio2x.dll` and the SDK interfaces used by the exporter originate from
NVIDIA Audio2Face 3D SDK. See `THIRD_PARTY_LICENSES/NVIDIA-Audio2Face-3D-SDK-LICENSE.txt`.

No license has yet been assigned to the original add-on and exporter code. Before making
this repository public as an open-source project, choose and add an appropriate project
license.

