from pydantic import BaseModel


class FolderSchema(BaseModel):
    folder_name: str


class MoveSchema(BaseModel):
    source_path: str
    source_zone: str
    destination_folder: str


class ClipboardSchema(BaseModel):
    text: str


class RenameSchema(BaseModel):
    zone: str
    item_path: str
    new_name: str
