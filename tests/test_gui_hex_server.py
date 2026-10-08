import json
from pathlib import Path
import threading
import time
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
import zipfile
from io import BytesIO
import pytest

from gui.server import Session, make_server
from tests.test_gui_hex_conversion import sample_hex


def test_hex_http_batch_preview_download_and_clear(tmp_path):
    service = make_server(0, Session(master=None, output=tmp_path))
    threading.Thread(target=service.serve_forever, daemon=True).start()
    def request(path, payload=None, raw=None, auth=True):
        headers = {'X-GUI-Session':service.token if auth else '', 'X-File-Name':quote('程序.hex'),
                   'Content-Type':'application/octet-stream' if raw is not None else 'application/json'}
        data = raw if raw is not None else json.dumps(payload).encode() if payload is not None else None
        return urlopen(Request(service.origin+path, data=data, headers=headers), timeout=10)
    try:
        assert b'hex.js' in request('/hex').read()
        with pytest.raises(HTTPError) as error:
            request('/api/hex/state', auth=False)
        assert error.value.code == 403
        ids = [json.load(request('/api/hex/input', raw=sample_hex()))['id'] for _ in range(2)]
        with pytest.raises(HTTPError):
            request('/api/hex/start', {'taskIds':ids, 'profileId':'swd-ptxxx-template'})
        state = json.load(request('/api/hex/start', {'taskIds':ids, 'profileId':'swd-sram-pt100', 'pins':['CLK','DATA','RST'], 'verify':False, 'outputPlatform':'both'}))
        assert state['running']
        with pytest.raises(HTTPError):
            request('/api/hex/clear', {})
        deadline = time.monotonic()+20
        while service.hex.state()['running'] and time.monotonic()<deadline:
            time.sleep(.05)
        state = json.load(request('/api/hex/state'))
        assert [t['status'] for t in state['tasks']] == ['completed','completed']
        task = state['tasks'][0]
        name = task['result']['files'][0]['name']
        assert b'SPM_PATTERN' in request('/api/hex/preview?task='+ids[0]+'&file='+quote(name)).read()
        with pytest.raises(HTTPError):
            request('/api/hex/preview?task='+ids[0]+'&file=../input.hex')
        blob = request('/api/hex/download?task='+ids[0]).read()
        with zipfile.ZipFile(BytesIO(blob)) as package:
            assert name in package.namelist()
            assert any(n.endswith('.sd') for n in package.namelist())
            assert b'CLK,DATA,RST;' in package.read(name)
            metadata = json.loads(package.read('conversion.json'))
            assert metadata['profile']['pins'] == ['CLK','DATA','RST']
            assert metadata['profile']['verify'] is False
            assert metadata['conversion']['verify'] is False
            assert json.loads(package.read('conversion.json'))['profile']['id'] == 'swd-sram-pt100'
        archive = service.hex.download(ids[0])
        assert not json.load(request('/api/hex/clear', {}))['tasks']
        assert archive.is_file()
        from gui.hex_workspace import HexWorkspace
        assert HexWorkspace(service.hex.root).state()['tasks'] == []
    finally:
        service.shutdown()
        service.server_close()
