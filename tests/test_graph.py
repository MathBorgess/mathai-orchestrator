from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from orch.errors import GraphError
from orch.graph import load_graph

REPO = Path(__file__).resolve().parents[1]


def test_v1_loads() -> None:
    graph = load_graph(REPO / "graphs" / "v1.yaml", root=REPO)
    assert graph.id == "v1"
    assert set(graph.instances) == {"build.a", "build.b", "build.c"}
    assert graph.width == 3
    assert graph.stop.all_of == ("gate", "contract")
    merge = graph.nodes["merge"]
    assert merge.type == "join"
    assert merge.owns == ("a-b", "a-c", "b-c")


def test_v0_refused_as_v1_schema() -> None:
    with pytest.raises(GraphError) as exc:
        load_graph(REPO / "graphs" / "v0.yaml", root=REPO)
    assert exc.value.code in {"V-19", "V-2", "V-timeout"}


def _dump(tmp: Path, data: dict, name: str = "v1.yaml") -> Path:
    graphs = tmp / "graphs"
    graphs.mkdir(parents=True)
    path = graphs / name
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path


def _copy_support(tmp: Path) -> None:
    (tmp / "prompts").mkdir()
    for name in ("scout.md", "builder.md", "merge.md", "baseline.md"):
        (tmp / "prompts" / name).write_text((REPO / "prompts" / name).read_text())
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    for name in ("has-sections", "gate-report", "check-writes"):
        dest = bin_dir / name
        dest.write_bytes((REPO / "bin" / name).read_bytes())
        dest.chmod(0o755)


def _v1_data() -> dict:
    return yaml.safe_load((REPO / "graphs" / "v1.yaml").read_text())


def test_id_must_match_stem(tmp_path: Path) -> None:
    _copy_support(tmp_path)
    data = _v1_data()
    path = _dump(tmp_path, data, "other.yaml")
    with pytest.raises(GraphError) as exc:
        load_graph(path, root=tmp_path)
    assert exc.value.code == "V-1"


def test_missing_baseline(tmp_path: Path) -> None:
    _copy_support(tmp_path)
    data = _v1_data()
    del data["baseline"]
    path = _dump(tmp_path, data)
    with pytest.raises(GraphError) as exc:
        load_graph(path, root=tmp_path)
    assert exc.value.code == "V-19"


def test_overlapping_partition_writes(tmp_path: Path) -> None:
    _copy_support(tmp_path)
    data = _v1_data()
    data["nodes"][1]["partition"][0]["writes"] = ["out/a/**"]
    data["nodes"][1]["partition"][1]["writes"] = ["out/a/extra.md"]
    path = _dump(tmp_path, data)
    with pytest.raises(GraphError) as exc:
        load_graph(path, root=tmp_path)
    assert exc.value.code == "V-22"
    assert "build.a" in exc.value.message and "build.b" in exc.value.message


def test_bad_owns(tmp_path: Path) -> None:
    _copy_support(tmp_path)
    data = _v1_data()
    for node in data["nodes"]:
        if node["id"] == "merge":
            node["owns"] = ["a-b"]
    path = _dump(tmp_path, data)
    with pytest.raises(GraphError) as exc:
        load_graph(path, root=tmp_path)
    assert exc.value.code == "V-11"


def test_always_only_fanout_to_join(tmp_path: Path) -> None:
    _copy_support(tmp_path)
    data = _v1_data()
    data["edges"].append({"from": "scout", "to": "merge", "on": "always"})
    path = _dump(tmp_path, data)
    with pytest.raises(GraphError) as exc:
        load_graph(path, root=tmp_path)
    assert exc.value.code == "V-10"


def test_cycle_refused(tmp_path: Path) -> None:
    _copy_support(tmp_path)
    data = _v1_data()
    data["edges"].append(
        {
            "from": "gate",
            "to": "merge",
            "on": "check_passed",
            "check": "gate",
        }
    )
    path = _dump(tmp_path, data)
    with pytest.raises(GraphError) as exc:
        load_graph(path, root=tmp_path)
    assert exc.value.code == "V-6"


def test_check_cannot_be_claude(tmp_path: Path) -> None:
    _copy_support(tmp_path)
    data = _v1_data()
    for node in data["nodes"]:
        if node["id"] == "gate":
            node["run"] = ["claude", "-p", "hi"]
    path = _dump(tmp_path, data)
    with pytest.raises(GraphError) as exc:
        load_graph(path, root=tmp_path)
    assert exc.value.code in {"V-17", "V-18"}


def test_template_cannot_declare_writes(tmp_path: Path) -> None:
    _copy_support(tmp_path)
    data = _v1_data()
    data["nodes"][1]["template"]["writes"] = ["out/x.md"]
    path = _dump(tmp_path, data)
    with pytest.raises(GraphError) as exc:
        load_graph(path, root=tmp_path)
    assert exc.value.code == "V-9"


def test_missing_prompt(tmp_path: Path) -> None:
    _copy_support(tmp_path)
    data = _v1_data()
    data["nodes"][0]["prompt"] = "prompts/does-not-exist.md"
    path = _dump(tmp_path, data)
    with pytest.raises(GraphError) as exc:
        load_graph(path, root=tmp_path)
    assert exc.value.code == "V-3"


def test_short_rationale(tmp_path: Path) -> None:
    _copy_support(tmp_path)
    data = _v1_data()
    data["nodes"][1]["rationale"] = "one line\ntwo lines\n"
    path = _dump(tmp_path, data)
    with pytest.raises(GraphError) as exc:
        load_graph(path, root=tmp_path)
    assert exc.value.code == "V-12c"
