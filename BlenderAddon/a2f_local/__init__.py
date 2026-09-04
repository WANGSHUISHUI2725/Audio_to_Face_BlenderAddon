bl_info = {
    "name": "Audio2Face Local",
    "author": "WangShuishui",
    "version": (0, 6, 0),
    "blender": (4, 0, 0),
    "location": "3D View > Sidebar > Audio2Face",
    "description": "Generate local Audio2Face facial animation for Faceit or Shape Keys",
    "category": "Animation",
}

import os
import subprocess
import sys
from pathlib import Path

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import AddonPreferences, Operator, Panel, PropertyGroup, UIList

from .core import (
    create_json_output_paths,
    default_workspace_paths,
    resolve_runtime_model,
    resolve_model_mode,
    clamp_lips_closed_action,
    load_animation,
    match_channels,
    write_faceit_animation,
)


def _defaults():
    return default_workspace_paths(__file__)


def _armature_poll(_self, obj):
    return obj is not None and obj.type == "ARMATURE"


def _mesh_poll(_self, obj):
    return obj is not None and obj.type == "MESH"


class A2FPreferences(AddonPreferences):
    bl_idname = __package__

    exporter_path: StringProperty(
        name="Exporter",
        subtype="FILE_PATH",
        default=str(_defaults()["exporter"]),
    )
    model_path: StringProperty(
        name="v2.3 Model",
        subtype="FILE_PATH",
        default=str(_defaults()["model"]),
    )
    diffusion_model_path: StringProperty(
        name="v3.0 Model",
        subtype="FILE_PATH",
        default=str(_defaults()["diffusion_model"]),
    )
    model_mode: EnumProperty(
        name="A2F Model",
        items=(
            ("AUTO", "Auto Detect", "Detect Regression or Diffusion from model.json"),
            ("REGRESSION", "v2.3 Regression", "Use the Audio2Face-3D v2.3 regression model"),
            ("DIFFUSION", "v3.0 Diffusion", "Use the Audio2Face-3D v3.0 diffusion model"),
        ),
        default="AUTO",
    )
    diffusion_identity: EnumProperty(
        name="v3 Identity",
        items=(
            ("0", "Claire", "Use the Claire identity included with v3.0"),
            ("1", "James", "Use the James identity included with v3.0"),
            ("2", "Mark", "Use the Mark identity included with v3.0"),
        ),
        default="2",
    )
    cuda_path: StringProperty(
        name="CUDA",
        subtype="DIR_PATH",
        default=str(_defaults()["cuda"]),
    )
    tensorrt_path: StringProperty(
        name="TensorRT",
        subtype="DIR_PATH",
        default=str(_defaults()["tensorrt"]),
    )
    json_output_path: StringProperty(
        name="Generated JSON Folder",
        subtype="DIR_PATH",
        default=str(_defaults()["json_output"]),
    )
    lips_closed_max: FloatProperty(
        name="v3 Lips Closed Max",
        default=0.5,
        min=0.0,
        max=1.0,
        description="Limit Faceit's c_lips_closed controller when using v3 Diffusion",
    )

    def draw(self, _context):
        layout = self.layout
        layout.prop(self, "exporter_path")
        layout.prop(self, "model_path")
        layout.prop(self, "diffusion_model_path")
        layout.prop(self, "model_mode", expand=True)
        if self.model_mode != "REGRESSION":
            layout.prop(self, "diffusion_identity", expand=True)
            layout.prop(self, "lips_closed_max")
        layout.prop(self, "cuda_path")
        layout.prop(self, "tensorrt_path")
        layout.prop(self, "json_output_path")


class A2FTargetObject(PropertyGroup):
    object: PointerProperty(name="Model Part", type=bpy.types.Object, poll=_mesh_poll)


class A2FSettings(PropertyGroup):
    audio_path: StringProperty(name="Audio", subtype="FILE_PATH")
    last_json_path: StringProperty(name="Last Faceit JSON", subtype="FILE_PATH")
    last_audio_path: StringProperty(name="Last Imported Audio", subtype="FILE_PATH")
    previous_audio_handling: EnumProperty(
        name="Previous Audio",
        items=(
            ("MUTE", "Mute Previous Audio", "Mute the audio strip imported by the previous generation"),
            ("DELETE", "Delete Previous Audio", "Delete the audio strip imported by the previous generation"),
        ),
        default="MUTE",
        description="Choose one action for the audio strip imported by the previous generation",
    )
    animation_handling: EnumProperty(
        name="Animation",
        items=(
            ("REPLACE", "Overwrite Current Animation", "Replace the active facial animation"),
            ("NEW", "New Facial Animation", "Create a separate facial animation action"),
        ),
        default="REPLACE",
    )
    generation_mode: EnumProperty(
        name="Output",
        items=(
            ("ANIMATION", "Generate Animation", "Generate JSON and immediately import the animation"),
            ("JSON", "Generate Faceit JSON", "Generate a persistent JSON file for manual Faceit import"),
        ),
        default="ANIMATION",
    )
    output_mode: EnumProperty(
        name="Target",
        items=(
            ("FACEIT", "Faceit Control Rig", "Import ARKit animation through Faceit"),
            ("DIRECT", "Shape Keys", "Write animation directly to matching Shape Keys"),
        ),
        default="FACEIT",
    )
    target: PointerProperty(name="Face Mesh", type=bpy.types.Object)
    direct_targets: CollectionProperty(type=A2FTargetObject)
    direct_target_index: IntProperty(default=0, min=0)
    faceit_control_rig: PointerProperty(
        name="Faceit Control Rig",
        type=bpy.types.Object,
        poll=_armature_poll,
    )
    start_frame: IntProperty(name="Start", default=1, min=-1048574, max=1048574)
    max_duration_seconds: FloatProperty(
        name="Max Seconds",
        default=60.0,
        min=1.0,
        max=600.0,
        description="Reject audio longer than this duration; 60 seconds is about 1800 frames at 30 FPS",
    )
    bake_to_control_rig: BoolProperty(
        name="Bake to Faceit Control Rig",
        default=True,
        description="Animate the Faceit control rig instead of driver-controlled Shape Keys",
    )
    strength: FloatProperty(name="Strength", default=1.0, min=0.0, max=3.0)
    frame_step: IntProperty(name="Key Every", default=1, min=1, max=12)
    clamp_values: BoolProperty(name="Clamp 0-1", default=True)
    generation_in_progress: BoolProperty(name="Generation In Progress", default=False, options={"HIDDEN"})
    generation_status: StringProperty(name="Generation Status", default="", options={"HIDDEN"})


def _preferences(context):
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


def _shape_keys(target):
    data = getattr(target, "data", None)
    return getattr(data, "shape_keys", None)


def _direct_targets(settings):
    targets = []
    seen = set()
    for item in settings.direct_targets:
        target = item.object
        if target is not None and target.type == "MESH" and target.as_pointer() not in seen:
            seen.add(target.as_pointer())
            targets.append(target)
    # Keep files made with the single-target preview usable until an object is registered.
    if not targets and settings.target is not None and settings.target.type == "MESH":
        targets.append(settings.target)
    return targets


def _is_faceit_control_rig(obj):
    if obj is None or obj.type != "ARMATURE":
        return False
    return (
        "ctrl_rig_id" in obj
        or "ctrl_rig_version" in obj
        or "FaceitControlRig" in obj.name
        or bool(getattr(obj, "faceit_crig_targets", None))
    )


def _find_faceit_control_rig(context):
    settings = context.scene.a2f_local
    candidates = (
        settings.faceit_control_rig,
        getattr(context.scene, "faceit_control_armature", None),
        context.active_object,
    )
    for candidate in candidates:
        if candidate is not None and (
            candidate is settings.faceit_control_rig or _is_faceit_control_rig(candidate)
        ):
            return candidate
    return next((obj for obj in context.scene.objects if _is_faceit_control_rig(obj)), None)


def _faceit_control_rig_connected(context, rig):
    if rig is None:
        return False
    for obj in context.scene.objects:
        shape_keys = _shape_keys(obj)
        animation_data = getattr(shape_keys, "animation_data", None)
        for fcurve in getattr(animation_data, "drivers", ()):
            for variable in fcurve.driver.variables:
                if any(target.id == rig for target in variable.targets):
                    return True
    return False


def _activate_faceit_control_rig(context):
    rig = _find_faceit_control_rig(context)
    if rig is None:
        raise ValueError("No FaceitControlRig was found in the scene")
    if not hasattr(context.scene, "faceit_control_armature"):
        raise ValueError("Faceit is not enabled; its scene properties are unavailable")
    context.scene.a2f_local.faceit_control_rig = rig
    context.scene.faceit_control_armature = rig
    return rig


def _finalize_fcurves(action):
    if action is None:
        return
    for curve in getattr(action, "fcurves", ()):
        for keyframe in curve.keyframe_points:
            keyframe.interpolation = "LINEAR"
        curve.update()


def _handle_previous_audio(context, settings):
    previous = str(getattr(settings, "last_audio_path", "") or "")
    sequence_editor = getattr(context.scene, "sequence_editor", None)
    if sequence_editor is None:
        return
    def normalized_path(value):
        return os.path.normcase(os.path.abspath(bpy.path.abspath(str(value))))

    previous_normalized = normalized_path(previous) if previous else None
    for strip in list(getattr(sequence_editor, "sequences_all", ())):
        sound = getattr(strip, "sound", None)
        filepath = getattr(sound, "filepath", "") if sound is not None else ""
        candidates = (filepath, str(getattr(strip, "filepath", "") or ""))
        normalized = {normalized_path(value) for value in candidates if value}
        # Prefer the exact path recorded by the previous generation. If that
        # setting is unavailable (e.g. an older scene), fall back to Faceit's
        # marker so the first run after upgrading can still clean up its strip.
        matches_previous = previous_normalized is not None and previous_normalized in normalized
        marked_fallback = previous_normalized is None and getattr(strip, "faceit_audio", False)
        if not (matches_previous or marked_fallback):
            continue
        if settings.previous_audio_handling == "DELETE":
            collection = getattr(sequence_editor, "sequences", None)
            if collection is None:
                collection = getattr(sequence_editor, "strips", None)
            if collection is not None:
                collection.remove(strip)
        elif settings.previous_audio_handling == "MUTE":
            strip.mute = True


def _run_faceit_import(**properties):
    operator_class = None
    for module in tuple(sys.modules.values()):
        candidate = getattr(module, "FACEIT_OT_ImportA2FMocap", None)
        if candidate is not None and getattr(candidate, "bl_idname", None) == "faceit.import_a2f_mocap":
            operator_class = candidate
            break
    if operator_class is None:
        raise ValueError("Could not locate Faceit's Audio2Face importer class")

    original_execute = operator_class.execute

    def execute_with_engine_settings(operator, context):
        if getattr(operator, "engine_settings", None) is None:
            operator._get_engine_specific_settings(context)
        if getattr(operator, "engine_settings", None) is None:
            operator.report({"ERROR"}, "Faceit A2F engine settings are unavailable")
            return {"CANCELLED"}
        return original_execute(operator, context)

    operator_class.execute = execute_with_engine_settings
    try:
        return bpy.ops.faceit.import_a2f_mocap("EXEC_DEFAULT", **properties)
    finally:
        operator_class.execute = original_execute


def _shape_key_fcurves(shape_keys, action, replace_existing, existing_slot=None):
    """Bind layered Action curves to the Shape Key datablock on Blender 4.4+."""
    animation_data = shape_keys.animation_data
    if not hasattr(action, "slots") or not hasattr(animation_data, "action_slot"):
        if replace_existing:
            action.fcurves.clear()
        return action.fcurves

    slot = existing_slot if replace_existing else None
    if slot is None or slot.id_data != action:
        # An empty legacy Action can be converted to a layered Action after its
        # unbound legacy curves have been removed.
        if replace_existing and getattr(action, "is_action_legacy", False):
            action.fcurves.clear()
        slot = action.slots.new("KEY", shape_keys.name)

    animation_data.action_slot = slot
    channelbag = None
    for layer in action.layers:
        for strip in layer.strips:
            if strip.type == "KEYFRAME":
                channelbag = strip.channelbag(slot)
                if channelbag is not None:
                    break
        if channelbag is not None:
            break

    if channelbag is None:
        layer = action.layers[0] if action.layers else action.layers.new("Audio2Face")
        strip = next(
            (candidate for candidate in layer.strips if candidate.type == "KEYFRAME"),
            None,
        )
        if strip is None:
            strip = layer.strips.new(type="KEYFRAME")
        channelbag = strip.channelbag(slot, ensure=True)
    elif replace_existing:
        channelbag.fcurves.clear()

    return channelbag.fcurves


def _apply_animation(context, json_path):
    settings = context.scene.a2f_local
    animation = load_animation(json_path)
    targets = _direct_targets(settings)
    if not targets:
        raise ValueError("No mesh objects are registered for Shape Key animation")

    target_data = []
    seen_shape_keys = set()
    for target in targets:
        shape_keys = _shape_keys(target)
        if shape_keys is None:
            raise ValueError(f'Registered model "{target.name}" has no Shape Keys')
        pointer = shape_keys.as_pointer()
        if pointer in seen_shape_keys:
            continue
        seen_shape_keys.add(pointer)
        mapping = match_channels(animation["channels"], shape_keys.key_blocks.keys())
        if mapping:
            target_data.append((target, shape_keys, mapping))
    if not target_data:
        raise ValueError("No Audio2Face channels match the registered models' Shape Keys")

    for _target, shape_keys, _mapping in target_data:
        shape_keys.animation_data_create()
    action_name = f"A2F_{Path(animation.get('source', 'Audio')).stem}"
    replace_requested = settings.animation_handling == "REPLACE"
    action = next(
        (
            shape_keys.animation_data.action
            for _target, shape_keys, _mapping in target_data
            if replace_requested and shape_keys.animation_data.action is not None
        ),
        None,
    )
    if action is not None:
        action.name = action_name
    else:
        action = bpy.data.actions.new(action_name)

    scene_fps = context.scene.render.fps / context.scene.render.fps_base
    source_fps = float(animation["fps"])
    source_indices = {name: index for index, name in enumerate(animation["channels"])}

    def write_curves(fcurves, mapping_items):
        channel_frames = {target_name: [] for _source_name, target_name in mapping_items}
        for index, frame in enumerate(animation["frames"]):
            if index % settings.frame_step != 0 and index + 1 != len(animation["frames"]):
                continue
            timeline_frame = settings.start_frame + index * scene_fps / source_fps
            for source_name, target_name in mapping_items:
                value = float(frame["w"][source_indices[source_name]]) * settings.strength
                if settings.clamp_values:
                    value = min(1.0, max(0.0, value))
                channel_frames[target_name].append((timeline_frame, value))

        for target_name, points in channel_frames.items():
            escaped_name = target_name.replace("\\", "\\\\").replace('"', '\\"')
            curve = fcurves.new(
                data_path=f'key_blocks["{escaped_name}"].value',
                index=0,
            )
            curve.keyframe_points.add(len(points))
            coordinates = [coordinate for point in points for coordinate in point]
            curve.keyframe_points.foreach_set("co", coordinates)
            for keyframe in curve.keyframe_points:
                keyframe.interpolation = "LINEAR"
            curve.update()

    layered_action = hasattr(action, "slots")
    mapping_items = list(
        dict.fromkeys(
            pair
            for _target, _shape_keys, mapping in target_data
            for pair in mapping.items()
        )
    )
    if layered_action:
        shared_slot = next(
            (
                shape_keys.animation_data.action_slot
                for _target, shape_keys, _mapping in target_data
                if shape_keys.animation_data.action == action
                and shape_keys.animation_data.action_slot is not None
            ),
            None,
        )
        primary_shape_keys = target_data[0][1]
        primary_shape_keys.animation_data.action = action
        replace_slot = replace_requested and shared_slot is not None
        fcurves = _shape_key_fcurves(
            primary_shape_keys, action, replace_slot, existing_slot=shared_slot
        )
        shared_slot = primary_shape_keys.animation_data.action_slot
        for _target, shape_keys, _mapping in target_data:
            shape_keys.animation_data.action = action
            shape_keys.animation_data.action_slot = shared_slot
        write_curves(fcurves, mapping_items)
    else:
        if replace_requested:
            action.fcurves.clear()
        for _target, shape_keys, mapping in target_data:
            shape_keys.animation_data.action = action
        write_curves(action.fcurves, mapping_items)

    context.scene.frame_start = min(context.scene.frame_start, settings.start_frame)
    last_frame = settings.start_frame + (len(animation["frames"]) - 1) * scene_fps / source_fps
    context.scene.frame_end = max(context.scene.frame_end, int(round(last_frame)))
    matched_channels = sum(len(mapping) for _target, _shape_keys, mapping in target_data)
    return matched_channels, len(animation["frames"]), action.name


def _apply_with_faceit(context, faceit_json_path, audio_path):
    settings = context.scene.a2f_local
    prefs = _preferences(context)
    rig = _activate_faceit_control_rig(context)
    engine_collection = getattr(context.scene, "faceit_live_mocap_settings", None)
    if engine_collection is None:
        raise ValueError("Faceit is not enabled or its mocap settings are unavailable")
    engine_settings = engine_collection.get("A2F")
    if engine_settings is None:
        raise ValueError("Faceit A2F mocap settings are not initialized; reload the Blender file")
    if settings.bake_to_control_rig and not _faceit_control_rig_connected(context, rig):
        raise ValueError("FaceitControlRig was found but is not connected to Shape Key drivers")

    engine_settings.filename = str(faceit_json_path)
    engine_settings.audio_filename = str(audio_path)
    action_name = f"A2F_{audio_path.stem}"
    rig_animation_data = getattr(rig, "animation_data", None)
    if settings.animation_handling == "NEW" and hasattr(context.scene, "faceit_mocap_action"):
        context.scene.faceit_mocap_action = None
    if settings.animation_handling == "NEW" and rig_animation_data is not None:
        # Faceit reuses the control-rig action whenever one is active. Clear it
        # so its bake step creates a genuinely new action and action slot.
        rig_animation_data.action = None
    result = _run_faceit_import(
        a2f_solver="ARKIT",
        frame_start=settings.start_frame,
        record_frame_rate=60.0,
        animate_shapes=True,
        bake_to_control_rig=settings.bake_to_control_rig,
        overwrite_method="REPLACE",
        set_scene_frame_range=True,
        load_audio_file=True,
        # Faceit uses this value as the sound-strip name. Its invoke() method
        # normally fills it in, but this addon intentionally executes the
        # operator directly after showing its own confirmation dialog.
        audio_filename=audio_path.name,
        remove_audio_tracks_with_same_name=False,
        new_action_name=action_name,
    )
    if "FINISHED" not in result:
        raise ValueError("Faceit cancelled the ARKit mocap import")
    _finalize_fcurves(getattr(getattr(rig, "animation_data", None), "action", None))
    if prefs is not None and prefs.model_mode != "REGRESSION":
        clamp_lips_closed_action(
            getattr(getattr(rig, "animation_data", None), "action", None),
            prefs.lips_closed_max,
        )
    animation = load_animation(faceit_json_path)
    return len(animation["channels"]), len(animation["frames"]), action_name


class A2F_OT_detect_faceit_rig(Operator):
    bl_idname = "a2f.detect_faceit_rig"
    bl_label = "Detect Faceit Control Rig"
    bl_description = "Find FaceitControlRig and register it in the Faceit scene settings"

    def execute(self, context):
        try:
            rig = _activate_faceit_control_rig(context)
        except ValueError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        connected = _faceit_control_rig_connected(context, rig)
        status = "connected to Shape Keys" if connected else "found, but drivers are not connected"
        self.report({"INFO" if connected else "WARNING"}, f"{rig.name}: {status}")
        return {"FINISHED"}


class A2F_OT_open_json_folder(Operator):
    bl_idname = "a2f.open_json_folder"
    bl_label = "Open JSON Folder"
    bl_description = "Open the folder containing generated Audio2Face JSON files"

    def execute(self, context):
        prefs = _preferences(context)
        if prefs is None:
            return {"CANCELLED"}
        directory = Path(bpy.path.abspath(prefs.json_output_path))
        directory.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.path_open(filepath=str(directory))
        return {"FINISHED"}


class A2F_UL_direct_targets(UIList):
    def draw_item(
        self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index
    ):
        target = item.object
        icon = "MESH_DATA" if target is not None else "ERROR"
        layout.prop(item, "object", text="", emboss=False, icon=icon)


class A2F_OT_add_direct_targets(Operator):
    bl_idname = "a2f.add_direct_targets"
    bl_label = "Add Selected Models"
    bl_description = "Register all selected mesh objects for direct Shape Key animation"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.a2f_local
        registered = {
            item.object.as_pointer()
            for item in settings.direct_targets
            if item.object is not None
        }
        selected_meshes = [obj for obj in context.selected_objects if obj.type == "MESH"]
        added = 0
        for obj in selected_meshes:
            if obj.as_pointer() in registered:
                continue
            item = settings.direct_targets.add()
            item.object = obj
            registered.add(obj.as_pointer())
            added += 1
        if not selected_meshes:
            self.report({"WARNING"}, "Select one or more mesh objects first")
            return {"CANCELLED"}
        if added == 0:
            self.report({"INFO"}, "All selected mesh objects are already registered")
        else:
            settings.direct_target_index = len(settings.direct_targets) - 1
            self.report({"INFO"}, f"Registered {added} model part(s)")
        return {"FINISHED"}


class A2F_OT_remove_direct_target(Operator):
    bl_idname = "a2f.remove_direct_target"
    bl_label = "Remove Model"
    bl_description = "Remove the active model part from the direct animation list"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, "a2f_local", None)
        return settings is not None and bool(settings.direct_targets)

    def execute(self, context):
        settings = context.scene.a2f_local
        index = min(settings.direct_target_index, len(settings.direct_targets) - 1)
        settings.direct_targets.remove(index)
        settings.direct_target_index = min(index, max(0, len(settings.direct_targets) - 1))
        return {"FINISHED"}


class A2F_OT_clear_direct_targets(Operator):
    bl_idname = "a2f.clear_direct_targets"
    bl_label = "Clear Models"
    bl_description = "Remove all model parts from the direct animation list"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, "a2f_local", None)
        return settings is not None and bool(settings.direct_targets)

    def execute(self, context):
        context.scene.a2f_local.direct_targets.clear()
        context.scene.a2f_local.direct_target_index = 0
        return {"FINISHED"}


class A2F_OT_generate(Operator):
    bl_idname = "a2f.generate_animation"
    bl_label = "Generate Facial Animation"
    bl_description = "Run Audio2Face locally and apply the result to matching Shape Keys"
    bl_options = {"REGISTER", "UNDO"}

    _process = None
    _timer = None
    _output_path = None
    _faceit_output_path = None
    _audio_path = None
    confirmation_handling: EnumProperty(
        name="Animation Result",
        items=(
            ("REPLACE", "Overwrite Animation and Slot", "Replace the current facial animation and slot"),
            ("NEW", "New Animation and Slot", "Create a new facial animation and slot"),
        ),
        default="REPLACE",
        options={"SKIP_SAVE"},
    )

    def invoke(self, context, event):
        settings = context.scene.a2f_local
        self.confirmation_handling = settings.animation_handling
        if settings.generation_mode == "ANIMATION":
            return context.window_manager.invoke_props_dialog(self, width=420)
        return self.execute(context)

    def draw(self, context):
        settings = context.scene.a2f_local
        if settings.generation_mode == "ANIMATION":
            self.layout.label(text="Choose how to handle the current facial animation:")
            self.layout.prop(self, "confirmation_handling", expand=True)

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, "a2f_local", None)
        return settings is not None and not settings.generation_in_progress and bool(settings.audio_path) and (
            settings.generation_mode == "JSON"
            or settings.output_mode == "FACEIT"
            or bool(_direct_targets(settings))
        )

    def execute(self, context):
        settings = context.scene.a2f_local
        if settings.generation_mode == "ANIMATION":
            settings.animation_handling = self.confirmation_handling
        prefs = _preferences(context)
        if prefs is None:
            self.report({"ERROR"}, "Audio2Face preferences are unavailable")
            return {"CANCELLED"}

        exporter = Path(bpy.path.abspath(prefs.exporter_path))
        regression_model = Path(bpy.path.abspath(prefs.model_path))
        diffusion_model = Path(bpy.path.abspath(prefs.diffusion_model_path))
        if prefs.model_mode == "DIFFUSION":
            selected_model = diffusion_model
            generated_model = Path(_defaults()["generated_diffusion_model"])
        elif prefs.model_mode == "REGRESSION":
            selected_model = regression_model
            generated_model = Path(_defaults()["generated_regression_model"])
        elif regression_model.is_file():
            selected_model = regression_model
            generated_model = Path(_defaults()["generated_regression_model"])
        else:
            selected_model = diffusion_model
            generated_model = Path(_defaults()["generated_diffusion_model"])
        audio = Path(bpy.path.abspath(settings.audio_path))
        for label, path in (("Exporter", exporter), ("Audio", audio)):
            if not path.is_file():
                self.report({"ERROR"}, f"{label} file not found: {path}")
                return {"CANCELLED"}
        _handle_previous_audio(context, settings)
        try:
            model = resolve_runtime_model(selected_model, generated_model)
            model_mode = resolve_model_mode(model, prefs.model_mode)
        except ValueError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        if (
            settings.generation_mode == "ANIMATION"
            and settings.output_mode == "DIRECT"
            and not _direct_targets(settings)
        ):
            self.report({"ERROR"}, "Register at least one mesh object")
            return {"CANCELLED"}
        missing_shape_keys = [
            target.name for target in _direct_targets(settings) if _shape_keys(target) is None
        ]
        if settings.generation_mode == "ANIMATION" and settings.output_mode == "DIRECT" and missing_shape_keys:
            self.report(
                {"ERROR"},
                "Registered models without Shape Keys: " + ", ".join(missing_shape_keys),
            )
            return {"CANCELLED"}
        if settings.generation_mode == "ANIMATION" and settings.output_mode == "FACEIT":
            try:
                rig = _activate_faceit_control_rig(context)
            except ValueError as error:
                self.report({"ERROR"}, str(error))
                return {"CANCELLED"}
            if settings.bake_to_control_rig and not _faceit_control_rig_connected(context, rig):
                self.report({"ERROR"}, "FaceitControlRig is not connected to Shape Key drivers")
                return {"CANCELLED"}

        output_dir = Path(bpy.path.abspath(prefs.json_output_path))
        try:
            self._output_path, self._faceit_output_path = create_json_output_paths(
                output_dir, audio
            )
        except OSError as error:
            self.report({"ERROR"}, f"Could not create JSON output folder: {error}")
            return {"CANCELLED"}
        self._audio_path = audio
        environment = os.environ.copy()
        runtime_paths = [
            str(exporter.parent),
            str(Path(bpy.path.abspath(prefs.cuda_path)) / "bin"),
            str(Path(bpy.path.abspath(prefs.tensorrt_path)) / "lib"),
        ]
        environment["PATH"] = os.pathsep.join(runtime_paths + [environment.get("PATH", "")])
        command = [
            str(exporter),
            "--model", str(model),
            "--audio", str(audio),
            "--output", str(self._output_path),
            "--max-duration", str(settings.max_duration_seconds),
        ]
        # Keep the packaged v2 exporter backward-compatible; the v3 argument is
        # added only when the diffusion-capable exporter is being used.
        if model_mode == "DIFFUSION":
            command.extend(["--model-type", "diffusion", "--identity", prefs.diffusion_identity])
        try:
            self._process = subprocess.Popen(
                command,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as error:
            settings.generation_in_progress = False
            settings.generation_status = ""
            self.report({"ERROR"}, f"Could not start exporter: {error}")
            return {"CANCELLED"}

        settings.generation_in_progress = True
        settings.generation_status = (
            "New animation is generating..."
            if settings.animation_handling == "NEW"
            else "Animation overwrite is generating..."
        )
        self._timer = context.window_manager.event_timer_add(0.25, window=context.window)
        context.window_manager.modal_handler_add(self)
        context.window.cursor_set("WAIT")
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "ESC":
            self._finish(context)
            if self._process and self._process.poll() is None:
                self._process.terminate()
            settings = context.scene.a2f_local
            settings.generation_in_progress = False
            settings.generation_status = ""
            self.report({"WARNING"}, "Audio2Face generation cancelled")
            return {"CANCELLED"}
        if event.type != "TIMER" or self._process.poll() is None:
            return {"PASS_THROUGH"}

        stdout, stderr = self._process.communicate()
        return_code = self._process.returncode
        self._finish(context)
        if return_code != 0:
            message = (stderr or stdout or "Exporter failed").strip().splitlines()[-1]
            settings = context.scene.a2f_local
            settings.generation_in_progress = False
            settings.generation_status = ""
            self.report({"ERROR"}, message[:900])
            return {"CANCELLED"}
        try:
            write_faceit_animation(self._output_path, self._faceit_output_path)
            settings = context.scene.a2f_local
            settings.last_json_path = str(self._faceit_output_path)
            if settings.generation_mode == "JSON":
                settings.generation_in_progress = False
                settings.generation_status = ""
                self.report({"INFO"}, f"Faceit JSON created: {self._faceit_output_path}")
                return {"FINISHED"}
            if settings.output_mode == "FACEIT":
                channel_count, frame_count, action_name = _apply_with_faceit(
                    context, self._faceit_output_path, self._audio_path
                )
            else:
                channel_count, frame_count, action_name = _apply_animation(context, self._output_path)
            settings.last_audio_path = str(self._audio_path)
        except Exception as error:
            settings = context.scene.a2f_local
            settings.generation_in_progress = False
            settings.generation_status = ""
            self.report({"ERROR"}, f"Could not apply animation: {error}")
            return {"CANCELLED"}
        settings.generation_in_progress = False
        settings.generation_status = ""
        self.report(
            {"INFO"},
            f"Applied {frame_count} source frames across {channel_count} facial channels ({action_name})",
        )
        return {"FINISHED"}

    def _finish(self, context):
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        context.window.cursor_set("DEFAULT")

    def cancel(self, context):
        self._finish(context)
        if self._process and self._process.poll() is None:
            self._process.terminate()
        settings = context.scene.a2f_local
        settings.generation_in_progress = False
        settings.generation_status = ""


class A2F_PT_panel(Panel):
    bl_label = "Audio2Face"
    bl_idname = "DATA_PT_a2f_local"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Audio2Face"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.a2f_local
        prefs = _preferences(context)
        layout.prop(settings, "audio_path")
        layout.prop(settings, "previous_audio_handling", expand=True)
        if prefs is not None:
            layout.prop(prefs, "model_mode", expand=True)
            if prefs.model_mode != "REGRESSION":
                layout.prop(prefs, "diffusion_identity", expand=True)
        layout.prop(settings, "generation_mode", expand=True)
        if settings.generation_mode == "ANIMATION":
            layout.prop(settings, "output_mode", expand=True)
            if settings.output_mode == "FACEIT":
                layout.prop(settings, "faceit_control_rig")
                rig = _find_faceit_control_rig(context)
                row = layout.row(align=True)
                row.operator("a2f.detect_faceit_rig", icon="FILE_REFRESH")
                if rig is not None:
                    connected = _faceit_control_rig_connected(context, rig)
                    icon = "CHECKMARK" if connected else "ERROR"
                    layout.label(text=f"{rig.name}: {'Connected' if connected else 'Not connected'}", icon=icon)
                layout.prop(settings, "bake_to_control_rig")
            else:
                layout.label(text="Registered Model Parts")
                row = layout.row()
                row.template_list(
                    "A2F_UL_direct_targets",
                    "",
                    settings,
                    "direct_targets",
                    settings,
                    "direct_target_index",
                    rows=3,
                )
                controls = row.column(align=True)
                controls.operator("a2f.add_direct_targets", text="", icon="ADD")
                controls.operator("a2f.remove_direct_target", text="", icon="REMOVE")
                controls.separator()
                controls.operator("a2f.clear_direct_targets", text="", icon="TRASH")
                layout.operator("a2f.add_direct_targets", icon="RESTRICT_SELECT_OFF")
        if settings.generation_mode == "ANIMATION":
            row = layout.row(align=True)
            row.prop(settings, "start_frame")
            if settings.output_mode == "DIRECT":
                row.prop(settings, "frame_step")
        layout.prop(settings, "max_duration_seconds")
        if settings.generation_mode == "ANIMATION" and settings.output_mode == "DIRECT":
            layout.prop(settings, "strength")
            layout.prop(settings, "clamp_values")
        button_icon = "PLAY" if settings.generation_mode == "ANIMATION" else "FILE_TICK"
        button_text = "Generate Animation" if settings.generation_mode == "ANIMATION" else "Generate Faceit JSON"
        if settings.generation_in_progress:
            layout.label(text=settings.generation_status or "Animation is generating...", icon="TIME")
            row = layout.row()
            row.enabled = False
            row.operator("a2f.generate_animation", text="Generating...", icon="TIME")
        else:
            layout.operator("a2f.generate_animation", text=button_text, icon=button_icon)
        if settings.last_json_path:
            layout.prop(settings, "last_json_path", text="Last JSON")
        layout.operator("a2f.open_json_folder", icon="FILE_FOLDER")


CLASSES = (
    A2FPreferences,
    A2FTargetObject,
    A2FSettings,
    A2F_OT_detect_faceit_rig,
    A2F_OT_open_json_folder,
    A2F_UL_direct_targets,
    A2F_OT_add_direct_targets,
    A2F_OT_remove_direct_target,
    A2F_OT_clear_direct_targets,
    A2F_OT_generate,
    A2F_PT_panel,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.a2f_local = PointerProperty(type=A2FSettings)


def unregister():
    del bpy.types.Scene.a2f_local
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
