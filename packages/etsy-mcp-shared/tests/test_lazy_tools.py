"""Tests for the shared lazy_tools module."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from etsy_mcp_shared.lazy_tools import (
    LazyToolLoader,
    build_tool_module_map,
    setup_lazy_loading,
)


class TestBuildToolModuleMap:
    """Tests for build_tool_module_map with a temporary manifest."""

    def test_loads_from_manifest_fallback(self, tmp_path):
        """When the tools package cannot be found, falls back to manifest."""
        manifest = {
            "tools": [],
            "module_map": {
                "etsy_list_clients": "my_app.tools.clients",
                "etsy_list_devices": "my_app.tools.devices",
            },
        }
        manifest_path = tmp_path / "tools_manifest.json"
        manifest_path.write_text(json.dumps(manifest))

        result = build_tool_module_map("nonexistent.package.tools", manifest_path=str(manifest_path))

        assert result == {
            "etsy_list_clients": "my_app.tools.clients",
            "etsy_list_devices": "my_app.tools.devices",
        }

    def test_returns_empty_when_no_manifest(self):
        """Returns empty dict when package not found and no manifest."""
        result = build_tool_module_map("nonexistent.package.tools")
        assert result == {}

    def test_returns_empty_when_manifest_missing(self, tmp_path):
        """Returns empty dict when manifest path does not exist."""
        result = build_tool_module_map(
            "nonexistent.package.tools",
            manifest_path=str(tmp_path / "missing.json"),
        )
        assert result == {}

    def test_scans_tool_files(self, tmp_path):
        """Scans .py files in the package directory for tool names."""
        # Create a fake tools package
        tools_dir = tmp_path / "fake_tools"
        tools_dir.mkdir()
        (tools_dir / "__init__.py").write_text("")
        (tools_dir / "clients.py").write_text(
            """
@server.tool(name="etsy_list_clients")
async def list_clients():
    pass

@server.tool(name="etsy_get_client")
async def get_client():
    pass
"""
        )
        (tools_dir / "devices.py").write_text(
            """
@permissioned_tool(name="etsy_list_devices", permission_category="device", permission_action="read")
async def list_devices():
    pass
"""
        )
        # Private files should be skipped
        (tools_dir / "_internal.py").write_text('name="etsy_should_not_appear"')

        import sys

        # Register the fake package so importlib.import_module can find it
        fake_pkg = MagicMock()
        fake_pkg.__path__ = [str(tools_dir)]
        sys.modules["fake_tools"] = fake_pkg

        try:
            result = build_tool_module_map("fake_tools")

            assert "etsy_list_clients" in result
            assert "etsy_get_client" in result
            assert "etsy_list_devices" in result
            assert result["etsy_list_clients"] == "fake_tools.clients"
            assert result["etsy_list_devices"] == "fake_tools.devices"
            assert "etsy_should_not_appear" not in result
        finally:
            del sys.modules["fake_tools"]

    def test_manifest_with_invalid_json(self, tmp_path):
        """Returns empty dict when manifest contains invalid JSON."""
        manifest_path = tmp_path / "bad_manifest.json"
        manifest_path.write_text("not valid json {{{")

        result = build_tool_module_map("nonexistent.package.tools", manifest_path=str(manifest_path))
        assert result == {}


class TestLazyToolLoader:
    """Tests for the LazyToolLoader class."""

    def test_is_loaded_returns_false_initially(self):
        server = MagicMock()
        loader = LazyToolLoader(server, MagicMock(), {"etsy_test": "my.tools.test"})
        assert loader.is_loaded("etsy_test") is False

    @pytest.mark.asyncio
    async def test_load_tool_unknown(self):
        server = MagicMock()
        loader = LazyToolLoader(server, MagicMock(), {})
        result = await loader.load_tool("etsy_unknown")
        assert result is False

    @pytest.mark.asyncio
    async def test_load_tool_marks_as_loaded(self):
        server = MagicMock()
        tool_map = {"etsy_test": "json"}  # json is always importable
        loader = LazyToolLoader(server, MagicMock(), tool_map)
        result = await loader.load_tool("etsy_test")
        assert result is True
        assert loader.is_loaded("etsy_test") is True


class TestSetupLazyLoading:
    """Tests for setup_lazy_loading."""

    def test_returns_loader_and_patches_call_tool(self):
        server = MagicMock()
        server.call_tool = AsyncMock()
        tool_map = {"etsy_test": "json"}

        loader = setup_lazy_loading(server, MagicMock(), tool_map)

        assert isinstance(loader, LazyToolLoader)
        # call_tool should have been replaced
        assert server.call_tool != loader  # It's a wrapper, not the loader itself
