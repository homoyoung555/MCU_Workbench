import io
import json
import threading
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest

import gui.assistant_model as assistant_model
from gui.assistant_model import Cancelled, ModelClient, ModelConfig, ModelError, _RejectRedirect


class FakeResponse:
    def __init__(self, lines, after_read=None):
        self._lines = iter(lines)
        self._after_read = after_read
        self.closed = False

    def readline(self, _limit=None):
        try:
            line = next(self._lines)
        except StopIteration:
            return b""
        if self._after_read:
            self._after_read()
        return line

    def close(self):
        self.closed = True


def sse(event):
    return ("data: " + json.dumps(event) + "\n\n").encode()


def test_kimi_stream_replays_reasoning_and_reassembles_tool_call_without_exposing_it():
    response = FakeResponse(
        [
            sse({"choices": [{"delta": {"reasoning_content": "private "}}]}),
            sse(
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {"index": 0, "id": "call_1", "type": "function", "function": {"name": "look", "arguments": "{\"pa"}}
                                ]
                            }
                        }
                    ]
                }
            ),
            sse(
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {"index": 0, "function": {"name": "up", "arguments": "rt\": 1}"}}
                                ]
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                }
            ),
            b"data: [DONE]\n\n",
        ]
    )
    progress = []
    config = ModelConfig(provider="kimi", model="kimi-k3", api_key="secret")

    with patch("gui.assistant_model.urlopen", return_value=response) as open_call:
        assistant = ModelClient(config).complete([{"role": "user", "content": "hi"}], [{"type": "function"}], threading.Event(), progress.append)

    request = open_call.call_args.args[0]
    payload = json.loads(request.data)
    assert request.full_url == "https://api.moonshot.ai/v1/chat/completions"
    assert payload == {
        "model": "kimi-k3",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [{"type": "function"}],
        "stream": True,
        "reasoning_effort": "max",
        "max_completion_tokens": 8192,
    }
    assert progress == []
    assert assistant == {
        "role": "assistant",
        "content": None,
        "reasoning_content": "private ",
        "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "lookup", "arguments": "{\"part\": 1}"}}],
    }


def test_deepseek_payload_is_thinking_enabled_and_never_sends_tool_choice():
    response = FakeResponse(
        [sse({"choices": [{"delta": {"content": "answer"}, "finish_reason": "stop"}]}), b"data: [DONE]\n\n"]
    )
    config = ModelConfig(provider="deepseek", model="deepseek-flash", api_key="secret", max_tokens=123)

    with patch("gui.assistant_model.urlopen", return_value=response) as open_call:
        assistant = ModelClient(config).complete(
            [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "previous", "reasoning_content": "replay this"},
                {"role": "user", "content": "hi"},
            ],
            [],
            threading.Event(),
        )

    payload = json.loads(open_call.call_args.args[0].data)
    assert payload == {
        "model": "deepseek-flash",
        "messages": [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "previous", "reasoning_content": "replay this"},
            {"role": "user", "content": "hi"},
        ],
        "stream": True,
        "thinking": {"type": "enabled"},
        "reasoning_effort": "max",
        "max_tokens": 123,
    }
    assert "tool_choice" not in payload
    assert assistant == {"role": "assistant", "content": "answer"}


@pytest.mark.parametrize(
    ("raised", "code"),
    [
        (HTTPError("https://api.deepseek.com/chat/completions", 401, "", {}, io.BytesIO()), "auth"),
        (HTTPError("https://api.deepseek.com/chat/completions", 429, "", {}, io.BytesIO()), "rate_limit"),
        (HTTPError("https://api.deepseek.com/chat/completions", 400, "", {}, io.BytesIO()), "protocol"),
        (HTTPError("https://api.deepseek.com/chat/completions", 302, "", {}, io.BytesIO()), "protocol"),
        (URLError("offline"), "network"),
    ],
)
def test_transport_errors_are_classified_without_leaking_key(raised, code):
    client = ModelClient(ModelConfig(provider="deepseek", model="deepseek-flash", api_key="very-secret-key"))

    with patch("gui.assistant_model.urlopen", side_effect=raised), pytest.raises(ModelError) as error:
        client.complete([], [], threading.Event())

    assert error.value.code == code
    assert "very-secret-key" not in error.value.message
    assert "very-secret-key" not in str(error.value)


def test_cancelled_before_request_and_after_a_stream_read():
    cancelled = threading.Event()
    cancelled.set()
    client = ModelClient(ModelConfig(provider="deepseek", model="deepseek-flash", api_key="secret"))
    with patch("gui.assistant_model.urlopen") as open_call, pytest.raises(Cancelled):
        client.complete([], [], cancelled)
    open_call.assert_not_called()

    cancelled.clear()
    response = FakeResponse([sse({"choices": [{"delta": {"content": "late"}}]})], cancelled.set)
    with patch("gui.assistant_model.urlopen", return_value=response), pytest.raises(Cancelled):
        client.complete([], [], cancelled)


@pytest.mark.parametrize(
    "lines",
    [
        [sse({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "x", "function": {"name": "f", "arguments": "{\"x\":"}}]}, "finish_reason": "tool_calls"}]}), b"data: [DONE]\n\n"],
        [sse({"choices": [{"delta": {"content": "cut"}, "finish_reason": "length"}]}), b"data: [DONE]\n\n"],
        [b"data: not-json\n\n"],
    ],
)
def test_malformed_or_truncated_stream_is_rejected_before_any_tool_can_execute(lines):
    client = ModelClient(ModelConfig(provider="deepseek", model="deepseek-flash", api_key="secret"))
    with patch("gui.assistant_model.urlopen", return_value=FakeResponse(lines)), pytest.raises(ModelError) as error:
        client.complete([], [{"type": "function"}], threading.Event())
    assert error.value.code in {"protocol", "truncated"}


def test_redirect_handler_never_follows_an_authorized_request_to_another_host():
    response = FakeResponse([sse({"choices": [{"delta": {"content": "answer"}, "finish_reason": "stop"}]}), b"data: [DONE]\n\n"])
    client = ModelClient(ModelConfig(provider="deepseek", model="deepseek-flash", api_key="secret"))
    with patch("gui.assistant_model.build_opener") as build:
        build.return_value.open.return_value = response
        client.complete([], [], threading.Event())
    handler = build.call_args.args[0]
    assert isinstance(handler, _RejectRedirect)
    assert handler.redirect_request(None, None, 302, "Found", {}, "https://other.example") is None


def test_usage_only_sse_event_is_accepted_and_only_safe_usage_is_retained():
    response = FakeResponse(
        [
            sse({"choices": [{"delta": {"content": "answer"}, "finish_reason": "stop"}]}),
            sse({"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5, "provider_note": "discard"}}),
            b"data: [DONE]\n\n",
        ]
    )
    client = ModelClient(ModelConfig(provider="deepseek", model="deepseek-flash", api_key="secret"))
    with patch("gui.assistant_model.urlopen", return_value=response):
        assert client.complete([], [], threading.Event()) == {"role": "assistant", "content": "answer"}
    assert client.last_usage == {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}


@pytest.mark.parametrize(
    "lines",
    [
        [b"data: " + b"x" * 1_048_577 + b"\n"],
        [
            sse({"choices": [{"delta": {"tool_calls": [{"index": True, "id": "x", "function": {"name": "f", "arguments": "{}"}}]}}]}),
            b"data: [DONE]\n\n",
        ],
        [
            sse({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "x", "function": {"name": "f", "arguments": "{"}}]}}]}),
            sse({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "x", "function": {"arguments": "}"}}]}, "finish_reason": "tool_calls"}]}),
            b"data: [DONE]\n\n",
        ],
    ],
)
def test_stream_limits_and_invalid_tool_identifiers_are_rejected(lines):
    client = ModelClient(ModelConfig(provider="deepseek", model="deepseek-flash", api_key="secret"))
    with patch("gui.assistant_model.urlopen", return_value=FakeResponse(lines)), pytest.raises(ModelError) as error:
        client.complete([], [{"type": "function"}], threading.Event())
    assert error.value.code in {"protocol", "truncated"}


def test_total_stream_limit_stops_many_small_sse_lines(monkeypatch):
    monkeypatch.setattr(assistant_model, "_MAX_SSE_RESPONSE_BYTES", 10)
    client = ModelClient(ModelConfig(provider="deepseek", model="deepseek-flash", api_key="secret"))
    with patch("gui.assistant_model.urlopen", return_value=FakeResponse([b": 123\n", b": 456\n"])), pytest.raises(ModelError) as error:
        client.complete([], [], threading.Event())
    assert error.value.code == "truncated"


def test_connection_failure_retries_once_but_partial_stream_never_retries():
    client = ModelClient(ModelConfig(provider='deepseek', model='deepseek-flash', api_key='secret'))
    response = FakeResponse([sse({'choices': [{'delta': {'content': 'ok'}, 'finish_reason': 'stop'}]}), b'data: [DONE]\n\n'])
    with patch('gui.assistant_model.urlopen', side_effect=[URLError('offline'), response]) as opened:
        assert client.complete([], [], threading.Event())['content'] == 'ok'
        assert opened.call_count == 2
    class Broken(FakeResponse):
        def readline(self, _limit=None):
            raise OSError('stream interrupted')
    with patch('gui.assistant_model.urlopen', return_value=Broken([])) as opened, pytest.raises(ModelError):
        client.complete([], [], threading.Event())
    assert opened.call_count == 1


def test_retry_wait_is_cancellable_and_key_repr_is_redacted():
    event = threading.Event()
    def fail(*args, **kwargs):
        event.set()
        raise URLError('connection failed')
    config = ModelConfig(provider='kimi', model='kimi-k3', api_key='private-secret')
    assert 'private-secret' not in repr(config)
    with patch('gui.assistant_model.urlopen', side_effect=fail), pytest.raises(Cancelled):
        ModelClient(config).complete([], [], event)


def test_deepseek_usage_on_final_choice_chunk_is_recorded():
    response = FakeResponse([sse({'choices': [{'delta': {'content': 'ok'}, 'finish_reason': 'stop'}],
                                 'usage': {'prompt_tokens': 11, 'completion_tokens': 7, 'total_tokens': 18}}),
                             b'data: [DONE]\n\n'])
    client = ModelClient(ModelConfig('deepseek', 'deepseek-v4-pro', 'secret'))
    with patch('gui.assistant_model.urlopen', return_value=response):
        client.complete([], [], threading.Event())
    assert client.last_usage == {'prompt_tokens': 11, 'completion_tokens': 7, 'total_tokens': 18}
