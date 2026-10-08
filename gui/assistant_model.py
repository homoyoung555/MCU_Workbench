"""最小的 DeepSeek/Kimi Chat Completions 流式传输层。"""

from __future__ import annotations

import json
import socket
import threading
from dataclasses import dataclass, field
from http.client import IncompleteRead
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


_ENDPOINTS = {
    "deepseek": "https://api.deepseek.com/chat/completions",
    "kimi": "https://api.moonshot.ai/v1/chat/completions",
}
_MAX_SSE_LINE_BYTES = 1_048_576
_MAX_SSE_RESPONSE_BYTES = 8_388_608


class _RejectRedirect(HTTPRedirectHandler):
    """不将 Authorization 请求转发给重定向目标。"""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def urlopen(request: Request, timeout: float) -> Any:
    return build_opener(_RejectRedirect()).open(request, timeout=timeout)


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    model: str
    api_key: str = field(repr=False)
    reasoning_effort: str = "max"
    max_tokens: int = 8192
    kimi_region: str = 'international'


class ModelError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class Cancelled(ModelError):
    def __init__(self):
        super().__init__("cancelled", "请求已取消。")


class ModelClient:
    """发送一次请求；调用方负责工具执行及下一轮请求。"""

    def __init__(self, config: ModelConfig):
        self.config = config
        self.last_usage: dict[str, int] | None = None

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        cancel: threading.Event,
        on_progress: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        if cancel.is_set():
            raise Cancelled()
        self.last_usage = None
        provider = self.config.provider.lower()
        endpoint = _ENDPOINTS.get(provider)
        if provider == 'kimi':
            endpoint = {'china': 'https://api.moonshot.cn/v1/chat/completions',
                        'international': _ENDPOINTS['kimi']}.get(self.config.kimi_region)
        elif provider == 'kimi-code':
            endpoint = {'china': 'https://api.kimi.com/coding/v1/chat/completions',
                        'international': 'https://api.kimi.ai/coding/v1/chat/completions'}.get(self.config.kimi_region)
        if (
            endpoint is None
            or not self.config.model
            or not isinstance(self.config.max_tokens, int)
            or isinstance(self.config.max_tokens, bool)
            or self.config.max_tokens <= 0
        ):
            raise ModelError("protocol", "模型配置无效。")
        if not self.config.api_key:
            raise ModelError("auth", "缺少 API 密钥。")
        if not isinstance(self.config.api_key, str) or any(ord(ch) < 33 or ord(ch) > 126 for ch in self.config.api_key):
            raise ModelError('auth', 'API 密钥格式无效，请重新输入。')

        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "stream": True,
            "reasoning_effort": self.config.reasoning_effort,
        }
        if tools:
            payload["tools"] = tools
        if provider in ("kimi", "kimi-code"):
            payload["max_completion_tokens"] = self.config.max_tokens
            if self.config.model in ('kimi-k2.6', 'kimi-k2.7-code'):
                payload.pop('reasoning_effort')
                payload['thinking'] = {'type': 'enabled'}
        else:
            payload["thinking"] = {"type": "enabled"}
            payload["max_tokens"] = self.config.max_tokens

        request = Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.config.api_key}", "Content-Type": "application/json", "Accept": "text/event-stream", "User-Agent": "MCU-Workbench/1.0"},
            method="POST",
        )
        response = None
        try:
            for attempt in range(2):
                try:
                    response = urlopen(request, timeout=30)
                    break
                except HTTPError as error:
                    if attempt or not 500 <= error.code < 600:
                        raise
                    error.close()
                except (URLError, socket.timeout, TimeoutError, OSError):
                    if attempt:
                        raise
                if cancel.wait(1):
                    raise Cancelled()
            # Never retry after receiving response headers or any stream data.
            return self._read_stream(response, cancel, on_progress)
        except Cancelled:
            raise
        except HTTPError as error:
            if 300 <= error.code < 400:
                raise ModelError("protocol", "模型服务重定向请求已被拒绝。") from None
            if error.code in (401, 403):
                if provider == 'kimi-code':
                    raise ModelError('auth', 'Kimi Code鉴权或权限检查失败，请核对订阅控制台密钥、有效期、地区与套餐权限；开放平台密钥不能替代订阅密钥。') from None
                raise ModelError("auth", "身份验证失败，请检查本机 API 密钥；Kimi还需核对国内/国际地区是否与密钥一致。") from None
            if error.code == 404:
                raise ModelError('model_unavailable', '当前地区或账号未开放所选模型，请核对模型名称与账号权限。') from None
            if error.code == 429:
                raise ModelError("rate_limit", "服务限流，请稍后手动重试。") from None
            if 400 <= error.code < 500:
                raise ModelError("protocol", "模型服务拒绝了当前请求。") from None
            raise ModelError("network", "网络请求失败，请检查连接后手动重试。") from None
        except (URLError, socket.timeout, TimeoutError, OSError):
            raise ModelError("network", "网络请求失败，请检查连接后手动重试。") from None
        except IncompleteRead:
            raise ModelError("truncated", "模型响应不完整，未执行任何工具。") from None
        finally:
            if response is not None:
                response.close()

    def _read_stream(
        self,
        response: Any,
        cancel: threading.Event,
        on_progress: Callable[[str], None] | None,
    ) -> dict[str, Any]:
        content: list[str] = []
        reasoning: list[str] = []
        content_seen = False
        reasoning_seen = False
        calls: dict[int, dict[str, Any]] = {}
        finish_reason: str | None = None
        done = False
        total_bytes = 0

        while True:
            if cancel.is_set():
                raise Cancelled()
            line = response.readline(_MAX_SSE_LINE_BYTES + 1)
            if cancel.is_set():
                raise Cancelled()
            if not line:
                break
            total_bytes += len(line)
            if len(line) > _MAX_SSE_LINE_BYTES or total_bytes > _MAX_SSE_RESPONSE_BYTES:
                raise ModelError("truncated", "模型响应超过传输上限，未执行任何工具。")
            try:
                text = line.decode("utf-8").strip()
            except UnicodeDecodeError:
                raise ModelError("protocol", "模型服务返回了不兼容的数据。") from None
            if not text or text.startswith((":", "event:", "id:", "retry:")):
                continue
            if not text.startswith("data:"):
                raise ModelError("protocol", "模型服务返回了不兼容的数据。")
            data = text[5:].strip()
            if data == "[DONE]":
                done = True
                break
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                raise ModelError("protocol", "模型服务返回了不兼容的数据。") from None
            if not isinstance(event, dict):
                raise ModelError("protocol", "模型服务返回了不兼容的数据。")
            if "error" in event:
                self._raise_stream_error(event["error"])
            choices = event.get("choices")
            if choices == [] or event.get("usage") is not None:
                self._collect_usage(event.get("usage"))
            if choices == []:
                continue
            if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                raise ModelError("protocol", "模型服务返回了不兼容的数据。")
            choice = choices[0]
            delta = choice.get("delta")
            if not isinstance(delta, dict):
                raise ModelError("protocol", "模型服务返回了不兼容的数据。")
            if "content" in delta and delta["content"] is not None:
                if not isinstance(delta["content"], str):
                    raise ModelError("protocol", "模型服务返回了不兼容的数据。")
                content_seen = True
                content.append(delta["content"])
                if delta["content"] and on_progress is not None:
                    on_progress(delta["content"])
            if "reasoning_content" in delta and delta["reasoning_content"] is not None:
                if not isinstance(delta["reasoning_content"], str):
                    raise ModelError("protocol", "模型服务返回了不兼容的数据。")
                reasoning_seen = True
                reasoning.append(delta["reasoning_content"])
            if "tool_calls" in delta:
                self._append_tool_calls(calls, delta["tool_calls"])
            reason = choice.get("finish_reason")
            if reason is not None:
                if not isinstance(reason, str):
                    raise ModelError("protocol", "模型服务返回了不兼容的数据。")
                finish_reason = reason

        if not done or finish_reason == "length":
            raise ModelError("truncated", "模型响应不完整，未执行任何工具。")
        if finish_reason not in {"stop", "tool_calls"}:
            raise ModelError("protocol", "模型服务返回了不兼容的数据。")
        if (finish_reason == "tool_calls") != bool(calls):
            raise ModelError("protocol", "模型服务返回了不兼容的数据。")

        assistant: dict[str, Any] = {"role": "assistant", "content": "".join(content) if content_seen else None}
        if reasoning_seen:
            assistant["reasoning_content"] = "".join(reasoning)
        if calls:
            assistant["tool_calls"] = self._finalize_calls(calls)
        return assistant

    @staticmethod
    def _append_tool_calls(calls: dict[int, dict[str, Any]], chunks: Any) -> None:
        if not isinstance(chunks, list):
            raise ModelError("protocol", "模型服务返回了不兼容的数据。")
        for chunk in chunks:
            if (
                not isinstance(chunk, dict)
                or not isinstance(chunk.get("index"), int)
                or isinstance(chunk.get("index"), bool)
                or chunk["index"] < 0
            ):
                raise ModelError("protocol", "模型服务返回了不兼容的数据。")
            call = calls.setdefault(chunk["index"], {"id": None, "type": "function", "function": {"name": "", "arguments": ""}})
            for key in ("id", "type"):
                if key in chunk:
                    if not isinstance(chunk[key], str) or (key == "type" and chunk[key] != "function"):
                        raise ModelError("protocol", "模型服务返回了不兼容的数据。")
                    if key == "id":
                        if call["id"] is not None:
                            raise ModelError("protocol", "模型服务返回了不兼容的数据。")
                        call["id"] = chunk[key]
            function = chunk.get("function")
            if function is not None:
                if not isinstance(function, dict):
                    raise ModelError("protocol", "模型服务返回了不兼容的数据。")
                for key in ("name", "arguments"):
                    if key in function:
                        if not isinstance(function[key], str):
                            raise ModelError("protocol", "模型服务返回了不兼容的数据。")
                        call["function"][key] += function[key]

    @staticmethod
    def _finalize_calls(calls: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
        result = []
        for index in sorted(calls):
            call = calls[index]
            if not isinstance(call["id"], str) or not call["id"] or not call["function"]["name"]:
                raise ModelError("truncated", "模型响应不完整，未执行任何工具。")
            try:
                arguments = json.loads(call["function"]["arguments"])
            except json.JSONDecodeError:
                raise ModelError("truncated", "模型响应不完整，未执行任何工具。") from None
            if not isinstance(arguments, dict):
                raise ModelError("protocol", "模型服务返回了不兼容的数据。")
            result.append(call)
        return result

    def _collect_usage(self, usage: Any) -> None:
        if not isinstance(usage, dict):
            raise ModelError("protocol", "模型服务返回了不兼容的数据。")
        safe: dict[str, int] = {}
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = usage.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                safe[key] = value
        self.last_usage = safe

    @staticmethod
    def _raise_stream_error(error: Any) -> None:
        if isinstance(error, dict):
            marker = str(error.get("code", "")).lower() + str(error.get("type", "")).lower()
            if "auth" in marker or "key" in marker:
                raise ModelError("auth", "身份验证失败，请检查本机 API 密钥。")
            if "rate" in marker or "429" in marker:
                raise ModelError("rate_limit", "服务限流，请稍后手动重试。")
        raise ModelError("protocol", "模型服务返回了不兼容的数据。")
