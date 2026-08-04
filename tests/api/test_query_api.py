"""FastAPI 六类 Query 分类与原文映射接口测试。"""

from fastapi.testclient import TestClient

from api.app import app, get_query_service
from application.query_service import QueryProcessingService
from query.classification import QuerySceneClassifier


def _rule_only_service() -> QueryProcessingService:
    return QueryProcessingService(classifier=QuerySceneClassifier(None))


app.dependency_overrides[get_query_service] = _rule_only_service
client = TestClient(app)


def test_index_serves_workbench() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "风险查询" in response.text
    assert "案例录入" in response.text
    assert "全部案例" in response.text


def test_classifier_status_reports_rule_and_llm_state() -> None:
    response = client.get("/api/query/classifier")

    assert response.status_code == 200
    assert response.json()["llm_configured"] is False
    assert response.json()["taxonomy_version"] == "query-scene-2.0"


def test_text_query_endpoint_returns_exact_risk_sentence_fields() -> None:
    response = client.post(
        "/api/query/analyze/text",
        json={"text": "营销海报，限时活动现已开启！立即扫码领取专属权益。"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["classification"]["scene"] == "ST1_poster_sms_social"
    assert len(payload["sentences"]) == 2
    assert set(payload["sentences"][0]) == {"query_id", "sentence_id", "scene", "text"}
    assert payload["sentences"][0]["sentence_id"] == payload["source_mappings"][0]["sentence_id"]


def test_file_query_endpoint_returns_source_regions() -> None:
    response = client.post(
        "/api/query/analyze/file",
        files={
            "file": (
                "callback.txt",
                "回访话术。坐席：您好，本次致电进行客户回访；客户：好的。",
                "text/plain",
            )
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["classification"]["scene"] == "ST5_training_telemarketing_callback"
    assert payload["source_filename"] == "callback.txt"
    assert payload["source_mappings"][0]["regions"]


def test_ambiguous_text_without_llm_returns_service_unavailable() -> None:
    response = client.post(
        "/api/query/analyze/text",
        json={"text": "这是今天整理的一份材料。"},
    )

    assert response.status_code == 503
    assert "DEEPSEEK_API_KEY" in response.json()["detail"]
