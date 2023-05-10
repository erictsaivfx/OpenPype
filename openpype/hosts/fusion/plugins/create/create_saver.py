from copy import deepcopy
import os

from openpype.hosts.fusion.api import (
    get_current_comp,
    comp_lock_and_undo_chunk,
)
from openpype.hosts.fusion.api.lib import get_frame_path

from openpype.lib import (
    BoolDef,
    EnumDef,
)
from openpype.pipeline import (
    legacy_io,
    Creator as NewCreator,
    CreatedInstance,
    Anatomy
)
from openpype.client import (
    get_asset_by_name,
)


class CreateSaver(NewCreator):
    identifier = "io.openpype.creators.fusion.saver"
    label = "Render (saver)"
    name = "render"
    family = "render"
    default_variants = ["Main", "Mask"]
    description = "Fusion Saver to generate image sequence"
    icon = "fa5.eye"

    instance_attributes = [
        "reviewable"
    ]
    default_variants = [
        "Main",
        "Mask"
    ]
    temp_rendering_path_template = (
        "{workdir}/renders/fusion/{subset}/{subset}.{frame}.{ext}")

    def create(self, subset_name, instance_data, pre_create_data):
        # TODO: Add pre_create attributes to choose file format?
        file_format = "OpenEXRFormat"

        comp = get_current_comp()
        with comp_lock_and_undo_chunk(comp):
            args = (-32768, -32768)  # Magical position numbers
            saver = comp.AddTool("Saver", *args)

            instance_data["subset"] = subset_name
            self._update_tool_with_data(saver, data=instance_data)

            saver["OutputFormat"] = file_format

            # Check file format settings are available
            if saver[file_format] is None:
                raise RuntimeError(
                    f"File format is not set to {file_format}, this is a bug"
                )

            # Set file format attributes
            saver[file_format]["Depth"] = 0  # Auto | float16 | float32
            # TODO Is this needed?
            saver[file_format]["SaveAlpha"] = 1

        self._imprint(saver, instance_data)

        # Register the CreatedInstance
        instance = CreatedInstance(
            family=self.family,
            subset_name=subset_name,
            data=instance_data,
            creator=self,
        )

        # Insert the transient data
        instance.transient_data["tool"] = saver

        self._add_instance_to_context(instance)

        return instance

    def collect_instances(self):
        comp = get_current_comp()
        tools = comp.GetToolList(False, "Saver").values()
        for tool in tools:
            data = self.get_managed_tool_data(tool)
            if not data:
                data = self._collect_unmanaged_saver(tool)

            # Add instance
            created_instance = CreatedInstance.from_existing(data, self)

            # Collect transient data
            created_instance.transient_data["tool"] = tool

            self._add_instance_to_context(created_instance)

    def update_instances(self, update_list):
        for created_inst, _changes in update_list:
            new_data = created_inst.data_to_store()
            tool = created_inst.transient_data["tool"]
            self._update_tool_with_data(tool, new_data)
            self._imprint(tool, new_data)

    def remove_instances(self, instances):
        for instance in instances:
            # Remove the tool from the scene

            tool = instance.transient_data["tool"]
            if tool:
                tool.Delete()

            # Remove the collected CreatedInstance to remove from UI directly
            self._remove_instance_from_context(instance)

    def _imprint(self, tool, data):
        # Save all data in a "openpype.{key}" = value data

        active = data.pop("active", None)
        if active is not None:
            # Use active value to set the passthrough state
            tool.SetAttrs({"TOOLB_PassThrough": not active})

        for key, value in data.items():
            tool.SetData(f"openpype.{key}", value)

    def _update_tool_with_data(self, tool, data):
        """Update tool node name and output path based on subset data"""
        if "subset" not in data:
            return

        original_subset = tool.GetData("openpype.subset")
        subset = data["subset"]
        if original_subset != subset:
            self._configure_saver_tool(data, tool, subset)

    def _configure_saver_tool(self, data, tool, subset):
        formatting_data = deepcopy(data)

        # get frame padding from anatomy templates
        anatomy = Anatomy()
        frame_padding = int(
            anatomy.templates["render"].get("frame_padding", 4)
        )

        # Subset change detected
        workdir = os.path.normpath(legacy_io.Session["AVALON_WORKDIR"])
        formatting_data.update({
            "workdir": workdir.replace("\\", "/"),
            "frame": "0" * frame_padding,
            "ext": "exr"
        })

        # build file path to render
        filepath = self.temp_rendering_path_template.format(
            **formatting_data)

        # create directory
        if not os.path.isdir(os.path.dirname(filepath)):
            self.log.warning("Path does not exist! I am creating it.")
            os.makedirs(os.path.dirname(filepath))

        tool["Clip"] = filepath

        # Rename tool
        if tool.Name != subset:
            print(f"Renaming {tool.Name} -> {subset}")
            tool.SetAttrs({"TOOLS_Name": subset})

    def _collect_unmanaged_saver(self, tool):
        # TODO: this should not be done this way - this should actually
        #       get the data as stored on the tool explicitly (however)
        #       that would disallow any 'regular saver' to be collected
        #       unless the instance data is stored on it to begin with

        print("Collecting unmanaged saver..")
        comp = tool.Comp()

        # Allow regular non-managed savers to also be picked up
        project = legacy_io.Session["AVALON_PROJECT"]
        asset = legacy_io.Session["AVALON_ASSET"]
        task = legacy_io.Session["AVALON_TASK"]

        asset_doc = get_asset_by_name(project_name=project, asset_name=asset)

        path = tool["Clip"][comp.TIME_UNDEFINED]
        fname = os.path.basename(path)
        head, _, _ = get_frame_path(fname)

        variant = head.rstrip(".")
        subset = self.get_subset_name(
            variant=variant,
            task_name=task,
            asset_doc=asset_doc,
            project_name=project,
        )

        attrs = tool.GetAttrs()
        passthrough = attrs["TOOLB_PassThrough"]
        return {
            # Required data
            "project": project,
            "asset": asset,
            "subset": subset,
            "task": task,
            "variant": variant,
            "active": not passthrough,
            "family": self.family,
            # Unique identifier for instance and this creator
            "id": "pyblish.avalon.instance",
            "creator_identifier": self.identifier,
        }

    def get_managed_tool_data(self, tool):
        """Return data of the tool if it matches creator identifier"""
        data = tool.GetData("openpype")
        if not isinstance(data, dict):
            return

        required = {
            "id": "pyblish.avalon.instance",
            "creator_identifier": self.identifier,
        }
        for key, value in required.items():
            if key not in data or data[key] != value:
                return

        # Get active state from the actual tool state
        attrs = tool.GetAttrs()
        passthrough = attrs["TOOLB_PassThrough"]
        data["active"] = not passthrough

        return data

    def get_pre_create_attr_defs(self):
        """Settings for create page"""
        attr_defs = [
            self._get_render_target_enum(),
            self._get_reviewable_bool(),
        ]
        return attr_defs

    def get_instance_attr_defs(self):
        """Settings for publish page"""
        attr_defs = [
            self._get_render_target_enum(),
            self._get_reviewable_bool(),
        ]
        return attr_defs

    # These functions below should be moved to another file
    # so it can be used by other plugins. plugin.py ?

    def _get_render_target_enum(self):
        rendering_targets = {
            "local": "Local machine rendering",
            "frames": "Use existing frames",
        }
        if "farm_rendering" in self.instance_attributes:
            rendering_targets["farm"] = "Farm rendering"

        return EnumDef(
            "render_target", items=rendering_targets, label="Render target"
        )

    def _get_reviewable_bool(self):
        return BoolDef(
            "review",
            default=("reviewable" in self.instance_attributes),
            label="Review",
        )

    def apply_settings(
        self,
        project_settings,
        system_settings
    ):
        """Method called on initialization of plugin to apply settings."""

        # plugin settings
        plugin_settings = (
            project_settings["fusion"]["create"][self.__class__.__name__]
        )

        # individual attributes
        self.instance_attributes = plugin_settings.get(
            "instance_attributes") or self.instance_attributes
        self.default_variants = plugin_settings.get(
            "default_variants") or self.default_variants
        self.temp_rendering_path_template = (
            plugin_settings.get("temp_rendering_path_template")
            or self.temp_rendering_path_template
        )
