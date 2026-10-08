import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from gui.server import Session, make_server


def test_assistant_routes_are_authenticated_and_work_without_program(tmp_path):
    server = make_server(0, session=Session(master=None, output=tmp_path))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    def call(path, data=None, token=None):
        request = Request(server.origin + path, data=None if data is None else json.dumps(data).encode(),
                          headers={'Content-Type': 'application/json', 'X-GUI-Session': token or server.token})
        try:
            with urlopen(request) as response:
                return response.status, response.read()
        except HTTPError as error:
            return error.code, error.read()
    try:
        assert call('/assistant')[0] == 200
        assert call('/api/assistant/state', token='bad')[0] == 403
        code, raw = call('/api/assistant/state')
        assert code == 200
        assert json.loads(raw)['settings']['hasKey'] is False
        code, raw = call('/api/assistant/start', {'requestId': 'one', 'text': 'help', 'context': {}})
        assert code == 422
        assert 'API' in raw.decode()
        assert call('/api/assistant/arbitrary', {})[0] == 404
        assert call('/api/assistant/clear', {}, token='bad')[0] == 403
        assert call('/api/assistant/confirm-knowledge', {}, token='bad')[0] == 403
        from tests.test_assistant_knowledge import REQUEST, answers
        from tests.test_assistant_tasks import Scripted, tool, wait
        record = wait(server.assistant, server.assistant.start({'requestId': 'missing-reset', 'text': 'PA4 MCO',
            'context': {}, 'conditions': {'product': 'PCD009', 'platform': 'chroma', 'initialState': 'reset'}},
            Scripted([tool('prepare_swd', {'request': REQUEST})]), materials=server.swd.materials().state())['id'])
        assert record['status'] == 'needs_input'
        code, raw = call('/api/assistant/confirm-knowledge', {'id': record['id'], 'context': {}, 'answers': answers(record)})
        assert code == 200 and json.loads(raw)['status'] == 'completed', raw
        assert json.loads(call('/api/assistant/clear', {})[1]) == {'removed': 1}
    finally:
        server.shutdown()
        server.server_close()
