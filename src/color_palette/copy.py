from __future__ import annotations

from .constants import OFFICIAL_MODULES
from .material_fx import display_names


def official_report(analysis: dict) -> dict:
    tone = analysis["tone"]
    clipping = tone["clipping"]
    if tone["code"] == "high_key":
        tone_sentence = "高调结构，高光与亮部是主要影调重心。"
    elif tone["code"] == "low_key":
        tone_sentence = "低调结构，暗部是主要影调重心。"
    else:
        tone_sentence = "中间调结构，画面亮度重心分布均衡。"

    black = clipping["black_class"]
    white = clipping["white_class"]
    if black != "无" and white != "无":
        edge_sentence = "黑白两端均有像素碰壁，明暗跨度完整。"
    elif black != "无":
        edge_sentence = "黑端有像素碰壁，高光端仍留有余量。"
    elif white != "无":
        edge_sentence = "高光端有像素碰壁，暗部仍保留空间。"
    else:
        edge_sentence = "黑白两端均未明显碰壁，端部保留柔和余量。"

    contrast = analysis["contrast"]["level"]
    contrast_sentence = {
        "低": "明暗关系小，对比度低。",
        "中": "明暗关系中等，对比度中。",
        "高": "明暗关系大，对比度高。",
    }[contrast]

    saturation = analysis["saturation"]["level"]
    saturation_sentence = f"色彩饱和度{saturation}。"

    regions = {item["role"]: item["hue"] for item in analysis["tonal_regions"]}
    white_balance = analysis["white_balance"]["judgement"]
    hue_sentence = (
        f"综合色相：暗部{regions.get('暗部', '—')}，"
        f"中间调{regions.get('中间调', '—')}，高光{regions.get('高光', '—')}。"
    )

    skin = analysis["skin"]
    if skin["status"] == "单人":
        primary = _skin_line("① 苹果肌主锚点", skin.get("primary_anchor"))
        secondary = _skin_line("② 额头副锚点", skin.get("secondary_anchor"))
        skin_lines = [primary, secondary]
    elif skin["status"] == "多人不合并":
        skin_lines = [f"检测到{skin['face_count']}张人脸，多人物肤色不合并，不输出单一肤色数值。"]
    elif skin["status"] == "未验证":
        if skin.get("detector") == "disabled":
            skin_lines = ["肤色分析未启用，不输出肤色锚点数值。"]
        else:
            skin_lines = ["肤色样本不足，不输出肤色锚点数值。"]
    else:
        skin_lines = ["未检测到可用于稳定肤色分析的单人脸，样本不足，不输出肤色数值。"]

    effect_labels = display_names(analysis)
    light = analysis["light"]
    report = {
        "官方语言": "中文（zh-CN）",
        "官方模块": OFFICIAL_MODULES,
        "影调结构": [tone_sentence, edge_sentence],
        "明暗关系": [contrast_sentence, analysis["contrast"]["description"]],
        "色彩浓度": [saturation_sentence, analysis["saturation"]["description"]],
        "白平衡&色相": [f"白平衡：{white_balance}。", hue_sentence],
        "影调色卡": analysis["tonal_palette"],
        "肤色锚点": skin_lines,
        "素材特效&光线构成": {
            "素材特效": {
                "标签": effect_labels,
                "结论": "\n".join(effect_labels),
            },
            "光线构成": {
                "光源": light["source"],
                "光质": light["quality"],
                "光比": light["ratio"],
            },
        },
    }
    return report


def _skin_line(label: str, anchor: dict | None) -> str:
    if not anchor or anchor.get("status") != "有效":
        return f"{label}：样本不足，隐藏数值。"
    lab = anchor["lab"]
    return (
        f"{label}：{anchor['hex']}｜RGB {', '.join(map(str, anchor['rgb']))}｜"
        f"L* {lab['l']:.1f}｜a* {lab['a']:.1f}｜b* {lab['b']:.1f}"
    )
