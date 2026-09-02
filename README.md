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

## Requirements and downloads

The following versions match the environment used to build and test the current Windows
package. Using these exact versions is recommended before trying newer releases.

| Component | Tested version | Supported/required range | Official download |
| --- | --- | --- | --- |
| Operating system | Windows 10/11 x64 | Windows 10/11 x64 | - |
| NVIDIA GPU driver | A current driver compatible with CUDA 12.9 | NVIDIA driver with CUDA 12.9 support | [NVIDIA Driver Downloads](https://www.nvidia.com/Download/index.aspx) |
| CUDA Toolkit | **12.9.2** | `>= 12.8, < 13.0` | [CUDA Toolkit Archive](https://developer.nvidia.com/cuda-toolkit-archive) |
| TensorRT | **10.13.3.9** | `>= 10.13, < 11.0` | [TensorRT Downloads](https://developer.nvidia.com/tensorrt/download/10x) |
| A2F model (v2) | **Audio2Face-3D-v2.3-Mark** | Model compatible with the NVIDIA Audio2Face 3D SDK | [NVIDIA model on Hugging Face](https://huggingface.co/nvidia/Audio2Face-3D-v2.3-Mark) |
| A2F model (v3) | **Audio2Face-3D-v3.0** | Model compatible with the NVIDIA Audio2Face 3D SDK | [NVIDIA model on Hugging Face](https://huggingface.co/nvidia/Audio2Face-3D-v3.0) |
| Audio2Face SDK | Current NVIDIA Audio2Face-3D-SDK used by this project | CUDA/TensorRT-compatible SDK build | [Audio2Face-3D-SDK on GitHub](https://github.com/NVIDIA/Audio2Face-3D-SDK) |

An NVIDIA GPU is required; the current exporter does not provide a CPU inference mode.
Install the GPU driver first, then CUDA and TensorRT. Download the complete A2F model
repository rather than only `model.json`: files such as `model_data.npz`, `network.onnx`,
blendshape data, and the adjacent configuration files are also required. In Blender's
add-on preferences, select:

- the model directory's `model.json`;
- the CUDA Toolkit root directory (the directory containing `bin`);
- the TensorRT root directory (the directory containing `lib`).

The v3.0 model package may provide `network.onnx` but not a prebuilt `network.trt`. In that
case, run the NVIDIA SDK model/test-data generation step to build the TensorRT engine, or use
the generated `multi-diffusion/network.trt` produced by the SDK when it matches the v3.0
model files. Place the resulting `network.trt` beside v3.0's `model.json`.

See [`BlenderAddon/README.md`](BlenderAddon/README.md) for installation and usage details.

## License

Project code is released under the MIT License. NVIDIA Audio2Face SDK, model, CUDA, and
TensorRT components remain subject to their respective licenses. See
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
