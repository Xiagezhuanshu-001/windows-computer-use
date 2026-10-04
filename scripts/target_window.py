# -*- coding: utf-8 -*-
"""
独立进程测试靶子（增强版）
============================
为什么需要它：
  在同一个 Python 进程里反复创建 / 销毁 tkinter 窗口来当靶子，本身就不稳定
  （2026-10-04 实测：第 3 个窗口起前台就会丢；单一窗口重复输入也会静默失败）。
  更关键的是 —— 真实使用场景本来就是"操作另一个进程的窗口"，
  同进程内建窗口根本测不到真实情况。

  所以靶子必须是**独立进程**。

增强版新增（为了让测试能做"效果回读"，而不是"没抛异常就算过"）：
  · 真滑块        slider     可被拖动，位置会被记录
  · 横向滚动区    hscroll    验证横向滚轮真的生效
  · 可缩放区      zoom       验证 Ctrl+滚轮真的生效
  · 可拖拽对象    draggable  记录对象实际坐标，验证拖放是否送达
  · 菜单计数      menu_count 验证右键菜单真的弹出过
  · 拖拽接收区    dropzone   验证拖放落点是否在区内
  · 多击计数      dbl/triple 验证双击、三击真的被识别
  · 键盘事件日志  key_log    记录收到的按键，验证 F 键 / Esc / Tab 等

用法：
  python target_window.py <状态文件路径>

  所有状态每 250ms 落盘一次，主测试进程读文件即可知道"操作到底有没有生效"。
"""

import sys
import os
import json
# ── DPI 感知声明（必须放在最前）──
# 2026-10-04：技能侧已声明 PER_MONITOR_AWARE_V2，
# 靶子若还是 DPI-UNAWARE，两边坐标系差 1.75 倍，测试会全点空。
# 真实应用大多声明了 DPI 感知，靶子也要跟上才贴近现实。
try:
    import ctypes as _ct
    for _ctx in (-4, -3):
        try:
            if _ct.windll.user32.SetProcessDpiAwarenessContext(_ct.c_void_p(_ctx)):
                break
        except Exception:
            continue
except Exception:
    pass

import tkinter as tk


def main():
    state_file = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.environ.get("TEMP", "."), "gui_agent_target_state.json")

    root = tk.Tk()
    root.title("gui-agent-test-target")
    root.geometry("640x720+180+80")

    st = {
        "clicks": 0,
        "dbl_clicks": 0,
        "triple_clicks": 0,
        "right_clicks": 0,
        "middle_clicks": 0,
        "menu_count": 0,
        "key_log": [],
        "drag_count": 0,
        "drop_count": 0,
    }

    # ── 文本框 ──
    tk.Label(root, text="text").pack(anchor="w", padx=8)
    text = tk.Text(root, height=3, width=74)
    text.pack(padx=8)

    # ── 列表（多选 + 垂直滚动） ──
    tk.Label(root, text="list").pack(anchor="w", padx=8)
    listbox = tk.Listbox(root, height=4, selectmode=tk.EXTENDED)
    for i in range(80):
        listbox.insert(tk.END, "item_%02d" % i)
    listbox.pack(padx=8, fill=tk.X)

    # ── 真滑块（可拖动，记录位置） ──
    tk.Label(root, text="slider").pack(anchor="w", padx=8)
    slider_var = tk.DoubleVar(value=0.0)
    slider = tk.Scale(root, from_=0, to=100, orient=tk.HORIZONTAL,
                      length=500, variable=slider_var)
    slider.pack(padx=8, anchor="w")

    # ── 横向滚动区 ──
    tk.Label(root, text="hscroll").pack(anchor="w", padx=8)
    hframe = tk.Frame(root)
    hframe.pack(padx=8, fill=tk.X)
    hcanvas = tk.Canvas(hframe, height=40, bg="#eef2f7")
    hbar = tk.Scrollbar(hframe, orient=tk.HORIZONTAL, command=hcanvas.xview)
    hcanvas.configure(xscrollcommand=hbar.set, scrollregion=(0, 0, 3000, 40))
    hcanvas.create_text(20, 20, text="horizontal scroll area " * 12, anchor="w")
    hcanvas.pack(fill=tk.X)
    hbar.pack(fill=tk.X)

    # tkinter 默认不响应原生横向滚轮（MOUSEEVENTF_HWHEEL），
    # 需要显式绑定 <Shift-MouseWheel> 和 <Alt-MouseWheel> 才会滚动
    def _hscroll(event):
        hcanvas.xview_scroll(-1 if event.delta > 0 else 1, "units")

    hcanvas.bind("<Shift-MouseWheel>", _hscroll)
    hcanvas.bind("<Alt-MouseWheel>", _hscroll)
    hcanvas.bind("<Button-4>", lambda e: hcanvas.xview_scroll(-1, "units"))
    hcanvas.bind("<Button-5>", lambda e: hcanvas.xview_scroll(1, "units"))

    # ── 可缩放区（Ctrl+滚轮） ──
    tk.Label(root, text="zoom").pack(anchor="w", padx=8)
    zcanvas = tk.Canvas(root, height=60, bg="#f7f0ee")
    zcanvas.pack(padx=8, fill=tk.X)
    z_item = zcanvas.create_rectangle(20, 10, 120, 50, fill="#d98b6a", outline="")
    zoom_state = {"factor": 1.0}

    def on_zoom(event):
        zoom_state["factor"] = max(0.3, min(3.0,
                                           zoom_state["factor"] * (1.1 if event.delta > 0 else 0.9)))
        w = max(10, int(100 * zoom_state["factor"]))
        zcanvas.coords(z_item, 20, 10, 20 + w, 50)

    zcanvas.bind("<Control-MouseWheel>", on_zoom)

    # ── 可拖拽对象 + 接收区 ──
    tk.Label(root, text="drag / drop").pack(anchor="w", padx=8)
    dcanvas = tk.Canvas(root, height=80, bg="#eef7ee")
    dcanvas.pack(padx=8, fill=tk.X)
    drag_item = dcanvas.create_rectangle(30, 20, 110, 60, fill="#6aa84f", outline="")
    drop_box = dcanvas.create_rectangle(420, 15, 590, 65, outline="#333", width=2)
    drag_state = {"sx": 0, "sy": 0, "x": 30, "y": 20}

    def start_drag(e):
        drag_state["sx"], drag_state["sy"] = e.x, e.y

    def do_drag(e):
        dx = e.x - drag_state["sx"]
        dy = e.y - drag_state["sy"]
        dcanvas.move(drag_item, dx, dy)
        drag_state["sx"], drag_state["sy"] = e.x, e.y
        st["drag_count"] += 1
        c = dcanvas.coords(drag_item)
        drag_state["x"], drag_state["y"] = c[0], c[1]

    def end_drag(e):
        c = dcanvas.coords(drag_item)
        drag_state["x"], drag_state["y"] = c[0], c[1]
        if c[0] > 400 and c[2] < 600:
            st["drop_count"] += 1

    dcanvas.tag_bind(drag_item, "<Button-1>", start_drag)
    dcanvas.tag_bind(drag_item, "<B1-Motion>", do_drag)
    dcanvas.tag_bind(drag_item, "<ButtonRelease-1>", end_drag)

    # ── 按钮区 ──
    btnrow = tk.Frame(root)
    btnrow.pack(pady=6)

    click_label = tk.Label(btnrow, text="clicks: 0")
    dbl_label = tk.Label(btnrow, text="dbl: 0")
    triple_label = tk.Label(btnrow, text="tri: 0")
    right_label = tk.Label(btnrow, text="right: 0")
    mid_label = tk.Label(btnrow, text="mid: 0")

    def on_click():
        st["clicks"] += 1
        click_label.config(text="clicks: %d" % st["clicks"])

    def on_dbl(_e=None):
        st["dbl_clicks"] += 1
        dbl_label.config(text="dbl: %d" % st["dbl_clicks"])

    def on_triple(_e=None):
        st["triple_clicks"] += 1
        triple_label.config(text="tri: %d" % st["triple_clicks"])

    def on_right(e):
        st["right_clicks"] += 1
        st["menu_count"] += 1
        right_label.config(text="right: %d" % st["right_clicks"])
        m = tk.Menu(root, tearoff=0)
        m.add_command(label="menu_item_1")
        m.add_command(label="menu_item_2")
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    def on_middle(_e=None):
        st["middle_clicks"] += 1
        mid_label.config(text="mid: %d" % st["middle_clicks"])

    b1 = tk.Button(btnrow, text="click me", command=on_click)
    b1.pack(side=tk.LEFT, padx=4)
    b1.bind("<Double-Button-1>", on_dbl)
    b1.bind("<Triple-Button-1>", on_triple)
    b1.bind("<Button-3>", on_right)
    b1.bind("<Button-2>", on_middle)

    for lbl in (click_label, dbl_label, triple_label, right_label, mid_label):
        lbl.pack(side=tk.LEFT, padx=6)

    # ── 键盘事件日志 ──
    def log_key(e):
        if len(st["key_log"]) < 300:
            st["key_log"].append({"keysym": e.keysym, "keycode": e.keycode,
                                  "state": e.state, "char": e.char})

    root.bind_all("<KeyPress>", log_key)

    # ── 定时落盘 ──
    def dump():
        try:
            # 各控件的精确屏幕坐标（相对窗口左上角）——
            # 测试直接读这里，不再靠猜坐标
            def geo(w):
                # 直接报「屏幕绝对坐标」——
                # 不要去减 root.winfo_rootx()：那是客户区原点，
                # 而主测试用的是窗口矩形（含标题栏与边框），两者差一个边框偏移，
                # 2026-10-04 实测就是这个偏移让 20+ 项坐标全部算偏。
                try:
                    rx, ry = w.winfo_rootx(), w.winfo_rooty()
                    ww, wh = w.winfo_width(), w.winfo_height()
                    return {"x": rx, "y": ry, "w": ww, "h": wh,
                            "cx": rx + ww // 2, "cy": ry + wh // 2}
                except Exception:
                    return {"x": 0, "y": 0, "w": 0, "h": 0, "cx": 0, "cy": 0}

            def cgeo(c, item):
                # 注意：Canvas.bbox() 返回的是 (x1, y1, x2, y2) 左上+右下，
                # 不是 (x, y, w, h)。2026-10-04 实测把这个搞错，
                # 导致 drop_box 中心被算到 (910,584) —— 跑到窗口外去了。
                try:
                    c.update_idletasks()
                    bb = c.bbox(item)
                    if not bb:
                        return {"x": 0, "y": 0, "w": 0, "h": 0, "cx": 0, "cy": 0}
                    x1, y1, x2, y2 = bb
                    bw, bh = x2 - x1, y2 - y1
                    ox, oy = c.winfo_rootx(), c.winfo_rooty()   # 绝对坐标
                    return {"x": ox + x1, "y": oy + y1, "w": bw, "h": bh,
                            "cx": ox + x1 + bw // 2, "cy": oy + y1 + bh // 2}
                except Exception:
                    return {"x": 0, "y": 0, "w": 0, "h": 0, "cx": 0, "cy": 0}

            data = {
                "geo": {
                    "text": geo(text),
                    "listbox": geo(listbox),
                    "slider": geo(slider),
                    "hcanvas": geo(hcanvas),
                    "zcanvas": geo(zcanvas),
                    "dcanvas": geo(dcanvas),
                    "btn": geo(b1),
                },
                "item_geo": {
                    "drag_item": cgeo(dcanvas, drag_item),
                    "drop_box": cgeo(dcanvas, drop_box),
                },
                "text": text.get("1.0", "end-1c"),
                "clicks": st["clicks"],
                "dbl_clicks": st["dbl_clicks"],
                "triple_clicks": st["triple_clicks"],
                "right_clicks": st["right_clicks"],
                "middle_clicks": st["middle_clicks"],
                "menu_count": st["menu_count"],
                "key_log_len": len(st["key_log"]),
                "key_log_tail": st["key_log"][-64:],   # 12 个功能键会产生 24 条事件，24 条窗口刚好装满会把前面的挤掉
                "list_selection": list(listbox.curselection()),
                "list_yview": list(listbox.yview()),
                "slider_value": float(slider_var.get()),
                # Scale.coords(value) 返回滑块柄的 (x1, y1, x2, y2)，
                # 这是拖动滑块时必须点到的位置——之前靠猜偏移量一直没点到
                "slider_handle": (list(slider.coords(slider_var.get()))
                                  if slider.coords(slider_var.get()) else None),
                "hscroll_xview": list(hcanvas.xview()),
                "zoom_factor": round(zoom_state["factor"], 3),
                "drag_count": st["drag_count"],
                "drop_count": st["drop_count"],
                "drag_x": round(drag_state.get("x", 0), 1),
                "drag_y": round(drag_state.get("y", 0), 1),
                "focus_widget": (root.focus_get().winfo_class() if root.focus_get() else None),
                "focus_name": (str(root.focus_get()) if root.focus_get() else None),
                "hwnd": root.winfo_id(),
                "alive": True,
            }
            tmp = state_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, state_file)
        except Exception:
            pass
        root.after(250, dump)

    root.after(250, dump)

    def check_quit():
        if os.path.exists(state_file + ".quit"):
            try:
                root.destroy()
            except Exception:
                pass
            return
        root.after(300, check_quit)

    root.after(300, check_quit)

    try:
        root.mainloop()
    except Exception:
        pass


if __name__ == "__main__":
    main()
