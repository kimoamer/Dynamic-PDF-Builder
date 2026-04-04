from abc import ABC, abstractmethod
from ..builder import DocumentBuilder

class BaseTemplate(ABC):
    def __init__(self, theme: str = "claude"):
        self.builder = DocumentBuilder(theme=theme)
        
    @abstractmethod
    def build(self) -> DocumentBuilder:
        pass
        
    def render(self, output: str):
        self.build().render(output)
