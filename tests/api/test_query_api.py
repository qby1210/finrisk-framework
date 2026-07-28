"""FastAPI Query 分类增强接口测试。"""

from fastapi.testclient import TestClient

from api.app import app

client = TestClient(app)


def test_index_serves_workbench() -> None:
    """首页应返回三模块工作台页面。"""

    response = client.get("/")

    assert response.status_code == 200
    assert "风险查询" in response.text
    assert "案例录入" in response.text
    assert "全部案例" in response.text


def test_text_query_endpoint_returns_sentence_list() -> None:
    """文字接口应返回文件级分类和逐句增强结果。"""

    response = client.post(
        "/api/query/analyze/text",
        json={
            "text": "限时活动现已开启！立即扫码了解产品详情。",
            "metadata": {"source_channel": "campaign"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["classification"]["selected_category"]["category_code"] == "marketing_content"
    assert len(payload["sentences"]) == 2
    assert all(
        item["category"]["category_code"] == "marketing_content" for item in payload["sentences"]
    )


def test_file_query_endpoint_reads_text_file() -> None:
    """上传文件接口应先读取文件再分类和切句。"""

    response = client.post(
        "/api/query/analyze/file",
        files={
            "file": (
                "chat.txt",
                "客户：这款产品可以赎回吗？顾问：您好，我帮您查询。",
                "text/plain",
            )
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["input_type"] == "file"
    assert payload["source_filename"] == "chat.txt"
    assert (
        payload["classification"]["selected_category"]["category_code"] == "customer_communication"
    )
