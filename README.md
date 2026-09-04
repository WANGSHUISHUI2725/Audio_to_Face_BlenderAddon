# Audio2Face Blender Add-on

This repository contains a Blender add-on and a native exporter that use the NVIDIA
Audio2Face 3D SDK to generate ARKit-compatible facial animation from audio.

## Version 0.6.0

Version 0.6.0 fixes direct Shape Key animation on Blender 4.5 and newer. Generated curves
are now bound to a `KEY` Action Slot instead of an unassigned Legacy Slot, so unrigged mesh
Shape Keys are evaluated correctly on the timeline.

Direct Shape Key mode now supports registering multiple character mesh parts, including the
head, mouth, teeth, tongue, eyeballs, and irises. All registered parts share one generated
Action and one Shape Key slot containing the combined animation curves. The release also
adds duplicate-registration protection, model validation, and Blender 4.5/5.2 regression
tests for both new-animation and overwrite workflows.

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

## GPU compatibility risk notice

The versions listed above describe the current test environment; they do not guarantee
support for every NVIDIA GPU. As a practical starting point, RTX 20-series and newer
cards are the target range, while RTX 30-series and newer cards with at least 12 GB of
VRAM are recommended for the v3.0 model. RTX 20-series/Turing cards may work but require
additional testing. GTX 16-series, GTX 10-series, and older cards are not recommended.

Compatibility depends on the GPU's Compute Capability, available VRAM, NVIDIA driver,
CUDA Runtime, TensorRT version, and the model being used. A TensorRT engine such as
`network.trt` may not be portable between GPU architectures or different TensorRT builds;
it may need to be regenerated on the target machine. A newer GPU can therefore still fail
if the driver, CUDA/TensorRT versions, or generated engine do not match. The project will
publish a tested GPU matrix as more hardware is verified.

## Known issues

1. **Eye movement and blinking**: Eye controls and blinking are not yet driven reliably.
   The next iteration should add an optimization algorithm. If no suitable open-source
   solution is available, noise-based jitter and fixed-frequency blinking will be evaluated
   as fallback approaches.
2. **v3.0 lip intersection**: The v3.0 model can cause the upper and lower lips to intersect.
   The initial diagnosis is that the `jawOpen` Shape Key value can leave the `[0, 1]` range
   and become negative. A later fix will attempt to clamp `jawOpen` values to `[0, 1]`.
3. **Missing TensorRT files**: The add-on preferences should provide a validation button that
   checks whether referenced files such as `network.trt` exist. We also need to investigate
   whether users without a development environment can generate the TensorRT engine locally.

## Development roadmap

1. Add support for MetaHuman Shape Keys.
2. Add sliders for controlling blinking frequency and eye-jitter frequency.
3. Expand GPU compatibility: infer candidate GPU models from the installed driver, CUDA,
   and TensorRT versions, then test and document support across additional GPU models.

## License

Project code is released under the **GNU General Public License v3.0 or later
(GPL-3.0-or-later)**. See the [official GPLv3 text](https://www.gnu.org/licenses/gpl-3.0.html)
for the license terms.

NVIDIA Audio2Face SDK, model, CUDA, TensorRT, and other third-party components remain
subject to their respective licenses and are not relicensed by this project. See
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
