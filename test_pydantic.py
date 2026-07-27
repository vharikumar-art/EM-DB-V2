from pydantic import BaseModel
from typing import List, Optional

class Template(BaseModel):
    name: str = ""
    subject: str = ""
    body: str = ""
    weight: int = 1

class ProfileUpdate(BaseModel):
    profileName: Optional[str] = None
    templates: Optional[List[Template]] = None

try:
    p = ProfileUpdate.model_validate({"profileName": "VHK", "templates": [{"id": "default", "name": "", "subject": "a", "body": "b"}]})
    print(p.model_dump(exclude_unset=True))
except Exception as e:
    print(repr(e))
