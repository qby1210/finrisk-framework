"""Query 应用服务测试。"""

from pathlib import Path

from application.query_service import QueryProcessingService
from domain.common import QueryInputType
from domain.query_models import QuerySceneLabel


def test_service_processes_extracted_file_into_sentences(tmp_path: Path) -> None:
    """文件读取完成后应直接输出可供 Risk 消费的句子列表。"""

    training_dir = tmp_path / "training"
    training_dir.mkdir()
    file_path = tmp_path / "notice.txt"
    file_path.write_text(
        "第一条 本办法用于规范业务办理。\n第二条 各部门应当遵照执行。",
        encoding="utf-8",
    )
    service = QueryProcessingService(training_dir=training_dir)

    result = service.process_file(file_path, source_uri="upload://notice.txt")

    assert result.input_type is QueryInputType.FILE
    assert result.source_filename == "notice.txt"
    assert result.classification.selected_category.category_code is QuerySceneLabel.FORMAL_DOCUMENT
    assert len(result.sentences) == 2
    assert result.metadata["source_uri"] == "upload://notice.txt"
