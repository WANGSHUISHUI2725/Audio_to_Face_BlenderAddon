# Audio2Face Blender Add-on

This repository contains a Blender add-on and a native exporter that use the NVIDIA
Audio2Face 3D SDK to generate ARKit-compatible facial animation from audio.

## Contents

- `BlenderAddon/`: Blender add-on source, tests, and packaging script.
- `Engine/`: native exporter source and CMake build files.
- `BlenderAddon/a2f_local.zip`: installable Windows package, when present.

CUDA, TensorRT, NVIDIA GPU drivers, and A2F model files are intentionally not stored here.
Install or download them from NVIDIA's official sources, then select their local paths in
the Blender add-on preferences. The A2F model must be downloaded as a complete directory,
not just `model.json`.

## Requirements

- Windows 10/11 x64
- Blender compatible with the add-on
- NVIDIA GPU and current driver
- CUDA 12.8-12.x
- TensorRT 10.13.x
- NVIDIA Audio2Face-3D model

See [`BlenderAddon/README.md`](BlenderAddon/README.md) for installation and usage details.

## License

Project code is released under the MIT License. NVIDIA Audio2Face SDK, model, CUDA, and
TensorRT components remain subject to their respective licenses. See
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
