"""ZBrush Addon Module"""
from typing import Type

from ayon_server.addons import BaseServerAddon

from .settings.main import ZBrushSettings, DEFAULT_ZBRUSH_SETTINGS
from .version import __version__


class ZBrushAddon(BaseServerAddon):
    name = "zbrush"
    title = "ZBrush"
    version = __version__
    settings_model: Type[ZBrushSettings] = ZBrushSettings

    async def get_default_settings(self):
        settings_model_cls = self.get_settings_model()
        return settings_model_cls(**DEFAULT_ZBRUSH_SETTINGS)
