import types
import pytest
from unittest.mock import MagicMock

from CourtListenerHelper import (
    sanitize_filename,
    ApiClient,
    CaseSearcher,
    CaseDownloader,
    get_case_id,
    get_case_url,
    API_BASE,
)


def test_sanitize_filename_simple():
    assert sanitize_filename('simple-name') == 'simple-name'


def test_sanitize_filename_special_chars():
    name = 'Hello:Case/Name?'
    assert sanitize_filename(name) == 'Hello_Case_Name_'


def test_sanitize_filename_with_spaces():
    name = 'A Case Name'
    assert sanitize_filename(name) == 'A Case Name'


def test_case_searcher_pagination():
    mock_client = MagicMock()
    first_resp = MagicMock()
    first_resp.json.return_value = {
        'results': [{'id': 1, 'url': '/case/1', 'name': 'Keyword Case'}],
        'next': '/search/?page=2'
    }
    first_resp.content = b'{}'
    second_resp = MagicMock()
    second_resp.json.return_value = {
        'results': [{'id': 2, 'url': '/case/2', 'name': 'Another keyword'}],
        'next': None
    }
    second_resp.content = b'{}'
    mock_client.get.side_effect = [first_resp, second_resp]
    searcher = CaseSearcher(mock_client)
    results = list(searcher.search('keyword'))
    assert results == [
        {'id': 1, 'url': '/case/1', 'name': 'Keyword Case'},
        {'id': 2, 'url': '/case/2', 'name': 'Another keyword'},
    ]
    assert mock_client.get.call_count == 2


def test_case_searcher_pagination_absolute_next():
    mock_client = MagicMock()
    first = MagicMock()
    first.json.return_value = {
        'results': [{'id': 1, 'url': '/case/1', 'name': 'kw first'}],
        'next': 'https://example.com/api/search/?page=2'
    }
    first.content = b'{}'
    second = MagicMock()
    second.json.return_value = {
        'results': [{'id': 2, 'url': '/case/2', 'name': 'KW second'}],
        'next': None
    }
    second.content = b'{}'
    mock_client.get.side_effect = [first, second]
    searcher = CaseSearcher(mock_client)
    results = list(searcher.search('kw'))
    assert results == [
        {'id': 1, 'url': '/case/1', 'name': 'kw first'},
        {'id': 2, 'url': '/case/2', 'name': 'KW second'},
    ]
    assert mock_client.get.call_count == 2


def test_case_searcher_keyword_filter_excludes_non_matching():
    mock_client = MagicMock()
    resp = MagicMock()
    resp.json.return_value = {
        'results': [{'id': 3, 'url': '/case/3', 'name': 'other case'}],
        'next': None
    }
    resp.content = b'{}'
    mock_client.get.return_value = resp
    searcher = CaseSearcher(mock_client)
    results = list(searcher.search('target'))
    assert results == [
        {'id': 3, 'url': '/case/3', 'name': 'other case'}
    ]
    mock_client.get.assert_called_once()


def test_case_searcher_accepts_jurisdiction_list():
    mock_client = MagicMock()
    resp = MagicMock()
    resp.json.return_value = {'results': [], 'next': None}
    resp.content = b'{}'
    mock_client.get.return_value = resp
    searcher = CaseSearcher(mock_client)
    list(searcher.search('foo', courts=['a', 'b']))
    args, kwargs = mock_client.get.call_args
    assert kwargs['params']['court'] == 'a,b'


def test_api_client_retry(monkeypatch):
    response = MagicMock(status_code=200)
    response.content = b"{}"

    def fake_get(self, url, headers=None, params=None, timeout=None, stream=False):
        return response

    import requests
    monkeypatch.setattr(requests.Session, 'get', fake_get)

    client = ApiClient('http://example.com', 't')
    resp = client.get('/path')
    assert resp is response
    assert client.metrics['call_count'] == 1
    assert client.metrics['total_bytes'] == len(b"{}")


def test_case_downloader_download():
    mock_client = MagicMock()
    response = MagicMock()
    response.json.return_value = {'name': 'n', 'cluster_id': 1}
    response.content = b'{}'
    mock_client.get.return_value = response
    downloader = CaseDownloader(mock_client)
    downloader._fetch_opinions = MagicMock(return_value=[{'id': 1}])
    result = downloader.download_opinions({'id': 1, 'url': '/case/1'})
    assert result == {
        'case_id': '1',
        'case_meta': {'name': 'n', 'cluster_id': 1},
        'opinions': [{'id': 1}],
    }
    mock_client.get.assert_called_with('/case/1')


def test_case_downloader_absolute_url():
    mock_client = MagicMock()
    response = MagicMock()
    response.json.return_value = {'name': 'n', 'cluster_id': 5}
    response.content = b'{}'
    mock_client.get.return_value = response
    downloader = CaseDownloader(mock_client)
    downloader._fetch_opinions = MagicMock(return_value=[])
    url = 'https://example.com/api/case/1'
    result = downloader.download_opinions({'id': 1, 'url': url})
    assert result == {
        'case_id': '1',
        'case_meta': {'name': 'n', 'cluster_id': 5},
        'opinions': [],
    }
    mock_client.get.assert_called_with(url)


def test_case_downloader_missing_cluster_id_uses_id():
    """download_opinions should fall back to 'id' when 'cluster_id' is absent."""
    mock_client = MagicMock()
    response = MagicMock()
    response.json.return_value = {'name': 'n', 'id': 7}
    response.content = b'{}'
    mock_client.get.return_value = response
    downloader = CaseDownloader(mock_client)
    downloader._fetch_opinions = MagicMock(return_value=[])
    result = downloader.download_opinions({'id': 7, 'url': '/case/7'})

    assert result == {
        'case_id': '7',
        'case_meta': {'name': 'n', 'id': 7},
        'opinions': [],
    }
    downloader._fetch_opinions.assert_called_with(7)


def test_fetch_opinions_fetches_sub_opinions():
    client = MagicMock()
    main_resp = MagicMock()
    main_resp.json.return_value = {
        'results': [
            {
                'id': 1,
                'type': 'major',
                'plain_text': 'main',
                'sub_opinions': ['http://sub1', 'http://sub2'],
            }
        ]
    }
    main_resp.content = b'{}'
    sub1 = MagicMock()
    sub1.json.return_value = {'id': 2, 'type': 'sub', 'plain_text': 's1'}
    sub1.content = b'{}'
    sub2 = MagicMock()
    sub2.json.return_value = {'id': 3, 'type': 'sub', 'plain_text': 's2'}
    sub2.content = b'{}'
    client.get.side_effect = [main_resp, sub1, sub2]

    downloader = CaseDownloader(client)
    data = downloader._fetch_opinions(10)

    assert len(data) == 1
    assert len(data[0]['sub_opinions']) == 2
    assert data[0]['sub_opinions'][0]['id'] == 2
    assert data[0]['sub_opinions'][1]['id'] == 3
    assert client.get.call_args_list[1][0][0] == 'http://sub1'
    assert client.get.call_args_list[2][0][0] == 'http://sub2'


def test_api_client_absolute_path(monkeypatch):
    called = {}

    def fake_get(url, headers=None, params=None, timeout=None, stream=False):
        called['url'] = url
        response = MagicMock(status_code=200)
        response.content = b''
        return response

    client = ApiClient('http://example.com', 't')
    monkeypatch.setattr(client.session, 'get', fake_get)
    client.get('https://foo.com/bar')
    assert called['url'] == 'https://foo.com/bar'


def test_get_case_id_variants():
    meta = {'id': 1, 'cluster_id': 2, 'docket_id': 3}
    assert get_case_id(meta) == '1'
    meta = {'cluster_id': 2, 'docket_id': 3}
    assert get_case_id(meta) == '2'
    meta = {'docket_id': 3}
    assert get_case_id(meta) == '3'


def test_get_case_url_variants():
    assert get_case_url({'url': '/case/1'}) == '/case/1'
    assert get_case_url({'resource_uri': '/case/2'}) == '/case/2'
    assert get_case_url({'cluster_id': 3}) == '/clusters/3/'
    assert (
        get_case_url({'absolute_url': '/api/rest/v4/opinions/4/'})
        == '/api/rest/v4/opinions/4/'
    )
    with pytest.raises(KeyError):
        get_case_url({'absolute_url': '/opinion/5'})


def test_get_case_url_prefers_cluster_id():
    meta = {'cluster_id': 42, 'absolute_url': '/opinion/42/foo'}
    assert get_case_url(meta) == '/clusters/42/'


def test_gui_download_cases_handles_cluster_id(tmp_path):
    """GuiApplication should fall back to alternate IDs when 'id' is missing."""
    from gui import GuiApplication

    dummy = types.SimpleNamespace()
    dummy.client = MagicMock()
    dummy.client.get_metrics.return_value = {
        'call_count': 1,
        'total_bytes': 1,
        'total_time': 0,
    }
    dummy.searcher = MagicMock()
    dummy.downloader = MagicMock()
    dummy.progress = types.SimpleNamespace(step=lambda n: None)
    dummy.start_button = types.SimpleNamespace(config=lambda **kw: None)
    dummy.log_messages = []

    def log(msg):
        dummy.log_messages.append(msg)

    dummy.log_message = log

    dummy.searcher.search.return_value = [
        {"cluster_id": 99, "url": "/case/99", "name": "Cluster Case"}
    ]
    dummy.downloader.download_opinions.return_value = {
        "case_id": 99,
        "cluster_id": 99,
        "opinions": [],
    }

    out_dir = tmp_path / "cases"
    out_dir.mkdir()
    GuiApplication.download_cases(dummy, ["kw"], str(out_dir))

    expected_json = out_dir / "Cluster Case_99_opinions.json"
    assert expected_json.exists()


def test_recap_downloader_get_entries_filters():
    from CourtListenerHelper import RecapDownloader

    client = MagicMock()
    resp = MagicMock()
    resp.json.return_value = {
        'results': [
            {'id': 1, 'recap_document': 10},
            {'id': 2}
        ]
    }
    resp.content = b'{}'
    client.get.return_value = resp

    rd = RecapDownloader(client, 'u', 'p')
    entries = rd.get_recap_entries(5)

    assert entries == [{'id': 1, 'recap_document': 10}]
    client.get.assert_called_with('/dockets/5/entries/')


def test_recap_downloader_request_pdf():
    from CourtListenerHelper import RecapDownloader

    client = MagicMock()
    resp = MagicMock()
    resp.json.return_value = {'ok': True}
    resp.content = b'{}'
    client.post.return_value = resp

    rd = RecapDownloader(client, 'user', 'pass')
    result = rd.request_pdf(123)

    assert result == {'ok': True}
    client.post.assert_called_with(
        '/recap-fetch/',
        data={
            'request_type': '2',
            'recap_document': '123',
            'pacer_username': 'user',
            'pacer_password': 'pass',
        },
    )


def test_recap_downloader_poll_entry():
    from CourtListenerHelper import RecapDownloader

    client = MagicMock()
    first = MagicMock()
    first.json.return_value = {'file': {}}
    first.content = b'{}'
    second = MagicMock()
    second.json.return_value = {'file': {'url': 'http://pdf'}}
    second.content = b'{}'
    client.get.side_effect = [first, second]

    rd = RecapDownloader(client, 'u', 'p')
    url = rd.poll_entry(7, interval=0, timeout=1)

    assert url == 'http://pdf'
    assert client.get.call_count == 2


def test_recap_downloader_fetch_first_pdf():
    from CourtListenerHelper import RecapDownloader

    rd = RecapDownloader(MagicMock(), 'u', 'p')
    rd.get_recap_entries = MagicMock(return_value=[{'id': 1, 'recap_document': 2}])
    rd.request_pdf = MagicMock()
    rd.poll_entry = MagicMock(return_value='http://pdf')
    rd.download_pdf = MagicMock(return_value=b'pdf')

    data = rd.fetch_first_pdf(99)

    assert data == b'pdf'
    rd.request_pdf.assert_called_with(2)
    rd.poll_entry.assert_called_with(1)
    rd.download_pdf.assert_called_with('http://pdf')


def test_api_client_post_records_metrics(monkeypatch):
    from CourtListenerHelper import ApiClient
    import requests

    def fake_post(url, headers=None, data=None):
        resp = MagicMock(status_code=200)
        resp.content = b'foo'
        return resp

    monkeypatch.setattr(requests, 'post', fake_post)

    client = ApiClient('http://example.com', 't')
    client.post('/path', data={'a': 1})

    assert client.metrics['call_count'] == 1
    assert client.metrics['total_bytes'] == len(b'foo')

