"""number 实体属性 ↔ config_flow 选择器参数交叉对拍（R1 P3#2）。

本机无 homeassistant/voluptuous 包，无法 import 两侧模块执行；改用 ast 解析
两个源文件的字面声明对拍，钉住「值域/步长/单位/mode 在 number 与 config_flow
两侧一致 + unique_id 族与 storage 键对齐」的交叉契约——单侧改动即红，杜绝
「表单接受但实体回弹」的静默不一致。P3 裁定选纯测试侧（零生产改动）而非
const.py 常量单一来源：按非必要不增变量，首选需在生产三文件新增 4 组常量
并改约 16 处消费点，次选只动 tests。
"""

import ast
from pathlib import Path

COMPONENT_DIR = (
    Path(__file__).resolve().parents[1]
    / "custom_components" / "water_heater_optimizer"
)

# 实体类 ↔ config_flow CONF 常量（按 storage 键一一对应）
MAPPING = {
    "TargetTempNumber": "CONF_TARGET_TEMP",
    "HotWaterRatioNumber": "CONF_HOT_WATER_RATIO",
    "MinTempNumber": "CONF_MIN_TEMP",
    "MaxTempNumber": "CONF_MAX_TEMP",
}


def _literal(node):
    """ast 节点 → 可比较字面值（Constant 原值 / NumberMode 尾名小写 / Name 常量 id）。"""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Attribute):
        return node.attr.lower()  # NumberMode.BOX → "box"
    if isinstance(node, ast.Name):
        return node.id  # CONF_X 常量名（number 与 config_flow 两侧以同一 id 对拍）
    return None


def _class_attrs(tree, base_name):
    """收集继承 base_name 的类的类级属性 {class_name: {attr: literal}}。"""
    out = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if not any(getattr(b, "id", "") == base_name for b in node.bases):
            continue
        attrs = {}
        for stmt in node.body:
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                key = getattr(stmt.targets[0], "id", None)
                if key:
                    attrs[key] = _literal(stmt.value)
        out[node.name] = attrs
    return out


def _call_name(node):
    """调用名尾段：Name(NumberSelector，顶层 from-import) 或 Attribute(vol.Required) 统一取尾名。"""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _selector_params(tree):
    """config_flow 的 {CONF 常量名: {min,max,step,unit_of_measurement,mode}}。

    表单结构 vol.Required(CONF_X, ...): NumberSelector(NumberSelectorConfig(...))，
    key/value 是 ast.Dict 的同级子节点，成对扫描；同一键在初始流与 options
    流各出现一次，两处参数不一致即失败（两侧 schema 互证）。
    """
    out = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key_node, value_node in zip(node.keys, node.values):
            if not (
                isinstance(key_node, ast.Call)
                and _call_name(key_node.func) in ("Required", "Optional")
                and key_node.args
            ):
                continue
            conf_name = getattr(key_node.args[0], "id", None)
            if not (conf_name and conf_name.startswith("CONF_")):
                continue
            # value_node 即 NumberSelector(...) 包装调用，其首个位置参数才是
            # NumberSelectorConfig(...)（NumberSelectorConfig 本身全关键字实参，
            # 无位置参数可再下钻）
            config = value_node.args[0] if (
                isinstance(value_node, ast.Call) and value_node.args
            ) else None
            if not (
                isinstance(config, ast.Call)
                and _call_name(config.func) == "NumberSelectorConfig"
            ):
                continue  # EntitySelector 等非 number 选择器不在本钉范围
            params = {kw.arg: _literal(kw.value) for kw in config.keywords}
            if conf_name in out and out[conf_name] != params:
                raise AssertionError(
                    f"config_flow 两处 {conf_name} 选择器参数不一致："
                    f"{out[conf_name]} != {params}"
                )
            out[conf_name] = params
    return out


def _number_entities():
    tree = ast.parse((COMPONENT_DIR / "number.py").read_text(encoding="utf-8"))
    return _class_attrs(tree, "_OptimizerNumber")


def _flow_selectors():
    tree = ast.parse((COMPONENT_DIR / "config_flow.py").read_text(encoding="utf-8"))
    return _selector_params(tree)


def test_number_ranges_match_config_flow_selectors():
    entities = _number_entities()
    selectors = _flow_selectors()
    for class_name, conf_name in MAPPING.items():
        ent = entities[class_name]
        sel = selectors[conf_name]
        assert ent["_attr_native_min_value"] == sel["min"], class_name
        assert ent["_attr_native_max_value"] == sel["max"], class_name
        assert ent["_attr_native_step"] == sel["step"], class_name
        # unit 交叉对拍：config_flow 显式写了 unit_of_measurement ↔ 实体同形
        assert (
            ent.get("_attr_native_unit_of_measurement")
            == sel.get("unit_of_measurement")
        ), class_name
        # mode：config_flow 显式写了 mode ↔ 实体 _attr_mode（未写侧不比，
        # NumberSelector 的默认呈现不属于本钉目标）
        if "mode" in sel:
            assert ent["_attr_mode"] == sel["mode"], class_name
    # 实体侧 mode 全量钉死（防 copy-paste 抄错）：ratio 唯一 slider，其余 BOX
    modes = {name: entities[name].get("_attr_mode") for name in MAPPING}
    assert modes == {
        "TargetTempNumber": "box",
        "HotWaterRatioNumber": "slider",
        "MinTempNumber": "box",
        "MaxTempNumber": "box",
    }


def test_number_identity_fields_are_distinct_and_keyed():
    entities = _number_entities()
    const_tree = ast.parse(
        (COMPONENT_DIR / "const.py").read_text(encoding="utf-8")
    )
    consts = {}
    for stmt in const_tree.body:
        target_id = (
            getattr(stmt.targets[0], "id", "")
            if isinstance(stmt, ast.Assign) else ""
        )
        if target_id.startswith("CONF_"):
            consts[target_id] = stmt.value.value
    # TITLE_SUFFIX 全非空且互不相同（copy-paste 抄错即红）
    titles = [entities[c].get("TITLE_SUFFIX") for c in MAPPING]
    assert all(titles) and len(set(titles)) == len(titles)
    # unique_id 命名族与 storage 键对齐：UNIQUE_SUFFIX == CONFIG_KEY 常量的字符串值
    for class_name in MAPPING:
        ent = entities[class_name]
        assert ent["CONFIG_KEY"] in consts, class_name
        assert consts[ent["CONFIG_KEY"]] == ent["UNIQUE_SUFFIX"], class_name
