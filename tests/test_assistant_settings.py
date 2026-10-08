import json

import pytest

from gui.assistant_settings import AssistantSettings


def test_saved_key_is_encrypted_and_public_state_never_returns_it(tmp_path):
    settings = AssistantSettings(tmp_path)
    public = settings.save({'provider': 'kimi', 'model': 'kimi-k3', 'apiKey': 'test-secret-123',
                            'remember': True})
    assert public['hasKey'] is True
    assert 'test-secret' not in json.dumps(public)
    assert b'test-secret' not in (tmp_path / 'settings.json').read_bytes()
    restored = AssistantSettings(tmp_path)
    assert restored.client_config()['api_key'] == 'test-secret-123'
    restored.save({'provider': 'deepseek', 'model': 'deepseek-v4-pro', 'remember': False})
    assert restored.state()['hasKey'] is False


def test_session_only_key_is_not_restored_and_invalid_provider_rejected(tmp_path):
    settings = AssistantSettings(tmp_path)
    settings.save({'provider': 'deepseek', 'model': 'deepseek-v4-pro', 'apiKey': 'session-secret', 'remember': False})
    assert settings.client_config()['api_key'] == 'session-secret'
    assert not AssistantSettings(tmp_path).state()['hasKey']
    with pytest.raises(ValueError):
        settings.save({'provider': 'other', 'model': 'x', 'apiKey': 'secret'})
    settings.save({'provider': 'deepseek', 'model': 'deepseek-v4-pro', 'clearKey': True})
    assert not settings.state()['hasKey']
