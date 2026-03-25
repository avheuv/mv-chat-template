import os
import yaml
from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict

class UIInputConfig(BaseModel):
    id: str
    label: str
    type: str = "text" # can be "text" or "select"
    placeholder: Optional[str] = ""
    options: Optional[List[Dict[str, str]]] = None # [{label: "Math", value: "math"}]

class PrototypeUIConfig(BaseModel):
    title: str = "Chat"
    subtitle: str = ""
    placeholder: str = "Type your message..."
    readonly: bool = False
    inputs: List[UIInputConfig] = Field(default_factory=lambda: [UIInputConfig(id="user_id", label="Student Code")])

class PrototypeConfig(BaseModel):
    id: str
    name: str
    description: Optional[str] = ""
    systemPrompt: str
    initialMessagePrompt: Optional[str] = None
    model: str = "gpt-4o"
    temperature: float = 0.7
    maxTokens: int = 1000
    contextSources: List[str] = []
    outputSpec: Optional[Dict[str, Any]] = None
    saveHandler: Optional[str] = None
    ui: PrototypeUIConfig = Field(default_factory=PrototypeUIConfig)

class PrototypeLoader:
    def __init__(self, prototypes_dir: str = "prototypes"): # changed default path relative to main
        self.prototypes_dir = os.path.join(os.path.dirname(__file__), "..", "..", prototypes_dir)
        self.prototypes: Dict[str, PrototypeConfig] = {}
        self.load_all()

    def load_all(self):
        if not os.path.exists(self.prototypes_dir):
            os.makedirs(self.prototypes_dir, exist_ok=True)
            return

        for filename in os.listdir(self.prototypes_dir):
            if filename.endswith(".yaml") or filename.endswith(".yml"):
                filepath = os.path.join(self.prototypes_dir, filename)
                with open(filepath, 'r') as f:
                    try:
                        data = yaml.safe_load(f)
                        if "id" not in data:
                            data["id"] = filename.rsplit(".", 1)[0]
                        prototype = PrototypeConfig(**data)
                        self.prototypes[prototype.id] = prototype
                    except Exception as e:
                        print(f"Error loading prototype {filename}: {e}")

    def get_prototype(self, prototype_id: str) -> Optional[PrototypeConfig]:
        return self.prototypes.get(prototype_id)

    def get_all(self) -> List[PrototypeConfig]:
        return list(self.prototypes.values())

prototype_loader = PrototypeLoader()
