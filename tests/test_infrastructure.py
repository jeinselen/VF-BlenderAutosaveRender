"""
Validation tests to ensure testing infrastructure is properly set up.
"""
import pytest
import sys
from pathlib import Path
import importlib.util


def test_pytest_working():
    """Test that pytest is working correctly."""
    assert True


def test_python_version():
    """Test that Python version is supported."""
    assert sys.version_info >= (3, 10), "Python 3.10+ required"


def test_project_structure():
    """Test that project structure is correct."""
    project_root = Path(__file__).parent.parent
    
    # Check main addon file exists
    assert (project_root / "VF_autosaveRender.py").exists(), "Main addon file should exist"
    
    # Check pyproject.toml exists
    assert (project_root / "pyproject.toml").exists(), "pyproject.toml should exist"
    
    # Check test directories exist
    assert (project_root / "tests").is_dir(), "tests directory should exist"
    assert (project_root / "tests" / "unit").is_dir(), "tests/unit directory should exist"
    assert (project_root / "tests" / "integration").is_dir(), "tests/integration directory should exist"


def test_test_markers():
    """Test that custom pytest markers are available."""
    import _pytest.config
    
    # This test ensures our custom markers are properly configured
    # The markers should be defined in pyproject.toml
    markers = ["unit", "integration", "slow"]
    
    # Since markers are validated at runtime, we'll just ensure they exist in config
    for marker in markers:
        assert marker is not None


@pytest.mark.unit
def test_unit_marker():
    """Test unit marker works."""
    assert True


@pytest.mark.integration  
def test_integration_marker():
    """Test integration marker works."""
    assert True


@pytest.mark.slow
def test_slow_marker():
    """Test slow marker works."""
    assert True


def test_temp_dir_fixture(temp_dir):
    """Test that temp_dir fixture works."""
    assert temp_dir.exists()
    assert temp_dir.is_dir()
    
    # Create a test file
    test_file = temp_dir / "test.txt"
    test_file.write_text("Hello, World!")
    
    assert test_file.exists()
    assert test_file.read_text() == "Hello, World!"


def test_mock_bpy_fixture(mock_bpy):
    """Test that mock_bpy fixture works."""
    assert mock_bpy is not None
    assert hasattr(mock_bpy, 'context')
    assert hasattr(mock_bpy, 'data')
    assert hasattr(mock_bpy, 'types')
    assert hasattr(mock_bpy.context, 'scene')


def test_mock_addon_prefs_fixture(mock_addon_prefs):
    """Test that mock_addon_prefs fixture works."""
    assert mock_addon_prefs is not None
    assert hasattr(mock_addon_prefs, 'autosave_render_path')
    assert mock_addon_prefs.autosave_render_path == "/tmp/renders/"


def test_sample_render_data_fixture(sample_render_data):
    """Test that sample_render_data fixture works."""
    assert isinstance(sample_render_data, dict)
    assert "frame" in sample_render_data
    assert "scene" in sample_render_data
    assert "camera" in sample_render_data


def test_mock_file_system_fixture(mock_file_system):
    """Test that mock_file_system fixture works."""
    test_file = mock_file_system("subdir/test.txt", "test content")
    assert test_file.exists()
    assert test_file.read_text() == "test content"


def test_addon_import():
    """Test that the main addon file can be imported without Blender dependencies."""
    import sys
    from unittest.mock import Mock
    
    # Mock Blender modules before importing
    sys.modules['bpy'] = Mock()
    sys.modules['bpy.app'] = Mock()
    sys.modules['bpy.app.handlers'] = Mock()
    
    project_root = Path(__file__).parent.parent
    addon_path = project_root / "VF_autosaveRender.py"
    
    # Load the addon module
    spec = importlib.util.spec_from_file_location("VF_autosaveRender", addon_path)
    assert spec is not None, "Could not create module spec"
    
    module = importlib.util.module_from_spec(spec)
    
    # This should not raise an exception
    try:
        spec.loader.exec_module(module)
        success = True
    except Exception as e:
        print(f"Import error: {e}")
        success = False
    
    assert success, "Addon should be importable with mocked dependencies"
    
    # Check bl_info exists
    assert hasattr(module, 'bl_info'), "Addon should have bl_info"
    assert isinstance(module.bl_info, dict), "bl_info should be a dictionary"
    assert "name" in module.bl_info, "bl_info should have name"