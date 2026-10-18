"""
TaskMaster - Plugin System
Extensible plugin architecture for custom task types and file processors.
"""
import importlib
import inspect
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

@dataclass
class PluginInfo:
    """Plugin metadata."""
    name: str
    version: str
    author: str
    description: str
    entry_point: str
    dependencies: List[str]

class TaskPlugin(ABC):
    """Base class for task plugins."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Plugin name."""
        pass

    @abstractmethod
    def execute(self, **kwargs) -> Any:
        """Execute the plugin task."""
        pass

    @abstractmethod
    def validate_config(self, config: Dict[str, Any]) -> bool:
        """Validate plugin configuration."""
        pass

    def get_description(self) -> str:
        """Get plugin description."""
        return self.__doc__ or "No description"

class FileProcessorPlugin(ABC):
    """Base class for file processor plugins."""

    @property
    @abstractmethod
    def supported_extensions(self) -> List[str]:
        """List of supported file extensions."""
        pass

    @abstractmethod
    def process(self, file_path: Path, **kwargs) -> Dict[str, Any]:
        """Process a file and return metadata."""
        pass

    @abstractmethod
    def extract_content(self, file_path: Path) -> str:
        """Extract text content from file."""
        pass

class PluginManager:
    """Manages plugin loading and registration."""

    def __init__(self, plugin_dir: Optional[Path] = None):
        self.plugin_dir = plugin_dir or Path(__file__).parent
        self.task_plugins: Dict[str, TaskPlugin] = {}
        self.file_plugins: Dict[str, FileProcessorPlugin] = {}
        self._discover_plugins()

    def _discover_plugins(self):
        """Auto-discover plugins from plugin directory."""
        if not self.plugin_dir.exists():
            return

        for file_path in self.plugin_dir.glob("*.py"):
            if file_path.name.startswith("_"):
                continue

            try:
                self._load_plugin_from_file(file_path)
            except Exception as e:
                print(f"Failed to load plugin {file_path}: {e}")

    def _load_plugin_from_file(self, file_path: Path):
        """Load a plugin from a Python file."""
        spec = importlib.util.spec_from_file_location(
            file_path.stem, str(file_path)
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Find plugin classes
        for name, obj in inspect.getmembers(module):
            if inspect.isclass(obj) and issubclass(obj, TaskPlugin) and obj != TaskPlugin:
                instance = obj()
                self.register_task_plugin(instance)

            if inspect.isclass(obj) and issubclass(obj, FileProcessorPlugin) and obj != FileProcessorPlugin:
                instance = obj()
                self.register_file_plugin(instance)

    def register_task_plugin(self, plugin: TaskPlugin) -> None:
        """Register a task plugin."""
        self.task_plugins[plugin.name] = plugin
        print(f"Registered task plugin: {plugin.name}")

    def register_file_plugin(self, plugin: FileProcessorPlugin) -> None:
        """Register a file processor plugin."""
        self.file_plugins[plugin.name] = plugin
        print(f"Registered file plugin: {plugin.name}")

    def get_task_plugin(self, name: str) -> Optional[TaskPlugin]:
        """Get a task plugin by name."""
        return self.task_plugins.get(name)

    def get_file_plugin_for_extension(self, ext: str) -> Optional[FileProcessorPlugin]:
        """Get a file plugin that supports the given extension."""
        for plugin in self.file_plugins.values():
            if ext.lower() in [e.lower() for e in plugin.supported_extensions]:
                return plugin
        return None

    def list_plugins(self) -> Dict[str, List[str]]:
        """List all registered plugins."""
        return {
            "task_plugins": list(self.task_plugins.keys()),
            "file_plugins": list(self.file_plugins.keys()),
        }

# Example built-in plugins
class ImageProcessorPlugin(FileProcessorPlugin):
    """Process image files and extract metadata."""

    @property
    def supported_extensions(self) -> List[str]:
        return [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"]

    @property
    def name(self) -> str:
        return "image_processor"

    def process(self, file_path: Path, **kwargs) -> Dict[str, Any]:
        """Extract image metadata."""
        try:
            from PIL import Image
            with Image.open(file_path) as img:
                return {
                    "width": img.width,
                    "height": img.height,
                    "format": img.format,
                    "mode": img.mode,
                    "size_bytes": file_path.stat().st_size,
                }
        except ImportError:
            return {"error": "PIL not installed"}

    def extract_content(self, file_path: Path) -> str:
        """Extract basic image info as text."""
        meta = self.process(file_path)
        return f"Image: {meta.get('width', '?')}x{meta.get('height', '?')} {meta.get('format', '?')}"

class PDFProcessorPlugin(FileProcessorPlugin):
    """Process PDF files and extract text."""

    @property
    def supported_extensions(self) -> List[str]:
        return [".pdf"]

    @property
    def name(self) -> str:
        return "pdf_processor"

    def process(self, file_path: Path, **kwargs) -> Dict[str, Any]:
        """Extract PDF metadata."""
        try:
            import PyPDF2
            with open(file_path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                return {
                    "pages": len(reader.pages),
                    "title": reader.metadata.title if reader.metadata else None,
                    "author": reader.metadata.author if reader.metadata else None,
                }
        except ImportError:
            return {"error": "PyPDF2 not installed"}

    def extract_content(self, file_path: Path) -> str:
        """Extract text from PDF."""
        try:
            import PyPDF2
            with open(file_path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                text = ""
                for page in reader.pages[:5]:  # First 5 pages
                    text += page.extract_text() or ""
                return text[:2000]  # Limit output
        except ImportError:
            return "PyPDF2 not installed"
