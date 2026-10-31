import os
from pathlib import Path

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton

from fleasion.config import manager as manager_module
from fleasion.config.manager import ConfigManager
from fleasion.gui.replacer_config import ReplacerConfigWindow
from fleasion.localization import DEFAULT_LANGUAGE, available_languages, get_language, set_language, tr


_APP = None
_TRANSLATED_LANGUAGES = [code for code, _name in available_languages() if code != DEFAULT_LANGUAGE]


def _qapp():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


@pytest.mark.parametrize('language', _TRANSLATED_LANGUAGES)
def test_translated_replacer_controls_do_not_clip_text(tmp_path, monkeypatch, language):
    app = _qapp()
    config_dir = Path(tmp_path) / 'FleasionNT'
    configs_dir = config_dir / 'configs'
    monkeypatch.setattr(manager_module, 'CONFIG_DIR', config_dir)
    monkeypatch.setattr(manager_module, 'CONFIG_FILE', config_dir / 'settings.json')
    monkeypatch.setattr(manager_module, 'CONFIGS_FOLDER', configs_dir)

    previous_language = get_language()
    set_language(language)
    window = None
    try:
        window = ReplacerConfigWindow(ConfigManager())
        window.resize(900, 750)
        window.show()
        app.processEvents()

        clipped = []
        for label in window.findChildren(QLabel):
            if label.isVisible() and label.text() and label.sizeHint().width() > label.width():
                clipped.append(('label', label.text(), label.width(), label.sizeHint().width()))

        for button in window.findChildren(QPushButton):
            if not button.isVisible() or not button.text() or button.text() == '?':
                continue
            if button.sizeHint().width() > button.width():
                clipped.append(('button', button.text(), button.width(), button.sizeHint().width()))

        for line_edit in window.findChildren(QLineEdit):
            placeholder = line_edit.placeholderText()
            if not line_edit.isVisible() or not placeholder:
                continue
            required_width = line_edit.fontMetrics().horizontalAdvance(placeholder) + 12
            if required_width > line_edit.width():
                clipped.append(('line edit', placeholder, line_edit.width(), required_width))

        assert clipped == []
    finally:
        if window is not None:
            window.enabled_menu.hide()
            window.close()
        set_language(previous_language)
        app.processEvents()



def test_dashboard_restores_fleasion_workflows_and_separates_advanced_sql(
    tmp_path, monkeypatch
):
    app = _qapp()
    config_dir = Path(tmp_path) / 'FleasionExtended'
    configs_dir = config_dir / 'configs'
    monkeypatch.setattr(manager_module, 'CONFIG_DIR', config_dir)
    monkeypatch.setattr(manager_module, 'CONFIG_FILE', config_dir / 'settings.json')
    monkeypatch.setattr(manager_module, 'CONFIGS_FOLDER', configs_dir)

    window = None
    try:
        window = ReplacerConfigWindow(ConfigManager())
        expected_tabs = [
            tr('ui.gui.replacer_config.replacer'),
            'Scraper DB',
            tr('ui.gui.replacer_config.subplace_joiner'),
            tr('ui.gui.replacer_config.miscellaneous'),
            tr('ui.gui.replacer_config.settings'),
            'Advanced SQL',
        ]
        actual_tabs = [
            window.tab_widget.tabText(index)
            for index in range(window.tab_widget.count())
        ]

        assert actual_tabs == expected_tabs
        assert window._scraper_db_tab is window._asset_explorer_tab
        assert window._advanced_sql_tab is window._sqlite_browser_tab
        assert window.tab_widget.indexOf(window._replacer_tab) == 0
        assert window.tab_widget.tabText(2) == tr('ui.gui.replacer_config.subplace_joiner')
        assert window.tab_widget.currentWidget() is window._replacer_tab
        assert not hasattr(window, '_local_db_tab')
        assert not hasattr(window, '_proxy_traffic_tab')
        assert window._asset_id_replacer_tab is window._replacer_tab
        assert not hasattr(window, '_replacer_modes')
        assert not hasattr(window, '_hash_replacer_tab')
        assert window._hash_replacer_store.root == config_dir / 'HashReplacer'
        assert window._rando_stuff_tab._hash_asset_store is window._hash_replacer_store
        assert window._rando_stuff_tab._cache_store is window._scraper_db_tab.store
        assert window._hash_replacer_store.create_config('Migrated Default')
        window.config_manager.settings['last_hash_replacer_profile'] = 'Migrated Default'
        window.config_manager.save()
        window.show()
        app.processEvents()
        window._open_hash_replacer_dialog()
        assert window._hash_replacer_tab.profile_combo.currentText() == 'Migrated Default'
        window._hash_replacer_tab.profile_combo.setCurrentText('Default')
        app.processEvents()
        assert window.config_manager.settings['last_hash_replacer_profile'] == 'Default'
        window._hash_replacer_tab.profile_combo.setCurrentText('Migrated Default')
        app.processEvents()
        assert window.config_manager.settings['last_hash_replacer_profile'] == 'Migrated Default'
        assert window._hash_replacer_tab.asset_store is window._hash_replacer_store
        assert window._hash_replacer_tab.cache_store is window._scraper_db_tab.store
        assert window._hash_replacer_dialog.isVisible()
        assert not hasattr(window, '_hidden_replacer_tab')
    finally:
        if window is not None:
            enabled_menu = getattr(window, 'enabled_menu', None)
            if enabled_menu is not None:
                enabled_menu.hide()
            window.close()
        app.processEvents()



def test_existing_asset_id_profiles_are_hidden_without_moving_or_rewriting_files(
    tmp_path, monkeypatch
):
    app = _qapp()
    config_dir = Path(tmp_path) / 'FleasionArchived'
    configs_dir = config_dir / 'configs'
    configs_dir.mkdir(parents=True)
    archived_config = configs_dir / 'fallen.json'
    original = (
        b'{\r\n'
        b'  "replacement_rules": [\r\n'
        b'    {"name": "example", "replace_ids": [123], "mode": "local", '
        b'"local_path": "D:/assets/example.obj"}\r\n'
        b'  ]\r\n'
        b'}\r\n'
    )
    archived_config.write_bytes(original)
    monkeypatch.setattr(manager_module, 'CONFIG_DIR', config_dir)
    monkeypatch.setattr(manager_module, 'CONFIG_FILE', config_dir / 'settings.json')
    monkeypatch.setattr(manager_module, 'CONFIGS_FOLDER', configs_dir)

    window = None
    try:
        manager = ConfigManager()
        window = ReplacerConfigWindow(manager)
        assert archived_config.read_bytes() == original
        assert archived_config.exists()
        assert 'fallen' in window._legacy_profile_names()
        assert 'fallen' not in window._visible_replacer_config_names()
        assert 'Default' in window._visible_replacer_config_names()
        assert window._rando_stuff_tab._legacy_config_combo.findData('fallen') >= 0
        window.set_legacy_profiles_visible(True)
        assert 'fallen' in window._visible_replacer_config_names()
        window.set_legacy_profiles_visible(False)
        assert 'fallen' not in window._visible_replacer_config_names()
        assert archived_config.read_bytes() == original
    finally:
        if window is not None:
            window.close()
        app.processEvents()

def test_original_default_profile_is_not_renamed_or_replaced_on_startup(
    tmp_path, monkeypatch
):
    app = _qapp()
    config_dir = Path(tmp_path) / 'FleasionOriginalDefault'
    configs_dir = config_dir / 'configs'
    configs_dir.mkdir(parents=True)
    default_path = configs_dir / 'Default.json'
    original = (
        b'{\r\n'
        b'  "replacement_rules": [\r\n'
        b'    {"name": "original wall", "replace_ids": [12345], "mode": "local", '
        b'"local_path": "D:/assets/wall.obj"}\r\n'
        b'  ]\r\n'
        b'}\r\n'
    )
    default_path.write_bytes(original)
    monkeypatch.setattr(manager_module, 'CONFIG_DIR', config_dir)
    monkeypatch.setattr(manager_module, 'CONFIG_FILE', config_dir / 'settings.json')
    monkeypatch.setattr(manager_module, 'CONFIGS_FOLDER', configs_dir)

    window = None
    try:
        manager = ConfigManager()
        window = ReplacerConfigWindow(manager)

        assert default_path.read_bytes() == original
        assert not (configs_dir / 'Legacy Default.json').exists()
        assert manager.get_replacement_rules('Default')[0]['name'] == 'original wall'
        assert 'Default' not in manager.settings['hidden_legacy_replacer_configs']
        assert 'Default' in window._visible_replacer_config_names()
        assert window._rando_stuff_tab._legacy_config_combo.findData('Default') >= 0
    finally:
        if window is not None:
            window.close()
        app.processEvents()


def test_previous_migration_restores_original_default_and_preserves_empty_placeholder(
    tmp_path, monkeypatch
):
    app = _qapp()
    config_dir = Path(tmp_path) / 'FleasionRecoverDefault'
    configs_dir = config_dir / 'configs'
    configs_dir.mkdir(parents=True)
    default_path = configs_dir / 'Default.json'
    archived_path = configs_dir / 'Legacy Default.json'
    empty_default = b'{\n  "replacement_rules": []\n}\n'
    original_default = (
        b'{\r\n'
        b'  "replacement_rules": [\r\n'
        b'    {"name": "restored original", "replace_ids": [777], "mode": "id", '
        b'"with_id": 888}\r\n'
        b'  ]\r\n'
        b'}\r\n'
    )
    default_path.write_bytes(empty_default)
    archived_path.write_bytes(original_default)
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / 'settings.json').write_text(
        json.dumps({
            'last_config': 'Default',
            'legacy_default_replacer_archived_v1': True,
            'legacy_replacer_visibility_initialized_v1': True,
            'hidden_legacy_replacer_configs': ['Legacy Default'],
            'show_legacy_replacer_configs': False,
        }),
        encoding='utf-8',
    )
    monkeypatch.setattr(manager_module, 'CONFIG_DIR', config_dir)
    monkeypatch.setattr(manager_module, 'CONFIG_FILE', config_dir / 'settings.json')
    monkeypatch.setattr(manager_module, 'CONFIGS_FOLDER', configs_dir)

    window = None
    try:
        manager = ConfigManager()
        window = ReplacerConfigWindow(manager)

        assert default_path.read_bytes() == original_default
        assert not archived_path.exists()
        recovery_copy = configs_dir / '.migration-backups' / 'Default.generated-empty.json'
        assert recovery_copy.read_bytes() == empty_default
        assert manager.get_replacement_rules('Default')[0]['name'] == 'restored original'
        assert 'Legacy Default' not in manager.settings['hidden_legacy_replacer_configs']
        assert manager.last_config == 'Default'
        assert window._rando_stuff_tab._legacy_config_combo.findData('Default') >= 0
    finally:
        if window is not None:
            window.close()
        app.processEvents()


def test_recovery_never_overwrites_a_nonempty_current_default(
    tmp_path, monkeypatch
):
    app = _qapp()
    config_dir = Path(tmp_path) / 'FleasionKeepBothDefaults'
    configs_dir = config_dir / 'configs'
    configs_dir.mkdir(parents=True)
    default_path = configs_dir / 'Default.json'
    archived_path = configs_dir / 'Legacy Default.json'
    current_default = (
        b'{"replacement_rules":[{"name":"current default","replace_ids":[1],'
        b'"mode":"id","with_id":2}]}'
    )
    archived_default = (
        b'{"replacement_rules":[{"name":"archived default","replace_ids":[3],'
        b'"mode":"id","with_id":4}]}'
    )
    default_path.write_bytes(current_default)
    archived_path.write_bytes(archived_default)
    monkeypatch.setattr(manager_module, 'CONFIG_DIR', config_dir)
    monkeypatch.setattr(manager_module, 'CONFIG_FILE', config_dir / 'settings.json')
    monkeypatch.setattr(manager_module, 'CONFIGS_FOLDER', configs_dir)

    window = None
    try:
        manager = ConfigManager()
        window = ReplacerConfigWindow(manager)

        assert default_path.read_bytes() == current_default
        assert archived_path.read_bytes() == archived_default
        assert not (configs_dir / '.migration-backups').exists()
        assert manager.get_replacement_rules('Default')[0]['name'] == 'current default'
        assert window._rando_stuff_tab._legacy_config_combo.findData('Default') >= 0
        assert window._rando_stuff_tab._legacy_config_combo.findData('Legacy Default') >= 0
    finally:
        if window is not None:
            window.close()
        app.processEvents()

