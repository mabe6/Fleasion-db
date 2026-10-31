"""The settings tab must build and refresh while the HTTP proxy section is hidden."""

from __future__ import annotations

import os

from PyQt6.QtWidgets import QApplication

import fleasion.config.manager as config_manager_module
from fleasion.gui.settings_tab import SettingsTab


def test_settings_tab_builds_and_refreshes_with_proxy_section_hidden(tmp_path, monkeypatch) -> None:
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    app = QApplication.instance() or QApplication([])
    assert app is not None

    # Keep the real config folder untouched
    config_dir = tmp_path / 'FleasionNT'
    monkeypatch.setattr(config_manager_module, 'CONFIG_DIR', config_dir)
    monkeypatch.setattr(config_manager_module, 'CONFIG_FILE', config_dir / 'settings.json')
    monkeypatch.setattr(config_manager_module, 'CONFIGS_FOLDER', config_dir / 'configs')

    tab = SettingsTab(config_manager_module.ConfigManager())
    tab.refresh_from_config()
    tab.close()
