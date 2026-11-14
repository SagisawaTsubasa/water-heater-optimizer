"""strings.json ↔ translations/ 镜像对拍（R1 P2#1 防回归钉）。

NTFS 大小写不敏感曾让 zh-Hans.json 被写成 zh-hans.json 而磁盘对拍漏检
（124 批同型教训；HA 运行时按 hass.config.language 拼大小写敏感的
translations/<language>.json）；本钉按字节级文件名断言 + 键结构镜像。
"""
import json
from pathlib import Path

COMPONENT_DIR = (
    Path(__file__).resolve().parents[1]
    / "custom_components" / "water_heater_optimizer"
)
EXPECTED_NAMES = ["en.json", "zh-Hans.json", "zh.json"]


def _load(rel: str):
    with open(COMPONENT_DIR / rel, encoding="utf-8") as f:
        return json.load(f)


def _key_tree(node):
    """压平成纯键结构（叶子置 None），比对翻译键集合是否镜像。"""
    if isinstance(node, dict):
        return {k: _key_tree(v) for k, v in node.items()}
    return None


def test_translation_filenames_exact_case():
    names = sorted(p.name for p in (COMPONENT_DIR / "translations").glob("*.json"))
    assert names == EXPECTED_NAMES


def test_strings_key_tree_matches_each_translation():
    strings = _key_tree(_load("strings.json"))
    for name in EXPECTED_NAMES:
        assert _key_tree(_load(f"translations/{name}")) == strings, name
