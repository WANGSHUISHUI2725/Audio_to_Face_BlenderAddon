import json
import importlib.util
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

CORE_PATH = Path(__file__).parents[1] / "a2f_local" / "core.py"
SPEC = importlib.util.spec_from_file_location("a2f_local_core", CORE_PATH)
CORE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CORE)
load_animation = CORE.load_animation
match_channels = CORE.match_channels
normalize_name = CORE.normalize_name
write_faceit_animation = CORE.write_faceit_animation
create_json_output_paths = CORE.create_json_output_paths
detect_model_mode = CORE.detect_model_mode
resolve_model_mode = CORE.resolve_model_mode
resolve_runtime_model = CORE.resolve_runtime_model


class CoreTests(unittest.TestCase):
    def test_detects_regression_and_diffusion_models(self):
        with tempfile.TemporaryDirectory() as directory:
            regression = Path(directory) / "regression.json"
            diffusion = Path(directory) / "diffusion.json"
            regression.write_text(
                json.dumps({"modelConfigPath": "config.json", "modelDataPath": "data.npz"}),
                encoding="utf-8",
            )
            diffusion.write_text(
                json.dumps({"modelConfigPaths": ["config.json"], "modelDataPaths": ["data.npz"]}),
                encoding="utf-8",
            )
            self.assertEqual(detect_model_mode(regression), "REGRESSION")
            self.assertEqual(detect_model_mode(diffusion), "DIFFUSION")
            self.assertEqual(resolve_model_mode(diffusion, "AUTO"), "DIFFUSION")

    def test_rejects_model_mode_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / "model.json"
            model.write_text(
                json.dumps({"modelConfigPath": "config.json", "modelDataPath": "data.npz"}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "does not match"):
                resolve_model_mode(model, "DIFFUSION")

    def test_runtime_model_falls_back_when_download_has_no_tensorrt_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            downloaded = root / "downloaded" / "model.json"
            generated = root / "generated" / "model.json"
            downloaded.parent.mkdir()
            generated.parent.mkdir()
            model_data = json.dumps({"networkPath": "network.trt"})
            downloaded.write_text(model_data, encoding="utf-8")
            generated.write_text(model_data, encoding="utf-8")
            (generated.parent / "network.trt").write_bytes(b"engine")
            self.assertEqual(resolve_runtime_model(downloaded, generated), generated)

    def test_normalize_name(self):
        self.assertEqual(normalize_name("Mouth_Smile.Left"), "mouthsmileleft")

    def test_channel_matching_accepts_common_separators(self):
        mapping = match_channels(
            ["mouthSmileLeft", "jawOpen", "eyeBlinkRight"],
            ["Basis", "mouth_smile_left", "Jaw.Open"],
        )
        self.assertEqual(
            mapping,
            {"mouthSmileLeft": "mouth_smile_left", "jawOpen": "Jaw.Open"},
        )

    def test_load_animation_validates_weight_count(self):
        data = {
            "schema": "a2f-blendshapes-v1",
            "fps": 60,
            "channels": ["jawOpen"],
            "frames": [{"t": 0, "w": []}],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "weight count"):
                load_animation(path)

    def test_faceit_export_reorders_faceit_left_right_pairs(self):
        channels = list(CORE.FACEIT_ARKIT_CHANNELS)
        channels[21], channels[22] = channels[22], channels[21]
        channels[25], channels[26] = channels[26], channels[25]
        weights = list(range(52))
        data = {
            "schema": "a2f-blendshapes-v1",
            "fps": 60,
            "channels": channels,
            "facsNames": channels,
            "frames": [{"t": 0, "w": weights}],
            "weightMat": [weights],
        }
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.json"
            destination = Path(directory) / "faceit.json"
            source.write_text(json.dumps(data), encoding="utf-8")
            write_faceit_animation(source, destination)
            faceit_data = json.loads(destination.read_text(encoding="ascii"))
        self.assertEqual(faceit_data["weightMat"][0][21:23], [22, 21])
        self.assertEqual(faceit_data["weightMat"][0][25:27], [26, 25])

    def test_json_output_paths_are_persistent_and_unique(self):
        with tempfile.TemporaryDirectory() as directory:
            moment = datetime(2026, 9, 1, 12, 30, 45)
            raw_path, faceit_path = create_json_output_paths(
                directory, "C:/audio/voice:test.mp3", now=moment
            )
            self.assertEqual(raw_path.name, "voice_test_a2f_20260901_123045.json")
            self.assertEqual(faceit_path.name, "voice_test_a2f_20260901_123045_faceit.json")
            raw_path.write_text("existing", encoding="ascii")
            next_raw, _ = create_json_output_paths(
                directory, "C:/audio/voice:test.mp3", now=moment
            )
            self.assertEqual(next_raw.name, "voice_test_a2f_20260901_123045_01.json")


if __name__ == "__main__":
    unittest.main()
