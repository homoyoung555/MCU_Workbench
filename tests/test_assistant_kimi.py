import json
import threading
from unittest.mock import patch
import pytest
from gui.assistant_model import ModelClient, ModelConfig, ModelError
from gui.assistant_settings import AssistantSettings
from tests.test_assistant_model import FakeResponse, sse


@pytest.mark.parametrize('model', ['kimi-k2.6', 'kimi-k2.7-code'])
def test_kimi_china_models_use_correct_endpoint_and_thinking_protocol(model):
    response = FakeResponse([sse({'choices':[{'delta':{'content':'ok'},'finish_reason':'stop'}]}), b'data: [DONE]\n'])
    with patch('gui.assistant_model.urlopen', return_value=response) as opened:
        result = ModelClient(ModelConfig('kimi', model, 'dummy', kimi_region='china')).complete(
            [{'role':'user','content':'hi'}], [], threading.Event())
    assert result['content'] == 'ok'
    request = opened.call_args.args[0]
    assert request.full_url == 'https://api.moonshot.cn/v1/chat/completions'
    body = json.loads(request.data)
    assert body['thinking'] == {'type':'enabled'} and 'reasoning_effort' not in body


def test_kimi_region_and_model_survive_settings_reload(tmp_path):
    settings = AssistantSettings(tmp_path)
    settings.save({'provider':'kimi','model':'kimi-k2.6','apiKey':'dummy','kimi_region':'china'})
    assert settings.client_config()['kimi_region'] == 'china'
    assert AssistantSettings(tmp_path).state()['kimi_region'] == 'china'
    with pytest.raises(ValueError):
        settings.save({'provider':'kimi','model':'kimi-k2.6','kimi_region':'https://untrusted.example'})


def test_invalid_region_never_sends_credential():
    with patch('gui.assistant_model.urlopen') as opened:
        with pytest.raises(ModelError):
            ModelClient(ModelConfig('kimi','kimi-k3','dummy',kimi_region='other')).complete([],[],threading.Event())
    opened.assert_not_called()


@pytest.mark.parametrize('model', ['k3', 'k3-256k'])
def test_kimi_code_subscription_uses_own_endpoint_and_k3_id(tmp_path, model):
    settings = AssistantSettings(tmp_path)
    settings.save({'provider':'kimi-code','model':model,'apiKey':'dummy','kimi_region':'china'})
    assert AssistantSettings(tmp_path).state()['model'] == model
    response = FakeResponse([sse({'choices':[{'delta':{'content':'ok'},'finish_reason':'stop'}]}), b'data: [DONE]\n'])
    with patch('gui.assistant_model.urlopen', return_value=response) as opened:
        ModelClient(ModelConfig(**settings.client_config())).complete([], [], threading.Event())
    request = opened.call_args.args[0]
    assert request.full_url == 'https://api.kimi.com/coding/v1/chat/completions'
    assert request.get_header('User-agent') == 'MCU-Workbench/1.0'
    body = json.loads(request.data)
    assert body['model'] == model and body['reasoning_effort'] == 'max'
    assert body['max_completion_tokens'] == 8192
    settings.save({'provider':'kimi','model':'kimi-k3','kimi_region':'china'})
    assert not settings.state()['hasKey']


def test_kimi_code_auth_error_identifies_subscription_key():
    from urllib.error import HTTPError
    with patch('gui.assistant_model.urlopen', side_effect=HTTPError('url',401,'Unauthorized',{},None)):
        with pytest.raises(ModelError, match='Kimi Code'):
            ModelClient(ModelConfig('kimi-code','k3','dummy',kimi_region='china')).complete([],[],threading.Event())
