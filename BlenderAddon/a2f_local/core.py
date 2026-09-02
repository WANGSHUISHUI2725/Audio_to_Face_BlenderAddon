import json
import os
import re
from datetime import datetime
from pathlib import Path


MODEL_MODE_AUTO = "AUTO"
MODEL_MODE_REGRESSION = "REGRESSION"
MODEL_MODE_DIFFUSION = "DIFFUSION"


def detect_model_mode(model_path):
    """Return the A2F executor type described by a model.json file."""
    try:
        with Path(model_path).open("r", encoding="utf-8") as stream:
            model = json.load(stream)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read A2F model configuration: {error}") from error
    if not isinstance(model, dict):
        raise ValueError("A2F model configuration must be a JSON object")
    if isinstance(model.get("modelConfigPaths"), list) and isinstance(
        model.get("modelDataPaths"), list
    ):
        return MODEL_MODE_DIFFUSION
    if isinstance(model.get("modelConfigPath"), str) and isinstance(
        model.get("modelDataPath"), str
    ):
        return MODEL_MODE_REGRESSION
    raise ValueError("Unrecognized A2F model configuration")


def resolve_model_mode(model_path, requested_mode):
    detected = detect_model_mode(model_path)
    if requested_mode == MODEL_MODE_AUTO:
        return detected
    if requested_mode not in (MODEL_MODE_REGRESSION, MODEL_MODE_DIFFUSION):
        raise ValueError(f"Unknown A2F model mode: {requested_mode}")
    if requested_mode != detected:
        raise ValueError(
            f"Selected {requested_mode.title()} mode does not match the model.json "
            f"detected as {detected.title()}"
        )
    return requested_mode


SCHEMA = "a2f-blendshapes-v1"

# Faceit 2.3.73 reads weightMat by position and uses this internal order, which
# differs from NVIDIA's ARKit order for two left/right pairs.
FACEIT_ARKIT_CHANNELS = (
    "eyeBlinkLeft", "eyeLookDownLeft", "eyeLookInLeft", "eyeLookOutLeft",
    "eyeLookUpLeft", "eyeSquintLeft", "eyeWideLeft", "eyeBlinkRight",
    "eyeLookDownRight", "eyeLookInRight", "eyeLookOutRight", "eyeLookUpRight",
    "eyeSquintRight", "eyeWideRight", "jawForward", "jawLeft", "jawRight",
    "jawOpen", "mouthClose", "mouthFunnel", "mouthPucker", "mouthRight",
    "mouthLeft", "mouthSmileLeft", "mouthSmileRight", "mouthFrownRight",
    "mouthFrownLeft", "mouthDimpleLeft", "mouthDimpleRight", "mouthStretchLeft",
    "mouthStretchRight", "mouthRollLower", "mouthRollUpper", "mouthShrugLower",
    "mouthShrugUpper", "mouthPressLeft", "mouthPressRight", "mouthLowerDownLeft",
    "mouthLowerDownRight", "mouthUpperUpLeft", "mouthUpperUpRight", "browDownLeft",
    "browDownRight", "browInnerUp", "browOuterUpLeft", "browOuterUpRight",
    "cheekPuff", "cheekSquintLeft", "cheekSquintRight", "noseSneerLeft",
    "noseSneerRight", "tongueOut",
)


def normalize_name(value):
    return re.sub(r"[^a-z0-9]", "", value.lower())


def match_channels(channels, shape_key_names):
    available = {normalize_name(name): name for name in shape_key_names}
    return {
        channel: available[normalize_name(channel)]
        for channel in channels
        if normalize_name(channel) in available
    }


def load_animation(path):
    with Path(path).open("r", encoding="utf-8") as stream:
        data = json.load(stream)

    if data.get("schema") != SCHEMA:
        raise ValueError("Unsupported Audio2Face animation schema")
    fps = data.get("fps")
    channels = data.get("channels")
    frames = data.get("frames")
    if not isinstance(fps, (int, float)) or fps <= 0:
        raise ValueError("Animation FPS must be positive")
    if not isinstance(channels, list) or not channels or not all(isinstance(v, str) for v in channels):
        raise ValueError("Animation has no valid channels")
    if not isinstance(frames, list) or not frames:
        raise ValueError("Animation has no frames")
    for index, frame in enumerate(frames):
        weights = frame.get("w") if isinstance(frame, dict) else None
        if not isinstance(weights, list) or len(weights) != len(channels):
            raise ValueError(f"Frame {index} has an invalid weight count")
    return data


def write_faceit_animation(source_path, destination_path):
    data = load_animation(source_path)
    weight_matrix = data.get("weightMat")
    source_channels = data.get("facsNames") or data["channels"]
    if not isinstance(weight_matrix, list) or len(weight_matrix) != len(data["frames"]):
        raise ValueError("Animation has no valid Faceit weight matrix")

    indices = {normalize_name(name): index for index, name in enumerate(source_channels)}
    try:
        faceit_indices = [indices[normalize_name(name)] for name in FACEIT_ARKIT_CHANNELS]
    except KeyError as error:
        raise ValueError(f"Faceit channel is missing: {error.args[0]}") from error
    for index, row in enumerate(weight_matrix):
        if not isinstance(row, list) or len(row) != len(source_channels):
            raise ValueError(f"Faceit weight row {index} has an invalid weight count")

    data["weightMat"] = [[row[index] for index in faceit_indices] for row in weight_matrix]
    data["facsNames"] = list(FACEIT_ARKIT_CHANNELS)
    with Path(destination_path).open("w", encoding="ascii") as stream:
        json.dump(data, stream, ensure_ascii=True, separators=(",", ":"))
    return Path(destination_path)


def safe_output_stem(value):
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value)).strip(" .")
    return stem or "audio"


def create_json_output_paths(directory, audio_path, now=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    stem = safe_output_stem(Path(audio_path).stem)
    base = directory / f"{stem}_a2f_{timestamp}"
    suffix = 1
    while base.with_suffix(".json").exists() or base.with_name(base.name + "_faceit.json").exists():
        base = directory / f"{stem}_a2f_{timestamp}_{suffix:02d}"
        suffix += 1
    return base.with_suffix(".json"), base.with_name(base.name + "_faceit.json")


def default_workspace_paths(addon_file):
    addon_directory = Path(addon_file).resolve().parent
    workspace = Path(os.environ.get("A2F_DEV_ROOT", "D:/A2F_Dev"))
    bundled_exporter = addon_directory / "bin" / "a2f_blender_exporter.exe"
    return {
        "exporter": bundled_exporter
        if bundled_exporter.is_file()
        else workspace / "Engine" / "build" / "Release" / "a2f_blender_exporter.exe",
        "model": workspace
        / "Audio2Face-3D-SDK"
        / "_data"
        / "generated"
        / "audio2face-sdk"
        / "samples"
        / "data"
        / "mark"
        / "model.json",
        "diffusion_model": workspace
        / "Audio2Face-3D-SDK"
        / "_data"
        / "audio2face-models"
        / "audio2face-3d-v3.0"
        / "model.json",
        "cuda": workspace / "CUDA" / "v12.9",
        "tensorrt": workspace / "TensorRT" / "TensorRT-10.13.3.9",
        "json_output": workspace / "BlenderAddon" / "generated_json",
    }
