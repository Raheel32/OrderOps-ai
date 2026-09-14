from tests.test_workflow import create, run


def test_dashboard_requires_admin(env):
    client, _, _ = env
    assert client.get('/dashboard', headers={'X-API-Key': 'wrong'}).status_code == 401


def test_dashboard_snapshot_redacts_tokens_and_joins_product_names(env):
    client, _, graph = env
    oid = create(client)
    run(graph, oid)
    response = client.get('/dashboard')
    assert response.status_code == 200
    data = response.json()
    assert len(data['products']) == 10
    assert data['orders'][0]['items'][0]['name'] == 'Tapal Danedar Tea 450g'
    assert data['orders'][0]['offers'][0]['name'] == 'Vital Tea 450g'
    assert 'token_hash' not in response.text
    assert '"token"' not in response.text
    assert 'request_hash' not in response.text
    assert data['metrics']['orders'] == 1
    assert data['metrics']['ready'] == 0
    assert data['events'][0]['payload']['text']


def test_dashboard_empty_state(env):
    client, _, _ = env
    data = client.get('/dashboard').json()
    assert data['orders'] == []
    assert data['events'] == []
    assert data['metrics']['orders'] == 0
