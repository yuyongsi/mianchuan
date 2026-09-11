#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🌊 面川 —— 自我激励桌面小工具
================================

核心规则：
  1. 每天凌晨 4:00 刷新，开启新的一天
  2. 早上到设定时间，程序自动 +早起分
  3. 晚上到设定时间，程序自动 -晚间分
  4. 事件按钮：点一下记一笔（正数 = 注水，负数 = 放水）
  5. 日历格子的右上角显示"晚间扣减前"的当日分数

数据保存在同目录下的 data.json（可随时手动改）
依赖：pip install pyside6
"""

import json
import os
import sys
from datetime import datetime, timedelta

from PySide6.QtCore import QDate, QTime, Qt, QTimer, QRect, QPoint
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap, QIcon, QPalette, QTextCharFormat, QBrush
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QCalendarWidget, QListWidget, QListWidgetItem, QLineEdit, QSpinBox,
    QDialog, QDialogButtonBox, QFormLayout, QTimeEdit, QMessageBox, QComboBox, QTextEdit,
    QFileDialog, QColorDialog, QSlider,
)

# ---------------------------------------------------------------------------
# 常量与默认值
# ---------------------------------------------------------------------------
def get_data_dir():
    """数据存储目录：打包后放 %APPDATA%/面川；开发时放脚本目录。"""
    if getattr(sys, "frozen", False):
        d = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "面川")
        os.makedirs(d, exist_ok=True)
        return d
    return os.path.dirname(os.path.abspath(__file__))


def get_exe_dir():
    """exe 所在目录（打包后）或脚本目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def get_icon_path():
    """窗口图标：优先 exe 同目录的 icon.ico；否则用打包进 exe 的。"""
    p = os.path.join(get_exe_dir(), "icon.ico")
    if os.path.exists(p):
        return p
    if getattr(sys, "frozen", False):
        bundled = os.path.join(sys._MEIPASS, "icon.ico")
        if os.path.exists(bundled):
            return bundled
    return None


DATA_FILE = os.path.join(get_data_dir(), "data.json")

DEFAULT_CONFIG = {
    "morning_time": "07:00",   # 早起加分时间点
    "morning_value": 10,       # 早起加分数
    "night_time": "23:00",     # 晚间扣分时间点
    "night_value": -5,         # 晚间扣分数（填负数）
    "refresh_hour": 4,         # 每日刷新时刻（凌晨4点）
    "bg_image": "",            # 背景图片路径（空=无图）
    "bg_color": "#f5f7fa",     # 背景颜色
    "bg_overlay_alpha": 120,   # 背景图遮罩透明度(0-255)
    "note_placeholder": "今天有什么想说的？",   # 闲笔占位提示文字
    # 步数积分：达不到基础步数扣 a；达到后每多 c 步加 b
    "step_base": 8000,         # 基础步数（达到不加分，达不到扣分）
    "step_a": 5,               # 达不到基础步数扣 a 分
    "step_b": 2,               # 超过基础后每多 c 步加 b 分
    "step_c": 1000,            # 每多 c 步
}

DEFAULT_TAGS = [
    {"name": "背单词",  "value": 5},
    {"name": "学习",    "value": 10},
    {"name": "刷题",    "value": 15},
    {"name": "打游戏",  "value": -15},
    {"name": "追剧",    "value": -10},
    {"name": "刷短视频", "value": -5},
]

# ---------------------------------------------------------------------------
# 数据层：json 读写 + 日期计算
# ---------------------------------------------------------------------------
def load_data():
    """加载数据；文件不存在时用默认值初始化。"""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, encoding="utf-8") as f:
            data = json.load(f)
        cfg = data.setdefault("config", {})
        for k, v in DEFAULT_CONFIG.items():
            cfg.setdefault(k, v)
        data.setdefault("tags", [dict(t) for t in DEFAULT_TAGS])
        data.setdefault("days", {})
        data.setdefault("one_time", [])
        return data
    data = {
        "config": dict(DEFAULT_CONFIG),
        "tags": [dict(t) for t in DEFAULT_TAGS],
        "days": {},
        "one_time": [],
    }
    save_data(data)
    return data


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def date_key(dt=None):
    """按凌晨4点为日界，返回当天的日期字符串。0-4点算前一天。"""
    dt = dt or datetime.now()
    d = dt.date() - timedelta(days=1) if dt.hour < 4 else dt.date()
    return d.isoformat()


def ensure_today(data):
    """确保今天（按日界）的记录存在，返回 key。"""
    key = date_key()
    if key not in data["days"]:
        data["days"][key] = {"morning_done": False, "night_done": False,
                             "events": [], "timers": []}
    return key


def step_value(cfg, steps):
    """根据步数计算积分：达不到基础步数扣 a；达到后每多 c 步加 b。"""
    base = cfg.get("step_base", 8000)
    if steps < base:
        return -cfg.get("step_a", 5)
    b = cfg.get("step_b", 2)
    c = cfg.get("step_c", 1000) or 1
    return (steps - base) // c * b


def get_settle_target(cfg, now=None):
    """晚间结算的目标日期 key。

    结算时间在凌晨时段(<=4点)时，结算的是"刚结束的一天"（昨天），
    这样凌晨 4 点正好清算掉昨天白天的活，新一天从 4 点干净开始；
    结算时间在当天时段(>4点)时，结算当天。
    未到结算时间返回 None。
    """
    now = now or datetime.now()
    t = now.strftime("%H:%M")
    night_t = cfg.get("night_time", "23:00")
    if t < night_t:
        return None
    if night_t <= "04:00":
        return (now.date() - timedelta(days=1)).isoformat()
    return date_key(now)


def day_score(data, key):
    """返回某天的 (晚间扣减前分数, 晚间扣减后分数)。"""
    cfg = data["config"]
    d = data["days"].get(key, {"morning_done": False, "night_done": False,
                               "events": [], "timers": []})
    s = 0
    if d["morning_done"]:
        s += cfg["morning_value"]
    for e in d["events"]:
        s += e["value"]
    for tm in d.get("timers", []):
        s += tm.get("value", 0)
    st = d.get("steps")
    if st:
        s += st.get("value", 0)
    before = s
    if d["night_done"]:
        s = 0  # 晚间清零
    return before, s


# ---------------------------------------------------------------------------
# 带分数标注的日历（在格子右上角画当日分数）
# ---------------------------------------------------------------------------
class WaterCalendar(QCalendarWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scores = {}          # QDate -> 分数
        self.note_dates = set()   # 写过闲笔的日期
        self._note_formatted = set()  # 已应用闲笔格式的日期

    def set_scores(self, scores):
        self.scores = dict(scores)
        self.update()

    def set_note_dates(self, dates):
        self.note_dates = set(dates)
        # 先重置旧的闲笔格式
        for d in self._note_formatted:
            self.setDateTextFormat(d, QTextCharFormat())
        self._note_formatted = set()
        # 给写过闲笔的日期应用"淡蓝底 + 深蓝字"
        for d in dates:
            fmt = QTextCharFormat()
            fmt.setBackground(QBrush(QColor("#dbeafe")))
            fmt.setForeground(QBrush(QColor("#1d4ed8")))
            self.setDateTextFormat(d, fmt)
            self._note_formatted.add(d)
        self.update()

    def paintCell(self, painter, rect, date):
        super().paintCell(painter, rect, date)
        # 右上角：当日分数
        s = self.scores.get(date)
        if s is not None:
            painter.save()
            painter.setPen(QColor("#2e7d32") if s >= 0 else QColor("#c62828"))
            font = QFont(self.font())
            font.setPointSize(8)
            painter.setFont(font)
            painter.drawText(rect.adjusted(0, 1, -2, 0), Qt.AlignRight | Qt.AlignTop, f"{s:+d}")
            painter.restore()


# ---------------------------------------------------------------------------
# 新建一次性任务对话框
# ---------------------------------------------------------------------------
class AddOneTimeDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🎯 新建一次性任务")
        self.setMinimumWidth(280)
        form = QFormLayout(self)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("任务名，如 完成课设")
        self.value_spin = QSpinBox()
        self.value_spin.setRange(-999, 999)
        self.value_spin.setValue(10)
        form.addRow("任务名", self.name_edit)
        form.addRow("分值", self.value_spin)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        form.addRow(box)

    def get_data(self):
        return self.name_edit.text().strip(), self.value_spin.value()


# ---------------------------------------------------------------------------
# 带斜体淡色占位提示的多行文本框
# ---------------------------------------------------------------------------
class NoteEdit(QTextEdit):
    def __init__(self, placeholder_text="", parent=None):
        super().__init__(parent)
        self.ph_label = QLabel(placeholder_text, self)
        self.ph_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.ph_label.setStyleSheet(
            "color:#b0b0b0; font-style:italic; background:transparent;")
        self.textChanged.connect(self._update_placeholder)
        self._update_placeholder()

    def _update_placeholder(self):
        self.ph_label.setVisible(not self.toPlainText().strip())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.ph_label.setGeometry(10, 8, self.width() - 20, 20)


# ---------------------------------------------------------------------------
# 某一天积分明细查看窗口
# ---------------------------------------------------------------------------
class DayDetailDialog(QDialog):
    def __init__(self, data, key, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"📖 {key} 记录")
        self.setMinimumSize(360, 440)
        self.data = data
        self.key = key
        cfg = data["config"]
        day = data["days"].get(key)
        has_record = bool(day and (
            day.get("morning_done") or day.get("night_done") or day.get("events")
            or day.get("timers") or day.get("steps")))

        lay = QVBoxLayout(self)

        # 上半部分：当日积分明细
        lst = QListWidget()
        rows = []
        if has_record:
            if day.get("morning_done"):
                rows.append(f"{cfg['morning_time']}　早起打卡　{cfg['morning_value']:+d}")
            for e in day.get("events", []):
                rows.append(f"{e['t']}　{e['tag']}　{e['value']:+d}")
            for tm in day.get("timers", []):
                rows.append(f"{tm['start']}~{tm['end']}　{tm['name']}({tm['duration']})　{tm['value']:+d}")
            st = day.get("steps")
            if st:
                rows.append(f"{st['t']}　今日步数 {st['count']}　{st['value']:+d}")
            if day.get("night_done"):
                rows.append(f"{cfg['night_time']}　晚间清零")
        else:
            rows.append("那天空空如也～")
        for r in rows:
            lst.addItem(r)
        lst.setMaximumHeight(130)
        lay.addWidget(lst)

        if has_record:
            before, after = day_score(data, key)
            info = QLabel(f"当日总分：{after:+d}　（晚间扣减前：{before:+d}）")
            info.setStyleSheet("font-weight: bold; color: #333333; padding: 4px 0;")
            lay.addWidget(info)

        # 下半部分：闲笔
        lay.addWidget(QLabel("闲笔"))
        placeholder = cfg.get("note_placeholder", "今天有什么想说的？")
        self.note_edit = NoteEdit(placeholder)
        note = day.get("note", "") if day else ""
        self.note_edit.setPlainText(note)
        lay.addWidget(self.note_edit, 1)

        # 底部：保存 + 上次修改时间
        bottom = QHBoxLayout()
        self.btn_save = QPushButton("💾 保存闲笔")
        self.btn_save.clicked.connect(self.save_note)
        updated = day.get("note_updated", "") if day else ""
        self.time_label = QLabel(f"上次修改：{updated}" if updated else "上次修改：—")
        self.time_label.setObjectName("note_time")
        bottom.addWidget(self.btn_save)
        bottom.addStretch(1)
        bottom.addWidget(self.time_label)
        lay.addLayout(bottom)

    def save_note(self):
        day = self.data["days"].setdefault(self.key, {
            "morning_done": False, "night_done": False, "events": []})
        day["note"] = self.note_edit.toPlainText()
        day["note_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        save_data(self.data)
        self.time_label.setText(f"上次修改：{day['note_updated']}")


# ---------------------------------------------------------------------------
# 设置对话框
# ---------------------------------------------------------------------------
class SettingsDialog(QDialog):
    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.data = data
        self.setWindowTitle("⚙️ 设置")
        self.setMinimumWidth(380)
        cfg = data["config"]

        lay = QVBoxLayout(self)

        # ---- 早晚自动加减 ----
        form = QFormLayout()
        self.morning_time = QTimeEdit(QTime.fromString(cfg["morning_time"], "HH:mm"))
        self.morning_value = QSpinBox(); self.morning_value.setRange(-999, 999)
        self.morning_value.setValue(cfg["morning_value"])
        self.night_time = QTimeEdit(QTime.fromString(cfg["night_time"], "HH:mm"))
        form.addRow("早起时间", self.morning_time)
        form.addRow("早起加分", self.morning_value)
        form.addRow("晚间清零时间", self.night_time)
        self.note_placeholder_edit = QLineEdit()
        self.note_placeholder_edit.setText(cfg.get("note_placeholder", "今天有什么想说的？"))
        form.addRow("闲笔占位", self.note_placeholder_edit)
        lay.addLayout(form)

        # ---- 步数积分参数 ----
        lay.addWidget(QLabel("步数积分（达不到基础步数扣 a；达到后每多 c 步加 b）"))
        step_form = QFormLayout()
        self.step_base = QSpinBox(); self.step_base.setRange(0, 200000); self.step_base.setValue(cfg.get("step_base", 8000))
        self.step_a = QSpinBox(); self.step_a.setRange(0, 999); self.step_a.setValue(cfg.get("step_a", 5))
        self.step_b = QSpinBox(); self.step_b.setRange(0, 999); self.step_b.setValue(cfg.get("step_b", 2))
        self.step_c = QSpinBox(); self.step_c.setRange(1, 100000); self.step_c.setValue(cfg.get("step_c", 1000))
        step_form.addRow("基础步数", self.step_base)
        step_form.addRow("扣分 a", self.step_a)
        step_form.addRow("每步加分 b", self.step_b)
        step_form.addRow("步数间隔 c", self.step_c)
        lay.addLayout(step_form)

        # ---- 事件标签管理 ----
        lay.addWidget(QLabel("事件标签（点一下就是一次 +N / -N）"))
        self.tag_list = QListWidget()
        self.tag_list.currentRowChanged.connect(self.on_row_changed)
        self.reload_tags()
        lay.addWidget(self.tag_list)

        row = QHBoxLayout()
        self.tag_name = QLineEdit(); self.tag_name.setPlaceholderText("名称，如 背单词")
        self.tag_value = QSpinBox(); self.tag_value.setRange(-999, 999)
        self.btn_add = QPushButton("添加"); self.btn_add.clicked.connect(self.add_tag)
        self.btn_upd = QPushButton("更新"); self.btn_upd.clicked.connect(self.update_tag)
        self.btn_del = QPushButton("删除"); self.btn_del.clicked.connect(self.delete_tag)
        row.addWidget(self.tag_name, 2)
        row.addWidget(self.tag_value, 1)
        row.addWidget(self.btn_add)
        row.addWidget(self.btn_upd)
        row.addWidget(self.btn_del)
        lay.addLayout(row)

        # 背景设置
        lay.addWidget(QLabel("背景"))
        bg_row = QHBoxLayout()
        self.btn_bg_image = QPushButton("🖼 选择背景图")
        self.btn_bg_image.clicked.connect(self.pick_image)
        self.btn_bg_color = QPushButton("🎨 纯色背景")
        self.btn_bg_color.clicked.connect(self.pick_color)
        self.btn_bg_reset = QPushButton("↩️ 恢复默认")
        self.btn_bg_reset.clicked.connect(self.reset_bg)
        bg_row.addWidget(self.btn_bg_image)
        bg_row.addWidget(self.btn_bg_color)
        bg_row.addWidget(self.btn_bg_reset)
        lay.addLayout(bg_row)

        alpha_row = QHBoxLayout()
        alpha_row.addWidget(QLabel("遮罩"))
        self.alpha_slider = QSlider(Qt.Horizontal)
        self.alpha_slider.setRange(0, 255)
        self.alpha_slider.setValue(cfg.get("bg_overlay_alpha", 120))
        self.alpha_slider.valueChanged.connect(self.on_alpha_changed)
        self.alpha_label = QLabel()
        alpha_row.addWidget(self.alpha_slider, 1)
        alpha_row.addWidget(self.alpha_label)
        lay.addLayout(alpha_row)
        self.on_alpha_changed(cfg.get("bg_overlay_alpha", 120))

        self.bg_hint = QLabel()
        self.bg_hint.setStyleSheet("color:#888888; font-size:11px;")
        self.update_bg_hint()
        lay.addWidget(self.bg_hint)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.on_ok)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

    # ---- 标签管理 ----
    def reload_tags(self):
        self.tag_list.clear()
        for t in self.data["tags"]:
            self.tag_list.addItem(f"{t['name']}   ({t['value']:+d})")

    def on_row_changed(self, row):
        if 0 <= row < len(self.data["tags"]):
            t = self.data["tags"][row]
            self.tag_name.setText(t["name"])
            self.tag_value.setValue(t["value"])

    def add_tag(self):
        name = self.tag_name.text().strip()
        if not name:
            return
        self.data["tags"].append({"name": name, "value": self.tag_value.value()})
        self.reload_tags()
        self.tag_name.clear()

    def update_tag(self):
        row = self.tag_list.currentRow()
        if not (0 <= row < len(self.data["tags"])):
            return
        name = self.tag_name.text().strip()
        if not name:
            return
        self.data["tags"][row]["name"] = name
        self.data["tags"][row]["value"] = self.tag_value.value()
        self.reload_tags()

    def delete_tag(self):
        row = self.tag_list.currentRow()
        if not (0 <= row < len(self.data["tags"])):
            return
        del self.data["tags"][row]
        self.reload_tags()

    # ---- 背景 ----
    def update_bg_hint(self):
        img = self.data["config"].get("bg_image", "")
        self.bg_hint.setText(f"当前背景：{os.path.basename(img)}" if img else "当前背景：默认纯色")

    def on_alpha_changed(self, v):
        self.alpha_label.setText(str(v))

    def pick_image(self):
        fname, _ = QFileDialog.getOpenFileName(
            self, "选择背景图", "", "图片 (*.png *.jpg *.jpeg *.bmp *.gif *.webp)")
        if fname:
            self.data["config"]["bg_image"] = fname
            self.update_bg_hint()

    def pick_color(self):
        cur = self.data["config"].get("bg_color", "#f5f7fa")
        color = QColorDialog.getColor(QColor(cur), self, "选择背景颜色")
        if color.isValid():
            self.data["config"]["bg_color"] = color.name()
            self.data["config"]["bg_image"] = ""
            self.update_bg_hint()

    def reset_bg(self):
        cfg = self.data["config"]
        cfg["bg_image"] = ""
        cfg["bg_color"] = "#f5f7fa"
        cfg["bg_overlay_alpha"] = 120
        self.alpha_slider.setValue(120)
        self.update_bg_hint()

    # ---- 保存 ----
    def on_ok(self):
        cfg = self.data["config"]
        cfg["morning_time"] = self.morning_time.time().toString("HH:mm")
        cfg["morning_value"] = self.morning_value.value()
        cfg["night_time"] = self.night_time.time().toString("HH:mm")
        cfg["bg_overlay_alpha"] = self.alpha_slider.value()
        cfg["note_placeholder"] = (self.note_placeholder_edit.text().strip()
                                   or "今天有什么想说的？")
        cfg["step_base"] = self.step_base.value()
        cfg["step_a"] = self.step_a.value()
        cfg["step_b"] = self.step_b.value()
        cfg["step_c"] = self.step_c.value()
        self.accept()


# ---------------------------------------------------------------------------
# 主窗口
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.data = load_data()
        self.setWindowTitle("🌊 面川")
        ic = get_icon_path()
        if ic:
            self.setWindowIcon(QIcon(ic))
        self.resize(470, 725)
        self.setMinimumSize(440, 660)
        # 计时状态
        self._timer_running = False   # 是否在计时中（含暂停）
        self._timer_begin = None      # 开始时间 datetime
        self._timer_elapsed = 0       # 已累计秒数（不含暂停）
        self._timer_paused = False    # 当前是否处于暂停
        self._timer_accum = 0.0       # 暂停前已累计的真实秒数
        self._timer_segment_start = None  # 当前这段计时的起点 datetime
        self._timer_display = QTimer(self)
        self._timer_display.timeout.connect(self._update_timer)
        self._build_ui()
        # 启动时检查一次"到点自动加减"
        self.check_auto()
        self.refresh_all()

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(8)

        # 标题行
        top = QHBoxLayout()
        self.title_label = QLabel("🌊 面川"); self.title_label.setObjectName("title")
        self.date_label = QLabel(); self.date_label.setObjectName("date")
        top.addWidget(self.title_label)
        top.addStretch(1)
        top.addWidget(self.date_label)
        root.addLayout(top)

        # 标语
        self.slogan_label = QLabel("捕食饮水，清早眉间白云生")
        self.slogan_label.setObjectName("slogan")
        self.slogan_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self.slogan_label)

        # 今日分数 + 状态
        self.score_label = QLabel("0"); self.score_label.setObjectName("score")
        self.score_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self.score_label)
        self.status_label = QLabel(); self.status_label.setObjectName("status")
        self.status_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self.status_label)

        # 今日流水
        self.log_list = QListWidget()
        self.log_list.setMaximumHeight(110)
        root.addWidget(self.log_list)

        # 一次性任务区
        ot_header = QHBoxLayout()
        ot_title = QLabel("🎯 一次性任务"); ot_title.setObjectName("ot_title")
        self.btn_add_ot = QPushButton("＋"); self.btn_add_ot.setFixedWidth(32)
        self.btn_add_ot.clicked.connect(self.add_one_time)
        ot_header.addWidget(ot_title)
        ot_header.addStretch(1)
        ot_header.addWidget(self.btn_add_ot)
        root.addLayout(ot_header)

        self.ot_list = QListWidget()
        self.ot_list.setMaximumHeight(100)
        self.ot_list.itemClicked.connect(self.on_ot_clicked)
        root.addWidget(self.ot_list)

        # 事件选择（下拉框 + 记一笔）
        evt_row = QHBoxLayout()
        self.evt_combo = QComboBox()
        self.evt_combo.setMinimumHeight(36)
        self.btn_apply = QPushButton("记一笔")
        self.btn_apply.clicked.connect(self.apply_selected_tag)
        evt_row.addWidget(self.evt_combo, 1)
        evt_row.addWidget(self.btn_apply)
        root.addLayout(evt_row)
        self.refresh_combo()

        # 计时区（设置行上方，独立的一条）
        timer_row = QHBoxLayout()
        timer_row.addWidget(QLabel("⏱ 计时"))
        self.timer_label = QLabel("00:00:00")
        self.timer_label.setObjectName("timer_label")
        self.timer_label.setAlignment(Qt.AlignCenter)
        timer_row.addWidget(self.timer_label, 1)
        self.timer_name = QLineEdit(); self.timer_name.setPlaceholderText("计时名（记录到日志）")
        self.timer_name.setMaximumWidth(150)
        timer_row.addWidget(self.timer_name)
        self.timer_value = QSpinBox(); self.timer_value.setRange(-999, 999); self.timer_value.setValue(5)
        self.timer_value.setMaximumWidth(60)
        timer_row.addWidget(self.timer_value)
        self.btn_timer = QPushButton("▶ 开始")
        self.btn_timer.clicked.connect(self.on_timer_button)
        timer_row.addWidget(self.btn_timer)
        self.btn_timer_end = QPushButton("✓ 结束")
        self.btn_timer_end.clicked.connect(self._timer_finish)
        self.btn_timer_end.setEnabled(False)
        timer_row.addWidget(self.btn_timer_end)
        root.addLayout(timer_row)

        # 步数记录行
        step_row = QHBoxLayout()
        step_row.addWidget(QLabel("👣 今日步数"))
        self.steps_edit = QLineEdit(); self.steps_edit.setPlaceholderText("输入今日步数")
        self.steps_edit.setMaximumWidth(110)
        step_row.addWidget(self.steps_edit)
        self.btn_steps = QPushButton("记录步数")
        self.btn_steps.clicked.connect(self.record_steps)
        step_row.addWidget(self.btn_steps)
        self.step_score_label = QLabel()
        self.step_score_label.setObjectName("step_score")
        step_row.addWidget(self.step_score_label, 1)
        root.addLayout(step_row)

        # 底部操作按钮（右侧放计时结束）
        row = QHBoxLayout()
        self.btn_set = QPushButton("⚙️ 设置"); self.btn_set.clicked.connect(self.open_settings)
        row.addWidget(self.btn_set)
        row.addStretch(1)
        root.addLayout(row)

        # 日历
        self.cal_ym = QLabel()
        self.cal_ym.setObjectName("cal_ym")
        root.addWidget(self.cal_ym, alignment=Qt.AlignCenter)
        self.calendar = WaterCalendar()
        self.calendar.setFirstDayOfWeek(Qt.Sunday)
        self.calendar.setGridVisible(True)
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        self.calendar.clicked.connect(self.on_date_clicked)
        self.calendar.currentPageChanged.connect(self._update_cal_ym)
        self._update_cal_ym(self.calendar.yearShown(), self.calendar.monthShown())
        root.addWidget(self.calendar)

        self.setStyleSheet(APP_QSS)

    def refresh_combo(self):
        """按当前标签刷新事件下拉框。"""
        self.evt_combo.clear()
        for tag in self.data["tags"]:
            self.evt_combo.addItem(f"{tag['name']}  ({tag['value']:+d})", tag)

    def apply_selected_tag(self):
        """对下拉框选中的事件记一笔。"""
        idx = self.evt_combo.currentIndex()
        if idx < 0:
            return
        tag = self.evt_combo.itemData(idx)
        if tag:
            self.on_tag_clicked(tag)

    # ---- 计时 ----
    def on_timer_button(self):
        """开始/暂停/继续/结束 的统一入口。"""
        if not self._timer_running:
            self._timer_start()
        elif not self._timer_paused:
            self._timer_pause()
        else:
            self._timer_resume()

    def _timer_start(self):
        self._timer_running = True
        self._timer_paused = False
        self._timer_begin = datetime.now()
        self._timer_segment_start = datetime.now()
        self._timer_accum = 0.0
        self._timer_elapsed = 0
        self._timer_display.start(500)
        self.btn_timer.setText("⏸ 暂停")
        self.btn_timer_end.setEnabled(True)
        self.timer_label.setText("00:00:00")

    def _timer_pause(self):
        # 把当前这段的真实时长存进累计值
        self._timer_accum += (datetime.now() - self._timer_segment_start).total_seconds()
        self._timer_paused = True
        self._timer_display.stop()
        self.btn_timer.setText("▶ 继续")

    def _timer_resume(self):
        self._timer_segment_start = datetime.now()
        self._timer_paused = False
        self._timer_display.start(500)
        self.btn_timer.setText("⏸ 暂停")

    def _timer_finish(self):
        """结束计时，写入今天日志，更新界面。"""
        # 先算出真实总时长：累计值 + 当前未暂停段的时间差
        elapsed = self._timer_accum
        if self._timer_running and not self._timer_paused:
            elapsed += (datetime.now() - self._timer_segment_start).total_seconds()
        self._timer_elapsed = int(elapsed)

        self._timer_display.stop()
        self._timer_running = False
        self._timer_paused = False
        self.btn_timer.setText("▶ 开始")
        self.btn_timer_end.setEnabled(False)
        self.timer_label.setText("00:00:00")

        name = self.timer_name.text().strip()
        if not name:
            self.status_label.setText("⚠️ 计时结束：请先填写计时名")
            QTimer.singleShot(3000, self.refresh_all)
            return

        key = ensure_today(self.data)
        dur = self._duration_str(self._timer_elapsed)
        start_s = self._timer_begin.strftime("%H:%M:%S")
        end_s = (self._timer_begin +
                 timedelta(seconds=self._timer_elapsed)).strftime("%H:%M:%S")
        self.data["days"][key].setdefault("timers", []).append({
            "start": start_s,
            "end": end_s,
            "duration": dur,
            "name": name,
            "value": self.timer_value.value(),
        })
        save_data(self.data)
        self.refresh_all()

    def _update_timer(self):
        # 用真实时间差计算，不依赖定时器心跳次数（心跳间隔≠1秒）
        if self._timer_running and not self._timer_paused:
            total = self._timer_accum + (datetime.now() - self._timer_segment_start).total_seconds()
            self._timer_elapsed = int(total)
            self.timer_label.setText(self._duration_str(self._timer_elapsed))

    @staticmethod
    def _duration_str(seconds):
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    # ---- 一次性任务 ----
    def add_one_time(self):
        dlg = AddOneTimeDialog(self)
        if dlg.exec():
            name, value = dlg.get_data()
            if name:
                self.data.setdefault("one_time", []).append({"name": name, "value": value})
                save_data(self.data)
                self.refresh_all()

    def on_ot_clicked(self, item):
        row = self.ot_list.row(item)
        one_time = self.data.get("one_time", [])
        if not (0 <= row < len(one_time)):
            return
        task = one_time[row]
        ret = QMessageBox.question(
            self, "确认", f"完成一次性任务「{task['name']}」？分值 {task['value']:+d}")
        if ret != QMessageBox.Yes:
            return
        # 延迟到点击事件处理完再改列表，避免在 itemClicked 槽里 clear 列表导致崩溃
        QTimer.singleShot(0, lambda: self._complete_ot(row))

    def _complete_ot(self, row):
        one_time = self.data.get("one_time", [])
        if not (0 <= row < len(one_time)):
            return
        task = one_time[row]
        del one_time[row]
        key = ensure_today(self.data)
        self.data["days"][key]["events"].append({
            "t": datetime.now().strftime("%H:%M"),
            "tag": task["name"],
            "value": task["value"],
        })
        save_data(self.data)
        self.refresh_all()

    def refresh_ot(self):
        self.ot_list.clear()
        for task in self.data.get("one_time", []):
            self.ot_list.addItem(f"{task['name']}  {task['value']:+d}")

    def on_tag_clicked(self, tag):
        key = ensure_today(self.data)
        self.data["days"][key]["events"].append({
            "t": datetime.now().strftime("%H:%M"),
            "tag": tag["name"],
            "value": tag["value"],
        })
        save_data(self.data)
        self.refresh_all()

    # ---- 步数记录 ----
    def record_steps(self):
        """记录今日步数（覆盖当天，取最后一次为准）。"""
        text = self.steps_edit.text().strip()
        if not text:
            self.status_label.setText("⚠️ 请输入今日步数")
            QTimer.singleShot(3000, self.refresh_all)
            return
        try:
            count = int(text)
        except ValueError:
            self.status_label.setText("⚠️ 步数必须是数字")
            QTimer.singleShot(3000, self.refresh_all)
            return
        if count < 0:
            self.status_label.setText("⚠️ 步数不能为负数")
            QTimer.singleShot(3000, self.refresh_all)
            return

        cfg = self.data["config"]
        key = ensure_today(self.data)
        self.data["days"][key]["steps"] = {
            "count": count,
            "t": datetime.now().strftime("%H:%M"),
            "value": step_value(cfg, count),
        }
        save_data(self.data)
        self.refresh_all()

    def _refresh_step_display(self, day):
        """刷新步数栏显示：已记录则回显步数与本次得分。"""
        st = day.get("steps")
        if st:
            self.steps_edit.setText(str(st["count"]))
            self.step_score_label.setText(f"→ {st['count']} 步　{st['value']:+d} 分")
        else:
            self.step_score_label.setText("")

    def paintEvent(self, event):
        """绘制主窗口背景：图片(等比铺满+遮罩) 或纯色。"""
        painter = QPainter(self)
        cfg = self.data["config"]
        img = cfg.get("bg_image", "")
        alpha = cfg.get("bg_overlay_alpha", 120)
        if img and os.path.exists(img):
            pix = QPixmap(img)
            if not pix.isNull():
                scaled = pix.scaled(
                    self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                x = (scaled.width() - self.width()) // 2
                y = (scaled.height() - self.height()) // 2
                painter.drawPixmap(0, 0, scaled.copy(QRect(x, y, self.width(), self.height())))
                if alpha > 0:
                    painter.fillRect(self.rect(), QColor(255, 255, 255, alpha))
                painter.end()
                return
        painter.fillRect(self.rect(), QColor(cfg.get("bg_color", "#f5f7fa")))
        painter.end()

    def check_auto(self):
        """启动时自动检查：早起加分(当天) + 晚间结算(目标日)。"""
        now = datetime.now()
        now_str = now.strftime("%H:%M")
        cfg = self.data["config"]
        changed = False

        # 早起加分：作用于当天
        key = ensure_today(self.data)
        day = self.data["days"][key]
        if not day["morning_done"] and now_str >= cfg["morning_time"]:
            day["morning_done"] = True
            changed = True

        # 晚间结算：作用于结算目标日
        target = get_settle_target(cfg, now)
        if target:
            tday = self.data["days"].setdefault(target, {
                "morning_done": False, "night_done": False, "events": []})
            if not tday["night_done"]:
                tday["night_done"] = True
                changed = True

        if changed:
            save_data(self.data)
        self.refresh_all()

    def open_settings(self):
        dlg = SettingsDialog(self.data, self)
        if dlg.exec():
            save_data(self.data)
            self.refresh_combo()
            self.refresh_all()
            self.update()  # 立即重绘背景

    # ---- 界面刷新 ----
    def refresh_all(self):
        key = date_key()
        cfg = self.data["config"]
        day = self.data["days"].get(key, {"morning_done": False, "night_done": False, "events": []})
        before, after = day_score(self.data, key)

        self.date_label.setText(datetime.now().strftime("%m月%d日 %A"))
        self.score_label.setText(f"{after:+d}")
        self.score_label.setStyleSheet("color:#2e7d32" if after >= 0 else "color:#c62828")

        m = "✓" if day["morning_done"] else "○"
        n = "✓" if day["night_done"] else "○"
        self.status_label.setText(
            f"早起 {cfg['morning_time']} {cfg['morning_value']:+d} {m}"
            f"　｜　晚间 {cfg['night_time']} 清零 {n}"
        )

        self.refresh_log(key, day)
        self.refresh_ot()
        self._refresh_step_display(day)
        self.refresh_calendar()

    def refresh_log(self, key, day):
        self.log_list.clear()
        cfg = self.data["config"]
        rows = []
        if day.get("morning_done"):
            rows.append(f"{cfg['morning_time']}　早起打卡　{cfg['morning_value']:+d}")
        for e in day["events"]:
            rows.append(f"{e['t']}　{e['tag']}　{e['value']:+d}")
        for tm in day.get("timers", []):
            rows.append(f"{tm['start']}~{tm['end']}　{tm['name']}({tm['duration']})　{tm['value']:+d}")
        st = day.get("steps")
        if st:
            rows.append(f"{st['t']}　今日步数 {st['count']}　{st['value']:+d}")
        if day.get("night_done"):
            rows.append(f"{cfg['night_time']}　晚间清零")
        for r in rows:
            self.log_list.addItem(r)

    def refresh_calendar(self):
        scores = {}
        note_dates = []
        for key in self.data["days"]:
            before, _ = day_score(self.data, key)
            scores[QDate.fromString(key, "yyyy-MM-dd")] = before
            day = self.data["days"][key]
            if day.get("note", "").strip():
                note_dates.append(QDate.fromString(key, "yyyy-MM-dd"))
        self.calendar.set_scores(scores)
        self.calendar.set_note_dates(note_dates)

    def _update_cal_ym(self, year, month):
        self.cal_ym.setText(f"📅 {year}年 {month}月")

    def on_date_clicked(self, qdate):
        """点击日历某天，查看明细 + 写闲笔。"""
        key = qdate.toString("yyyy-MM-dd")
        dlg = DayDetailDialog(self.data, key, self)
        dlg.exec()
        # 关闭弹窗后刷新，让闲笔标记/分数立刻生效
        self.refresh_all()


# ---------------------------------------------------------------------------
# 界面样式
# ---------------------------------------------------------------------------
APP_QSS = """
QMainWindow, QWidget { background: #f5f7fa; font-family: "Microsoft YaHei"; font-size: 13px; }
QWidget#central { background: transparent; }
QLabel { background: transparent; }
QLabel#title { font-size: 20px; font-weight: bold; color: #1a1a2e; background: transparent; }
QLabel#slogan { font-size: 13px; color: #8a8f9a; font-style: italic; background: transparent; padding-bottom: 2px; }
QLabel#date  { font-size: 12px; color: #666; background: transparent; }
QLabel#score { font-size: 46px; font-weight: bold; background: transparent; }
QLabel#status{ font-size: 12px; color: #555; background: transparent; }
QLabel#ot_title { font-size: 13px; font-weight: bold; color: #555; background: transparent; }
QLabel#cal_ym { font-size: 15px; font-weight: bold; color: #333333; background: transparent; padding: 4px 0; }
QLabel#timer_label { font-size: 18px; font-weight: bold; color: #1d4ed8; background: transparent; }
QLabel#step_score { font-size: 13px; font-weight: bold; color: #b45309; background: transparent; }

QPushButton { background: rgba(255,255,255,175); border: 1px solid rgba(120,130,150,130); border-radius: 8px; padding: 6px; }
QPushButton:hover { background: rgba(240,245,255,205); }
QPushButton[kind="pos"] { background: #e8f5e9; border-color: #a5d6a7; color: #1b5e20; font-weight: bold; }
QPushButton[kind="pos"]:hover { background: #c8e6c9; }
QPushButton[kind="neg"] { background: #fdecea; border-color: #ef9a9a; color: #b71c1c; font-weight: bold; }
QPushButton[kind="neg"]:hover { background: #ffcdd2; }

QComboBox { background: rgba(255,255,255,175); color: #333333; border: 1px solid rgba(120,130,150,130); border-radius: 6px; padding: 4px 8px; min-height: 20px; }
QComboBox:hover { border-color: #8ab4f8; }
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView { background: rgba(255,255,255,235); color: #333333; selection-background-color: #d7e6ff; selection-color: #1a1a2e; outline: none; }

QListWidget { background: rgba(255,255,255,175); border: 1px solid rgba(120,130,150,130); border-radius: 6px; }
QCalendarWidget { background: #ffffff; color: #333333; }
QCalendarWidget QToolButton { color: #333333; background: transparent; border: none; font-weight: bold; }
QCalendarWidget QToolButton:hover { background: #eef1f5; border-radius: 4px; }
QCalendarWidget QSpinBox { color: #333333; background: transparent; border: none; }
QCalendarWidget QAbstractItemView { background: #ffffff; color: #333333; selection-background-color: #d7e6ff; selection-color: #1a1a2e; }
"""


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
