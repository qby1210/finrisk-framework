"""随项目交付的数据包只读 API 冒烟测试。"""

from fastapi.testclient import TestClient

from api.app import app

client = TestClient(app)


def test_case_statistics_and_detail_are_available() -> None:
    statistics = client.get("/api/cases/statistics")
    page = client.get("/api/cases", params={"page": 1, "page_size": 1})

    assert statistics.status_code == 200
    assert statistics.json()["total_cases"] >= 7_328
    assert page.status_code == 200
    assert page.json()["items"]
    case_id = page.json()["items"][0]["case_id"]
    detail = client.get(f"/api/cases/{case_id}")
    assert detail.status_code == 200
    assert detail.json()["case_id"] == case_id
