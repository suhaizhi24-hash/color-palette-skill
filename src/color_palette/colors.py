from __future__ import annotations

import colorsys
import numpy as np
from sklearn.cluster import MiniBatchKMeans
from skimage.color import rgb2lab


def hue_name(rgb: list[int] | tuple[int, int, int]) -> str:
    r, g, b = [value / 255.0 for value in rgb]
    if max(r, g, b) - min(r, g, b) < 0.06:
        return "中性灰"
    hue, _, _ = colorsys.rgb_to_hsv(r, g, b)
    degree = hue * 360
    if degree < 20 or degree >= 345:
        return "红"
    if degree < 50:
        return "橙黄"
    if degree < 75:
        return "黄绿"
    if degree < 165:
        return "绿青"
    if degree < 205:
        return "青蓝"
    if degree < 260:
        return "蓝"
    if degree < 310:
        return "紫"
    return "洋红"


def dominant_tonal_palette(rgb01: np.ndarray, lab: np.ndarray, valid_mask: np.ndarray) -> list[dict]:
    flat_rgb = rgb01.reshape(-1, 3)
    flat_lab = lab.reshape(-1, 3)
    flat_l = flat_lab[:, 0]
    valid = valid_mask.reshape(-1)
    edges = [0, 20, 40, 60, 80, 100]
    roles = ["深黑", "阴影", "中间调", "亮部", "高光"]
    result: list[dict] = []

    for index, role in enumerate(roles):
        band = valid & (flat_l >= edges[index])
        if index < 4:
            band &= flat_l < edges[index + 1]
        else:
            band &= flat_l <= 100
        ids = np.flatnonzero(band)
        share = float(ids.size / max(int(valid.sum()), 1))

        if ids.size < 20:
            result.append({
                "role": role,
                "status": "样本不足",
                "rgb": [245, 245, 245],
                "hex": "#F5F5F5",
                "lab": {"l": 96.5, "a": 0.0, "b": 0.0},
                "band_share": round(share, 6),
            })
            continue

        rng = np.random.default_rng(20260812 + index)
        sample_ids = ids if ids.size <= 30000 else rng.choice(ids, 30000, replace=False)
        samples = flat_lab[sample_ids]
        clusters = min(4, max(1, sample_ids.size // 5000))
        model = MiniBatchKMeans(
            n_clusters=clusters,
            random_state=42,
            n_init=5,
            batch_size=2048,
        )
        labels = model.fit_predict(samples)
        winner = int(np.argmax(np.bincount(labels, minlength=clusters)))
        chosen_ids = sample_ids[labels == winner]
        median_rgb01 = np.median(flat_rgb[chosen_ids], axis=0)
        rgb = np.rint(median_rgb01 * 255).astype(int).tolist()
        lab_value = rgb2lab(median_rgb01.reshape(1, 1, 3))[0, 0]

        result.append({
            "role": role,
            "status": "有效",
            "rgb": rgb,
            "hex": "#" + "".join(f"{value:02X}" for value in rgb),
            "lab": {
                "l": round(float(lab_value[0]), 2),
                "a": round(float(lab_value[1]), 2),
                "b": round(float(lab_value[2]), 2),
            },
            "band_share": round(share, 6),
        })

    return result
