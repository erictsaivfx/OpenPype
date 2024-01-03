from pydantic import Field
from ayon_server.settings import BaseSettingsModel


class ShelvesSettingsModel(BaseSettingsModel):
    _layout = "compact"
    name: str = Field(title="Name")
    value: str = Field(title="Path")


class ZBrushSettings(BaseSettingsModel):
    shelves: list[ShelvesSettingsModel] = Field(
        default_factory=list,
        title="Shelves"
    )


DEFAULT_ZBRUSH_SETTINGS = {
    "shelves": []
}
