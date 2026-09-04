import json
import os
import sys
import tempfile
from pathlib import Path

import bpy


ADDON_ROOT = Path(os.environ.get("A2F_ADDON_ROOT", Path(__file__).parents[1]))
sys.path.insert(0, str(ADDON_ROOT))

import a2f_local


def main():
    a2f_local.register()
    try:
        mesh = bpy.data.meshes.new("DirectShapeKeyMesh")
        target = bpy.data.objects.new("DirectShapeKeyTarget", mesh)
        bpy.context.collection.objects.link(target)
        target.shape_key_add(name="Basis")
        blink = target.shape_key_add(name="eyeBlinkLeft")

        mouth_mesh = bpy.data.meshes.new("DirectMouthMesh")
        mouth = bpy.data.objects.new("DirectMouthTarget", mouth_mesh)
        bpy.context.collection.objects.link(mouth)
        mouth.shape_key_add(name="Basis")
        jaw = mouth.shape_key_add(name="jawOpen")

        settings = bpy.context.scene.a2f_local
        settings.target = None
        bpy.ops.object.select_all(action="DESELECT")
        target.select_set(True)
        mouth.select_set(True)
        bpy.context.view_layer.objects.active = target
        result = bpy.ops.a2f.add_direct_targets()
        assert result == {"FINISHED"}
        assert [item.object for item in settings.direct_targets] == [target, mouth]
        bpy.ops.a2f.add_direct_targets()
        assert len(settings.direct_targets) == 2, "Duplicate model parts must not be registered"
        settings.animation_handling = "NEW"
        settings.frame_step = 1
        settings.start_frame = 1
        settings.strength = 1.0
        settings.clamp_values = True
        bpy.context.scene.render.fps = 30
        bpy.context.scene.render.fps_base = 1.0

        animation = {
            "schema": "a2f-blendshapes-v1",
            "source": "slot_regression.wav",
            "fps": 30,
            "channels": ["eyeBlinkLeft", "jawOpen"],
            "frames": [
                {"t": 0.0, "w": [0.0, 0.0]},
                {"t": 1.0 / 30.0, "w": [0.75, 0.5]},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            json_path = Path(directory) / "animation.json"
            json_path.write_text(json.dumps(animation), encoding="utf-8")
            a2f_local._apply_animation(bpy.context, json_path)

            original_action = target.data.shape_keys.animation_data.action
            settings.animation_handling = "REPLACE"
            animation["frames"][1]["w"] = [0.25, 0.4]
            json_path.write_text(json.dumps(animation), encoding="utf-8")
            a2f_local._apply_animation(bpy.context, json_path)

        shape_keys = target.data.shape_keys
        bpy.context.scene.frame_set(1)
        first_value = blink.value
        bpy.context.scene.frame_set(2)
        second_value = blink.value
        jaw_value = jaw.value

        assert shape_keys.animation_data is not None
        assert shape_keys.animation_data.action is not None
        assert blink.is_property_set("value"), "Shape Key value is not marked as animated"
        assert abs(first_value - 0.0) < 1e-6
        assert shape_keys.animation_data.action == original_action
        assert mouth.data.shape_keys.animation_data.action == original_action
        assert mouth.data.shape_keys.animation_data.action_slot == shape_keys.animation_data.action_slot
        assert abs(second_value - 0.25) < 1e-6, (
            f"Expected eyeBlinkLeft=0.25 at frame 2, got {second_value}"
        )
        assert abs(jaw_value - 0.4) < 1e-6, f"Expected jawOpen=0.4 at frame 2, got {jaw_value}"
        assert len(original_action.slots) == 1, (
            f"Expected one shared Shape Key slot, got {len(original_action.slots)}"
        )
        slot = shape_keys.animation_data.action_slot
        curves = [
            curve
            for layer in original_action.layers
            for strip in layer.strips
            if strip.type == "KEYFRAME"
            for curve in strip.channelbag(slot).fcurves
            if strip.channelbag(slot) is not None
        ]
        assert len(curves) == 2, f"Expected two Shape Key F-Curves in one slot, got {len(curves)}"
    finally:
        a2f_local.unregister()


if __name__ == "__main__":
    main()
