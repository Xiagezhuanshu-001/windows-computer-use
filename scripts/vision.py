# -*- coding: utf-8 -*-
"""
视觉能力模块（屏幕找图 / 找色 / 找文字）
==========================================
人类看屏幕是为了"找到目标再动手"。本模块提供同样的能力：

  找图   find_image / find_all_images / wait_for_image
         —— 模板匹配，从截图里定位图标/按钮（不依赖无障碍树）
  找色   find_color / find_all_colors
         —— 按颜色定位纯色控件
  找文字 find_text / read_text
         —— OCR（需要 rapidocr-onnxruntime，未装时优雅降级）

依赖：
    必需：pillow、numpy
    可选：rapidocr-onnxruntime（OCR 功能）

作者：虾哥（DSH）  建于 2026-10-03
"""

import sys
import os
# ══════════════════════════════════════════════════════════
# DPI 感知（2026-10-04 实测发现的真实问题）
# ══════════════════════════════════════════════════════════
#
# 现象：在 175% 缩放的 4K 屏上，
#   Win32 API（GetWindowRect）返回**逻辑坐标** —— 2194x1234 体系
#   PIL 截图（ImageGrab）抓的是**物理像素** —— 3840x2160 体系
#   两者差 1.75 倍。拿截图量出来的坐标去点，必然点错位置。
#
# 修法：让进程声明 PER_MONITOR_AWARE_V2。
#   声明后 Win32 API 返回物理像素坐标，与截图统一，不再需要手工换算。
#   必须在进程早期调用（晚了无效），所以放在模块 import 时。
#
# 注意：如果宿主进程另有打算，可用环境变量 GUI_AGENT_NO_DPI_FIX=1 关掉。

_DPI_STATE = {"applied": False, "scale": 1.0, "physical": None, "logical": None}


def _init_dpi_awareness():
    import os as _os
    if _os.environ.get("GUI_AGENT_NO_DPI_FIX"):
        _DPI_STATE["applied"] = False
        return
    try:
        import ctypes as _ct
        u = _ct.windll.user32
        # PER_MONITOR_AWARE_V2 = -4；失败再退 DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE = -3
        ok = False
        for ctx in (-4, -3):
            try:
                if u.SetProcessDpiAwarenessContext(_ct.c_void_p(ctx)):
                    ok = True
                    break
            except Exception:
                continue
        if not ok:
            try:
                _ct.windll.shcore.SetProcessDpiAwareness(2)   # PER_MONITOR_DPI_AWARE
                ok = True
            except Exception:
                pass
        _DPI_STATE["applied"] = bool(ok)
    except Exception:
        _DPI_STATE["applied"] = False


def dpi_scale():
    """
    当前 DPI 缩放比（物理 / 逻辑）。

    · 如果 DPI 感知声明成功 -> 返回 1.0（Win32 和截图已统一）
    · 如果声明失败          -> 返回实际比值（调用方需自己换算）
    """
    try:
        import ctypes as _ct
        u = _ct.windll.user32
        hdc = u.GetDC(0)
        g = _ct.windll.gdi32
        phys = g.GetDeviceCaps(hdc, 118)      # DESKTOPHORZRES
        logi = g.GetDeviceCaps(hdc, 8)        # HORZRES
        u.ReleaseDC(0, hdc)
        _DPI_STATE["physical"] = phys
        _DPI_STATE["logical"] = logi
        if logi and logi > 0:
            s = phys / float(logi)
            _DPI_STATE["scale"] = s
            return s
    except Exception:
        pass
    return 1.0


def dpi_info():
    """返回诊断信息（doctor / 排查用）"""
    s = dpi_scale()
    return {
        "awareness_applied": _DPI_STATE["applied"],
        "scale": s,
        "physical": _DPI_STATE.get("physical"),
        "logical": _DPI_STATE.get("logical"),
        "note": ("已声明 DPI 感知，Win32 与截图坐标统一"
                 if _DPI_STATE["applied"] else
                 "未声明 DPI 感知，坐标可能需要按 scale 换算"),
    }


def to_logical(x, y):
    """把截图（物理像素）坐标换算成 Win32 逻辑坐标"""
    s = dpi_scale()
    if s == 1.0:
        return int(x), int(y)
    return int(round(x / s)), int(round(y / s))


def to_physical(x, y):
    """把 Win32 逻辑坐标换算成截图（物理像素）坐标"""
    s = dpi_scale()
    if s == 1.0:
        return int(x), int(y)
    return int(round(x * s)), int(round(y * s))


_init_dpi_awareness()


import time
from typing import Optional, Tuple, List

try:
    from PIL import ImageGrab, Image
except ImportError:
    raise ImportError("需要 pillow")

try:
    import numpy as np
except ImportError:
    raise ImportError("需要 numpy")


# ══════════════════════════════════════════════════════════
# 截图
# ══════════════════════════════════════════════════════════
def grab(region: Optional[Tuple[int, int, int, int]] = None) -> Image.Image:
    """
    截屏。
    region = (left, top, right, bottom)，None 表示全屏。
    """
    if region:
        return ImageGrab.grab(bbox=region)
    return ImageGrab.grab()


def _to_gray_array(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("L"), dtype=np.float32)


# ══════════════════════════════════════════════════════════
# ① 找图（模板匹配，归一化互相关）
# ══════════════════════════════════════════════════════════
def _ncc_score(patch: np.ndarray, region: np.ndarray) -> float:
    """归一化互相关，返回 0-1，越大越像（对亮度变化不敏感）"""
    p = patch - patch.mean()
    r = region - region.mean()
    denom = (np.sqrt((p ** 2).sum()) * np.sqrt((r ** 2).sum()))
    if denom == 0:
        return 0.0
    return float((p * r).sum() / denom)


def _downsample(arr: np.ndarray, factor: int) -> np.ndarray:
    """整数倍降采样（取块均值，比跳跃采样更稳）"""
    if factor <= 1:
        return arr
    h, w = arr.shape
    h2, w2 = h // factor * factor, w // factor * factor
    trimmed = arr[:h2, :w2]
    return trimmed.reshape(h2 // factor, factor, w2 // factor, factor).mean(axis=(1, 3))


def _ncc_map(shot: np.ndarray, tpl: np.ndarray, step: int = 1) -> np.ndarray:
    """
    计算模板在搜索图上每个位置的 NCC 分数图（向量化）。
    只支持 step 滑动（step=1 时逐像素，step>1 时隔点）。
    返回形状 (可行y数, 可行x数) 的分数矩阵。
    """
    th, tw = tpl.shape
    sh, sw = shot.shape
    if th > sh or tw > sw:
        return np.zeros((0, 0), dtype=np.float32)

    t = tpl.ravel().astype(np.float32)
    t_c = t - t.mean()
    t_norm = float(np.sqrt((t_c ** 2).sum()))
    if t_norm == 0:
        return np.zeros(((sh - th) // step + 1, (sw - tw) // step + 1), dtype=np.float32)

    ys = range(0, sh - th + 1, step)
    xs = range(0, sw - tw + 1, step)
    out = np.zeros((len(range(0, sh - th + 1, step)), len(range(0, sw - tw + 1, step))), dtype=np.float32)

    # 分块处理，避免一次性构造巨量窗口数据（1920x1080 会吃掉几 GB）
    BAND = 32
    band_idx = 0
    for y0 in range(0, len(ys), BAND):
        y_list = list(ys)[y0:y0 + BAND]
        y_end = min(y_list[-1] + th, sh)
        band = shot[y_list[0]:y_end]
        # 该带内所有窗口
        bw = np.lib.stride_tricks.sliding_window_view(band, (th, tw))
        bw = bw[::step, ::step]
        flat = bw.reshape(-1, th * tw).astype(np.float32)
        flat -= flat.mean(axis=1, keepdims=True)
        norms = np.sqrt((flat ** 2).sum(axis=1))
        num = flat @ t_c
        with np.errstate(divide="ignore", invalid="ignore"):
            scores = np.where(norms > 0, num / (norms * t_norm), 0.0)
        rows = min(BAND, len(ys) - y0)
        out[band_idx:band_idx + rows, :scores.size // rows] = scores.reshape(rows, -1)
        band_idx += rows
    return out


def find_image(template_path: str,
               screenshot: Optional[Image.Image] = None,
               region: Optional[Tuple[int, int, int, int]] = None,
               threshold: float = 0.85,
               step: int = 2,
               pyramid: bool = True) -> Optional[Tuple[int, int, float]]:
    """
    在屏幕（或指定区域）里找模板图。

    两级搜索（pyramid=True 时）：
      ① 把图和模板降采样 4 倍，快速扫出候选位置
      ② 回到原图，只在候选附近精修

    相比全像素暴力扫描，实测 1920x1080 从 44 秒降到 1 秒以内。

    返回 (屏幕X, 屏幕Y, 相似度)，坐标是匹配框中心。找不到返回 None。
    """
    tpl_img = Image.open(template_path)
    tpl = _to_gray_array(tpl_img)
    th, tw = tpl.shape

    shot = screenshot if screenshot is not None else grab(region)
    shot_arr = _to_gray_array(shot)
    sh, sw = shot_arr.shape

    if th > sh or tw > sw:
        return None

    ox = region[0] if region else 0
    oy = region[1] if region else 0
    # ── ① 粗搜：降采样 4 倍 ──
    if pyramid and th >= 12 and tw >= 12 and sh >= th * 2 and sw >= tw * 2:
        F = 4
        shot_s = _downsample(shot_arr, F)
        tpl_s = _downsample(tpl, F)
        if tpl_s.shape[0] >= 4 and tpl_s.shape[1] >= 4:
            score_map = _ncc_map(shot_s, tpl_s, step=1)
            if score_map.size:
                # 取若干高分候选（粗搜阈值放宽，避免漏掉）
                flat = score_map.ravel()
                k = min(6, flat.size)
                top_idx = np.argpartition(flat, -k)[-k:]
                cands = []
                for idx in top_idx:
                    if flat[idx] < threshold - 0.15:
                        continue
                    cy, cx = divmod(int(idx), score_map.shape[1])
                    cands.append((cx * F, cy * F))
                # ── ② 精修：候选附近原图逐像素 ──
                best = (-1.0, 0, 0)
                pad = F * 2
                for cx, cy in cands:
                    x0 = max(0, cx - pad)
                    y0 = max(0, cy - pad)
                    x1 = min(sw - tw, cx + pad)
                    y1 = min(sh - th, cy + pad)
                    if x1 < x0 or y1 < y0:
                        continue
                    sub = shot_arr[y0:y1 + th, x0:x1 + tw]
                    m = _ncc_map(sub, tpl, step=1)
                    if m.size == 0:
                        continue
                    idx = int(np.argmax(m))
                    sy, sx = divmod(idx, m.shape[1])
                    sc = float(m[sy, sx])
                    if sc > best[0]:
                        best = (sc, x0 + sx, y0 + sy)
                if best[0] >= threshold:
                    bx, by = best[1], best[2]
                    return (int(ox + bx + tw // 2), int(oy + by + th // 2), round(best[0], 4))
                # 金字塔已覆盖全图，最高分仍不达标 → 判定为"没找到"。
                # 不回退暴力全扫描 —— 那会让"找不到"的场景从 0.2 秒变成 10 秒。
                return None

    # ── 模板过小（<12px）时降采样会丢失特征，改用网格扫描 ──
    best = (-1.0, 0, 0)
    for y in range(0, sh - th + 1, step):
        for x in range(0, sw - tw + 1, step):
            sc = _ncc_score(tpl, shot_arr[y:y + th, x:x + tw])
            if sc > best[0]:
                best = (sc, x, y)
    if best[0] < threshold:
        return None
    return (int(ox + best[1] + tw // 2), int(oy + best[2] + th // 2), round(best[0], 4))


def find_all_images(template_path: str,
                    screenshot: Optional[Image.Image] = None,
                    region: Optional[Tuple[int, int, int, int]] = None,
                    threshold: float = 0.85,
                    step: int = 2,
                    max_results: int = 20) -> List[Tuple[int, int, float]]:
    """找出所有匹配位置（去重：相邻 20 像素内只保留最高分）"""
    tpl_img = Image.open(template_path)
    tpl = _to_gray_array(tpl_img)
    th, tw = tpl.shape

    shot = screenshot if screenshot is not None else grab(region)
    shot_arr = _to_gray_array(shot)
    sh, sw = shot_arr.shape
    if th > sh or tw > sw:
        return []

    origin_x = region[0] if region else 0
    origin_y = region[1] if region else 0

    hits = []
    for y in range(0, sh - th + 1, step):
        for x in range(0, sw - tw + 1, step):
            score = _ncc_score(tpl, shot_arr[y:y + th, x:x + tw])
            if score >= threshold:
                hits.append((score, x, y))

    hits.sort(reverse=True)
    picked = []
    for score, x, y in hits:
        if len(picked) >= max_results:
            break
        if any(abs(x - px) < 20 and abs(y - py) < 20 for _, px, py in picked):
            continue
        picked.append((score, x, y))

    return [(origin_x + x + tw // 2, origin_y + y + th // 2, round(s, 4)) for s, x, y in picked]


def wait_for_image(template_path: str,
                   timeout: float = 10.0,
                   interval: float = 0.5,
                   threshold: float = 0.85,
                   region: Optional[Tuple[int, int, int, int]] = None) -> Optional[Tuple[int, int, float]]:
    """等某个图标出现（人类等界面加载时的行为）。超时返回 None。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        hit = find_image(template_path, region=region, threshold=threshold)
        if hit:
            return hit
        time.sleep(interval)
    return None


def wait_for_image_gone(template_path: str, timeout: float = 10.0,
                        interval: float = 0.5, threshold: float = 0.85) -> bool:
    """等某个图标消失（人类等加载完成的行为）"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not find_image(template_path, threshold=threshold):
            return True
        time.sleep(interval)
    return False


# ══════════════════════════════════════════════════════════
# ② 找色（纯色控件、进度条、状态灯）
# ══════════════════════════════════════════════════════════
def find_color(rgb: Tuple[int, int, int],
               screenshot: Optional[Image.Image] = None,
               region: Optional[Tuple[int, int, int, int]] = None,
               tolerance: int = 12) -> Optional[Tuple[int, int]]:
    """
    找到屏幕上第一个接近该颜色的像素。
    rgb = (R, G, B)，tolerance 是每通道允许的误差。
    """
    shot = screenshot if screenshot is not None else grab(region)
    arr = np.asarray(shot.convert("RGB"), dtype=np.int16)
    target = np.array(rgb, dtype=np.int16)
    diff = np.abs(arr - target).max(axis=2)
    mask = diff <= tolerance
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    ox = region[0] if region else 0
    oy = region[1] if region else 0
    return int(ox + xs[0]), int(oy + ys[0])


def find_all_colors(rgb: Tuple[int, int, int],
                    screenshot: Optional[Image.Image] = None,
                    region: Optional[Tuple[int, int, int, int]] = None,
                    tolerance: int = 12,
                    cluster_gap: int = 15,
                    max_results: int = 30) -> List[Tuple[int, int]]:
    """找到所有该颜色的位置，按簇聚合（相邻的算一个）"""
    shot = screenshot if screenshot is not None else grab(region)
    arr = np.asarray(shot.convert("RGB"), dtype=np.int16)
    target = np.array(rgb, dtype=np.int16)
    mask = np.abs(arr - target).max(axis=2) <= tolerance
    ys, xs = np.nonzero(mask)
    ox = region[0] if region else 0
    oy = region[1] if region else 0

    picked = []
    for x, y in zip(xs, ys):
        if len(picked) >= max_results:
            break
        if any(abs(x - px) < cluster_gap and abs(y - py) < cluster_gap for px, py in picked):
            continue
        picked.append((int(x), int(y)))
    return [(ox + x, oy + y) for x, y in picked]


# ══════════════════════════════════════════════════════════
# ③ OCR（可选依赖）
# ══════════════════════════════════════════════════════════
_OCR_ENGINE = None
_OCR_TRIED = False


def ocr_available() -> bool:
    """OCR 是否可用"""
    global _OCR_ENGINE, _OCR_TRIED
    if _OCR_TRIED:
        return _OCR_ENGINE is not None
    _OCR_TRIED = True
    try:
        from rapidocr_onnxruntime import RapidOCR
        _OCR_ENGINE = RapidOCR()
    except Exception:
        _OCR_ENGINE = None
    return _OCR_ENGINE is not None


def read_text(region: Optional[Tuple[int, int, int, int]] = None) -> List[dict]:
    """
    读取屏幕上的文字。
    返回 [{"text":..., "x":..., "y":..., "conf":...}, ...]，坐标是文字框中心。
    OCR 不可用时抛 RuntimeError（不静默失败）。
    """
    if not ocr_available():
        raise RuntimeError(
            "OCR 不可用。安装：pip install rapidocr-onnxruntime\n"
            "（纯 CPU 推理，无需 GPU；首次运行会下载模型）"
        )
    shot = grab(region)
    arr = np.asarray(shot.convert("RGB"))
    result, _ = _OCR_ENGINE(arr)
    out = []
    if result:
        ox = region[0] if region else 0
        oy = region[1] if region else 0
        for box, text, conf in result:
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            cx = int(ox + (min(xs) + max(xs)) / 2)
            cy = int(oy + (min(ys) + max(ys)) / 2)
            out.append({"text": text, "x": cx, "y": cy, "conf": float(conf)})
    return out


def find_text(target: str,
              region: Optional[Tuple[int, int, int, int]] = None,
              exact: bool = False) -> Optional[Tuple[int, int, str]]:
    """
    在屏幕上找一段文字，返回 (x, y, 匹配到的原文)。
    exact=False 时做包含匹配（人类找按钮不会一个字符都不差）。
    """
    for item in read_text(region):
        t = item["text"]
        if (t == target) if exact else (target in t):
            return item["x"], item["y"], t
    return None


def click_text(target: str,
               region: Optional[Tuple[int, int, int, int]] = None,
               exact: bool = False,
               human_click: bool = True) -> bool:
    """
    找到文字并点击 —— 这是最接近人类的"看到按钮就按"的动作。
    需要 mouse 模块做实际点击。
    """
    hit = find_text(target, region, exact)
    if not hit:
        return False
    x, y, _ = hit
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import mouse
    if human_click:
        mouse.click(x, y)
    else:
        import win32api
        win32api.SetCursorPos((x, y))
        import win32con
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.07)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    return True


# ══════════════════════════════════════════════════════════
# 自查
# ══════════════════════════════════════════════════════════
def doctor():
    caps = [
        ("grab", "截屏（全屏或指定区域）"),
        ("find_image", "找图（模板匹配，归一化互相关 + 粗扫精修）"),
        ("find_all_images", "找出所有匹配位置（去重）"),
        ("wait_for_image", "等图标出现"),
        ("wait_for_image_gone", "等图标消失"),
        ("find_color", "按颜色找像素"),
        ("find_all_colors", "找出所有该颜色的位置（聚类）"),
        ("read_text", "OCR 读取屏幕文字"),
        ("find_text", "找文字（支持包含匹配）"),
        ("click_text", "找到文字并点击"),
    ]
    for name, desc in caps:
        print(f"  [OK] {name:<22} {desc}")
    print()
    print(f"  numpy 版本 : {np.__version__}")
    print(f"  OCR 可用   : {ocr_available()}")
    try:
        shot = grab()
        print(f"  截屏测试   : {shot.size[0]}x{shot.size[1]}")
    except Exception as e:
        print(f"  截屏测试   : 失败 - {e}")
    return len(caps)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if len(sys.argv) > 1 and sys.argv[1] == "doctor":
        n = doctor()
        print(f"\n  视觉能力共 {n} 项")
    else:
        print(__doc__)
