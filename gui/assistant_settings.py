"""Provider settings; optional keys are protected by the current Windows account."""
import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import threading


def _dpapi(raw, decrypt=False):
    if os.name != 'nt':
        raise ValueError('此系统不支持Windows密钥保护，请使用仅本次会话模式')
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    source, target = Blob(len(raw), buffer), Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        function = crypt.CryptUnprotectData
        function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                             ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        description = None
    else:
        function = crypt.CryptProtectData
        function.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p,
                             ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        description = 'MCU Workbench assistant'
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), description, None, None, None, 1, ctypes.byref(target)):
        raise ValueError('Windows密钥保护失败，请重新输入密钥或选择仅本次会话')
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(ctypes.cast(target.data, ctypes.c_void_p))


class AssistantSettings:
    def __init__(self, root):
        self.path = Path(root) / 'settings.json'
        self._lock = threading.RLock()
        self._key = ''
        self._data = {'provider': '', 'model': '', 'reasoning_effort': 'max', 'max_tokens': 8192, 'remember': False,
                      'kimi_region': 'international'}
        self._error = ''
        if self.path.is_file():
            try:
                saved = json.loads(self.path.read_text(encoding='utf-8'))
                self._data.update({key: saved[key] for key in self._data if key in saved})
                if saved.get('protectedKey'):
                    self._key = _dpapi(base64.b64decode(saved['protectedKey'], validate=True), True).decode('utf-8')
            except (ValueError, OSError, TypeError):
                self._error = '保存的设置或密钥无法读取，请重新配置'

    def state(self):
        with self._lock:
            return {**self._data, 'hasKey': bool(self._key), 'error': self._error}

    def save(self, payload):
        provider, model = payload.get('provider'), payload.get('model')
        allowed = {'kimi': {'kimi-k3', 'kimi-k2.6', 'kimi-k2.7-code'},
                   'kimi-code': {'k3', 'k3-256k'},
                   'deepseek': {'deepseek-v4-pro', 'deepseek-flash'}}
        if provider not in allowed or model not in allowed[provider]:
            raise ValueError('请选择已核对协议的服务商和模型')
        effort = payload.get('reasoning_effort', 'max')
        tokens = payload.get('max_tokens', 8192)
        region = payload.get('kimi_region', self._data['kimi_region'])
        if region not in ('china', 'international'):
            raise ValueError('请选择Kimi国内或国际接口')
        if effort not in ('low', 'high', 'max') or type(tokens) is not int or not 1024 <= tokens <= 131072:
            raise ValueError('推理档位或输出上限无效')
        key = payload.get('apiKey', '')
        if not isinstance(key, str) or len(key) > 4096 or any(ch.isspace() for ch in key):
            raise ValueError('密钥格式无效')
        with self._lock:
            proposed = '' if payload.get('clearKey') or provider != self._data['provider'] else self._key
            if key and not payload.get('clearKey'):
                proposed = key
            data = {'provider': provider, 'model': model, 'reasoning_effort': effort,
                    'max_tokens': tokens, 'remember': payload.get('remember') is True, 'kimi_region': region}
            saved = dict(data)
            if data['remember'] and proposed:
                saved['protectedKey'] = base64.b64encode(_dpapi(proposed.encode())).decode('ascii')
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(saved), encoding='utf-8')
            temporary.replace(self.path)
            self._data, self._key, self._error = data, proposed, ''
            return self.state()

    def client_config(self):
        with self._lock:
            if not self._key:
                raise ValueError('请先在助手设置中输入API密钥')
            return {key: self._data[key] for key in ('provider', 'model', 'reasoning_effort', 'max_tokens', 'kimi_region')} | {'api_key': self._key}
