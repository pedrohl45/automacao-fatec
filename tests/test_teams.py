from automacao_fatec.teams import extract_graph_token


def test_extract_token_de_requisicao_graph():
    headers = {"authorization": "Bearer xyz"}
    assert extract_graph_token("https://graph.microsoft.com/v1.0/me", headers) == "Bearer xyz"


def test_ignora_outros_hosts_e_esquemas():
    assert extract_graph_token("https://example.com/x", {"authorization": "Bearer xyz"}) is None
    assert (
        extract_graph_token("https://graph.microsoft.com/v1.0/me", {"authorization": "Basic abc"})
        is None
    )
    assert extract_graph_token("https://graph.microsoft.com/v1.0/me", {}) is None
