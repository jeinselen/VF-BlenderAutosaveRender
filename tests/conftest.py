import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, MagicMock
import json
import os


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path)


@pytest.fixture
def mock_bpy():
    """Mock Blender's bpy module for testing."""
    mock_bpy = Mock()
    mock_bpy.context = Mock()
    mock_bpy.data = Mock()
    mock_bpy.types = Mock()
    mock_bpy.props = Mock()
    mock_bpy.utils = Mock()
    mock_bpy.app = Mock()
    mock_bpy.app.handlers = Mock()
    mock_bpy.app.handlers.persistent = Mock()
    
    # Mock scene and render settings
    mock_scene = Mock()
    mock_scene.render = Mock()
    mock_scene.render.filepath = "/tmp/test"
    mock_scene.render.image_settings = Mock()
    mock_scene.render.image_settings.file_format = "PNG"
    mock_bpy.context.scene = mock_scene
    
    return mock_bpy


@pytest.fixture
def mock_addon_prefs():
    """Mock addon preferences for testing."""
    prefs = Mock()
    prefs.autosave_render_path = "/tmp/renders/"
    prefs.autosave_render_name = "render_{frame}"
    prefs.autosave_render_subfolders = False
    prefs.batch_render_factor = 1
    prefs.batch_render_random = False
    prefs.email_enabled = False
    prefs.pushover_enabled = False
    return prefs


@pytest.fixture
def sample_render_data():
    """Sample render data for testing."""
    return {
        "frame": "001",
        "scene": "Scene",
        "camera": "Camera",
        "timestamp": "20240101_120000",
        "format": "PNG",
        "resolution": "1920x1080"
    }


@pytest.fixture
def mock_datetime(monkeypatch):
    """Mock datetime for consistent testing."""
    import datetime
    mock_dt = Mock()
    mock_dt.now.return_value = datetime.datetime(2024, 1, 1, 12, 0, 0)
    mock_dt.strftime = lambda x, fmt: "20240101_120000"
    monkeypatch.setattr("datetime.datetime", mock_dt)
    return mock_dt


@pytest.fixture
def mock_file_system(temp_dir):
    """Mock file system operations."""
    def create_test_file(path, content="test content"):
        file_path = temp_dir / path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)
        return file_path
    
    return create_test_file


@pytest.fixture
def mock_subprocess():
    """Mock subprocess for FFmpeg operations."""
    mock = Mock()
    mock.run.return_value = Mock(returncode=0, stdout="", stderr="")
    mock.PIPE = "PIPE"
    return mock


@pytest.fixture
def mock_requests():
    """Mock requests for HTTP operations (Pushover notifications)."""
    mock = Mock()
    mock.post.return_value = Mock(status_code=200, json=lambda: {"status": 1})
    return mock


@pytest.fixture
def mock_email():
    """Mock email (SMTP) for notification testing."""
    mock_smtp = Mock()
    mock_smtp.sendmail.return_value = {}
    mock_smtp.quit.return_value = None
    return mock_smtp


@pytest.fixture
def sample_image_formats():
    """Sample image formats for testing."""
    return {
        "PNG": {"extension": "png", "supports_alpha": True},
        "JPEG": {"extension": "jpg", "supports_alpha": False},
        "TIFF": {"extension": "tif", "supports_alpha": True},
        "OPEN_EXR": {"extension": "exr", "supports_alpha": True}
    }


@pytest.fixture
def mock_platform_info():
    """Mock platform information."""
    return {
        "system": "Linux",
        "platform": "linux",
        "machine": "x86_64",
        "processor": "Intel64 Family 6 Model 142 Stepping 10",
        "python_version": "3.11.0"
    }


@pytest.fixture(autouse=True)
def clean_environment():
    """Clean environment variables before each test."""
    env_vars_to_clean = [
        "BLENDER_USER_SCRIPTS",
        "BLENDER_SYSTEM_SCRIPTS",
        "BLENDER_USER_CONFIG",
        "BLENDER_SYSTEM_CONFIG"
    ]
    
    original_values = {}
    for var in env_vars_to_clean:
        original_values[var] = os.environ.get(var)
        if var in os.environ:
            del os.environ[var]
    
    yield
    
    # Restore original values
    for var, value in original_values.items():
        if value is not None:
            os.environ[var] = value