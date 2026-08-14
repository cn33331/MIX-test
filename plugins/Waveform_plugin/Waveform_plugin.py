import sys
import os
import csv
import math
import importlib
import numpy as np
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QButtonGroup, QLineEdit, QLabel, QDialog,
                             QSizePolicy, QCompleter, QMessageBox, QApplication,
                             QStylePainter, QStyleOptionFrame, QFileDialog)
from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import QPainter, QPen, QColor, QFont, QPolygonF, QPixmap

import fft_processor
from PyQt6.uic import loadUi

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PLUGIN_DIR)


def get_resource_path(relative_path):
    """获取资源文件的绝对路径。

    插件目录在外部，不从 MEIPASS 加载，直接拼接插件目录与相对路径。

    Args:
        relative_path (str): 资源文件的相对路径。

    Returns:
        str: 资源文件的绝对路径。

    Example:
        >>> ui_path = get_resource_path('main.ui')
        >>> print(ui_path)
    """
    return os.path.join(PLUGIN_DIR, relative_path)


def load_external_file(file_name):
    """动态加载外部Python文件。

    从可执行文件所在目录加载指定的Python文件作为模块，
    支持热修改（修改后重启程序即可生效）。

    Args:
        file_name (str): 要加载的外部文件名（如 config.py）。

    Returns:
        module: 加载后的模块对象，可像正常 import 一样使用。

    Raises:
        FileNotFoundError: 当指定文件不存在时抛出。

    Example:
        >>> config = load_external_file('config.py')
        >>> print(config.SETTINGS)
    """
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
    else:
        exe_dir = os.path.dirname(os.path.abspath(__file__))

    file_path = os.path.join(exe_dir, file_name)

    if not os.path.exists(file_path):
        raise FileNotFoundError(
            f"未找到外部文件：{file_name}\n"
            f"请将{file_name}放在可执行文件所在目录：{exe_dir}"
        )

    spec = importlib.util.spec_from_file_location(
        name=file_name[:-3],
        location=file_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    print(f"✅ 成功加载外部文件：{file_path}（修改后重启程序即可生效）")
    return module


def enable_drag_drop(line_edit: QLineEdit):
    """使给定的 QLineEdit 控件具有文件拖放功能。

    为输入框添加 dragEnterEvent、dragMoveEvent 和 dropEvent 处理，
    支持将文件从文件管理器拖放到输入框中自动填充路径。

    Args:
        line_edit (QLineEdit): 要启用拖放功能的输入框对象。

    Example:
        >>> from PyQt6.QtWidgets import QLineEdit
        >>> edit = QLineEdit()
        >>> enable_drag_drop(edit)
    """
    def dragEnterEvent(event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls:
                path = urls[0].toLocalFile()
                line_edit.setText(path)
            event.acceptProposedAction()
        else:
            event.ignore()

    line_edit.setAcceptDrops(True)
    line_edit.dragEnterEvent = dragEnterEvent
    line_edit.dragMoveEvent = dragMoveEvent
    line_edit.dropEvent = dropEvent


def decimate_data(x, y, max_points=10000):
    """数据降采样函数，使用LTTB算法保持视觉特征。

    使用 Largest Triangle Three Buckets 算法将大数据集降采样到
    指定的最大点数，同时尽可能保留数据的视觉特征。

    Args:
        x (numpy.ndarray or list): X轴数据数组。
        y (numpy.ndarray or list): Y轴数据数组。
        max_points (int, optional): 降采样后的最大点数。默认值为 10000。

    Returns:
        tuple: 包含以下元素的元组：
            - result_x (numpy.ndarray): 降采样后的X轴数据。
            - result_y (numpy.ndarray): 降采样后的Y轴数据。

    Example:
        >>> x = np.linspace(0, 1, 100000)
        >>> y = np.sin(x * 2 * np.pi)
        >>> x_down, y_down = decimate_data(x, y, max_points=1000)
        >>> print(len(x_down))
        1000
    """
    n = len(x)
    if n <= max_points:
        return x, y

    step = n / max_points
    result_x = []
    result_y = []

    result_x.append(x[0])
    result_y.append(y[0])

    for i in range(1, max_points - 1):
        bucket_start = int((i - 1) * step)
        bucket_end = int(i * step)
        next_bucket_end = int((i + 1) * step)

        max_area = -1
        max_idx = bucket_start

        prev_x = result_x[-1]
        prev_y = result_y[-1]

        next_avg_x = np.mean(x[min(bucket_end, n-1):min(next_bucket_end, n-1)])
        next_avg_y = np.mean(y[min(bucket_end, n-1):min(next_bucket_end, n-1)])

        for j in range(bucket_start, min(bucket_end, n-1)):
            area = abs((x[j] - prev_x) * (next_avg_y - prev_y) -
                       (next_avg_x - prev_x) * (y[j] - prev_y))
            if area > max_area:
                max_area = area
                max_idx = j

        result_x.append(x[max_idx])
        result_y.append(y[max_idx])

    result_x.append(x[-1])
    result_y.append(y[-1])

    return np.array(result_x), np.array(result_y)


class ZoomMode:
    """缩放模式常量定义类。

    定义绘图控件支持的三种缩放模式，用于控制滚轮缩放时的行为。

    Attributes:
        WIDTH (int): 仅宽度缩放模式，值为 0。
        HEIGHT (int): 仅高度缩放模式，值为 1。
        CENTER (int): 中心缩放模式（宽高同时缩放），值为 2。

    Example:
        >>> mode = ZoomMode.WIDTH
        >>> print(mode)
        0
    """
    WIDTH = 0
    HEIGHT = 1
    CENTER = 2


class PlotWidget(QWidget):
    """轻量级绘图控件，使用 QPainter 绘制，支持平移和缩放。

    基于 Qt 的 QWidget 自定义控件，直接使用 QPainter 进行绘制，
    支持鼠标拖动平移、滚轮缩放、键盘快捷操作等功能。

    Attributes:
        x_data (numpy.ndarray): X轴数据数组。
        y_data (numpy.ndarray): Y轴数据数组。
        x_label (str): X轴标签文字。
        y_label (str): Y轴标签文字。
        title (str): 图表标题。
        axv_line (tuple or None): 垂直标记线信息 (x, color, label)。
        x_min_view (float): X轴视图左边界。
        x_max_view (float): X轴视图右边界。
        y_min_view (float): Y轴视图下边界。
        y_max_view (float): Y轴视图上边界。
        is_dragging (bool): 是否正在拖动视图。
        last_pos (QPointF): 上一次鼠标位置。
        zoom_mode (int): 当前缩放模式，见 ZoomMode 类。

    Example:
        >>> plot = PlotWidget()
        >>> plot.set_data([1, 2, 3], [4, 5, 6])
        >>> plot.set_labels("时间", "电压")
        >>> plot.show()
    """

    def __init__(self, parent=None):
        """初始化 PlotWidget 控件。

        设置初始数据、视图范围、鼠标样式和焦点策略等。

        Args:
            parent (QWidget, optional): 父窗口对象。默认值为 None。
        """
        super().__init__(parent)
        self.x_data = []
        self.y_data = []
        self.x_label = "X"
        self.y_label = "Y"
        self.title = ""
        self.axv_line = None
        self.setMinimumSize(600, 400)
        self.setBackgroundRole(QtGui.QPalette.ColorRole.Base)
        self.setAutoFillBackground(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.x_min_view = None
        self.x_max_view = None
        self.y_min_view = None
        self.y_max_view = None
        self.is_dragging = False
        self.last_pos = QPointF()
        self.setCursor(Qt.CursorShape.CrossCursor)

        self.zoom_mode = ZoomMode.WIDTH

    def get_zoom_mode_name(self):
        """获取当前缩放模式的中文名称。

        Returns:
            str: 当前缩放模式的名称，可能为 "宽度缩放"、"高度缩放" 或 "中心缩放"。

        Example:
            >>> plot = PlotWidget()
            >>> print(plot.get_zoom_mode_name())
            宽度缩放
        """
        if self.zoom_mode == ZoomMode.WIDTH:
            return "宽度缩放"
        elif self.zoom_mode == ZoomMode.HEIGHT:
            return "高度缩放"
        else:
            return "中心缩放"

    def set_data(self, x, y):
        """设置绘图数据并初始化视图范围。

        将输入数据转换为 numpy 数组，并自动计算数据范围作为初始视图。

        Args:
            x (array_like): X轴数据。
            y (array_like): Y轴数据。

        Example:
            >>> plot = PlotWidget()
            >>> plot.set_data([0, 1, 2], [0, 1, 0])
        """
        self.x_data = np.array(x)
        self.y_data = np.array(y)
        if len(self.x_data) > 0:
            self.x_min_view = np.min(self.x_data)
            self.x_max_view = np.max(self.x_data)
        if len(self.y_data) > 0:
            self.y_min_view = np.min(self.y_data)
            self.y_max_view = np.max(self.y_data)
        self.update()

    def set_labels(self, x_label, y_label):
        """设置坐标轴标签。

        Args:
            x_label (str): X轴标签文字。
            y_label (str): Y轴标签文字。

        Example:
            >>> plot = PlotWidget()
            >>> plot.set_labels("频率 (Hz)", "幅值 (dBm)")
        """
        self.x_label = x_label
        self.y_label = y_label
        self.update()

    def set_title(self, title):
        """设置图表标题。

        Args:
            title (str): 图表标题文字。

        Example:
            >>> plot = PlotWidget()
            >>> plot.set_title("波形图")
        """
        self.title = title
        self.update()

    def set_vertical_line(self, x, color=QColor(255, 165, 0), label=""):
        """设置垂直标记线。

        在指定X轴位置绘制一条垂直虚线，可附带标签说明。

        Args:
            x (float): 垂直线的X轴坐标位置。
            color (QColor, optional): 线条颜色。默认值为橙色 QColor(255, 165, 0)。
            label (str, optional): 标签文字。默认值为空字符串。

        Example:
            >>> from PyQt6.QtGui import QColor
            >>> plot = PlotWidget()
            >>> plot.set_vertical_line(1000, QColor(255, 0, 0), "目标频率")
        """
        self.axv_line = (x, color, label)
        self.update()

    def clear_vertical_line(self):
        """清除垂直标记线。

        Example:
            >>> plot = PlotWidget()
            >>> plot.clear_vertical_line()
        """
        self.axv_line = None
        self.update()

    def reset_view(self):
        """重置视图为原始数据范围。

        将视图范围重置为数据的最大最小值，显示全部数据。

        Example:
            >>> plot = PlotWidget()
            >>> plot.reset_view()
        """
        if len(self.x_data) > 0:
            self.x_min_view = np.min(self.x_data)
            self.x_max_view = np.max(self.x_data)
        if len(self.y_data) > 0:
            self.y_min_view = np.min(self.y_data)
            self.y_max_view = np.max(self.y_data)
        self.update()

    def mousePressEvent(self, event):
        """鼠标按下事件处理。

        左键按下时开始拖动模式，记录鼠标位置并切换光标样式。

        Args:
            event (QMouseEvent): 鼠标事件对象。
        """
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_dragging = True
            self.last_pos = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        """鼠标移动事件处理。

        在拖动模式下，根据鼠标移动距离平移视图。

        Args:
            event (QMouseEvent): 鼠标事件对象。
        """
        if self.is_dragging and len(self.x_data) > 0:
            delta_x = event.position().x() - self.last_pos.x()
            delta_y = event.position().y() - self.last_pos.y()

            margin = 60
            plot_width = self.width() - 2 * margin
            plot_height = self.height() - 2 * margin

            x_range = self.x_max_view - self.x_min_view
            y_range = self.y_max_view - self.y_min_view

            x_shift = -delta_x * x_range / plot_width
            y_shift = delta_y * y_range / plot_height

            self.x_min_view += x_shift
            self.x_max_view += x_shift
            self.y_min_view += y_shift
            self.y_max_view += y_shift

            self.last_pos = event.position()
            self.update()

    def mouseReleaseEvent(self, event):
        """鼠标释放事件处理。

        左键释放时结束拖动模式，恢复光标样式。

        Args:
            event (QMouseEvent): 鼠标事件对象。
        """
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_dragging = False
            self.setCursor(Qt.CursorShape.CrossCursor)

    def wheelEvent(self, event):
        """鼠标滚轮事件处理。

        根据当前缩放模式，以鼠标位置为中心进行缩放。

        Args:
            event (QWheelEvent): 滚轮事件对象。
        """
        if len(self.x_data) == 0:
            return

        margin = 60
        x = event.position().x()
        y = event.position().y()

        plot_width = self.width() - 2 * margin
        plot_height = self.height() - 2 * margin

        if plot_width <= 0 or plot_height <= 0:
            return

        norm_x = (x - margin) / plot_width
        norm_y = (y - margin) / plot_height

        norm_x = max(0.0, min(1.0, norm_x))
        norm_y = max(0.0, min(1.0, norm_y))

        x_center = self.x_min_view + norm_x * (self.x_max_view - self.x_min_view)
        y_center = self.y_min_view + (1 - norm_y) * (self.y_max_view - self.y_min_view)

        zoom_factor = 0.9 if event.angleDelta().y() > 0 else 1.1

        x_range = self.x_max_view - self.x_min_view
        y_range = self.y_max_view - self.y_min_view

        if self.zoom_mode == ZoomMode.WIDTH:
            new_x_range = x_range * zoom_factor
            x_ratio = (x_center - self.x_min_view) / x_range
            self.x_min_view = x_center - x_ratio * new_x_range
            self.x_max_view = self.x_min_view + new_x_range

        elif self.zoom_mode == ZoomMode.HEIGHT:
            new_y_range = y_range * zoom_factor
            y_ratio = (y_center - self.y_min_view) / y_range
            self.y_min_view = y_center - y_ratio * new_y_range
            self.y_max_view = self.y_min_view + new_y_range

        else:
            new_x_range = x_range * zoom_factor
            new_y_range = y_range * zoom_factor

            x_ratio = (x_center - self.x_min_view) / x_range
            self.x_min_view = x_center - x_ratio * new_x_range
            self.x_max_view = self.x_min_view + new_x_range

            y_ratio = (y_center - self.y_min_view) / y_range
            self.y_min_view = y_center - y_ratio * new_y_range
            self.y_max_view = self.y_min_view + new_y_range

        min_x_range = (np.max(self.x_data) - np.min(self.x_data)) * 0.01
        min_y_range = (np.max(self.y_data) - np.min(self.y_data)) * 0.01

        if self.x_max_view - self.x_min_view < min_x_range:
            self.x_max_view = self.x_min_view + min_x_range
        if self.y_max_view - self.y_min_view < min_y_range:
            self.y_max_view = self.y_min_view + min_y_range

        self.update()

    def keyPressEvent(self, event):
        """键盘事件处理，支持多种快捷键。

        支持的快捷键：
        - +/-: 放大/缩小视图
        - 方向键: 平移视图
        - Home: 重置视图
        - W/H/C: 切换缩放模式（宽度/高度/中心）

        Args:
            event (QKeyEvent): 键盘事件对象。
        """
        if len(self.x_data) == 0:
            return

        zoom_factor = 0.8

        if event.key() == Qt.Key.Key_Plus or event.key() == Qt.Key.Key_Equal:
            self.zoom(zoom_factor)
        elif event.key() == Qt.Key.Key_Minus or event.key() == Qt.Key.Key_Underscore:
            self.zoom(1 / zoom_factor)
        elif event.key() == Qt.Key.Key_Left:
            self.pan(-0.1, 0)
        elif event.key() == Qt.Key.Key_Right:
            self.pan(0.1, 0)
        elif event.key() == Qt.Key.Key_Up:
            self.pan(0, 0.1)
        elif event.key() == Qt.Key.Key_Down:
            self.pan(0, -0.1)
        elif event.key() == Qt.Key.Key_Home:
            self.reset_view()
        elif event.key() == Qt.Key.Key_W:
            self.zoom_mode = ZoomMode.WIDTH
            print(f"缩放模式已切换为：宽度缩放")
        elif event.key() == Qt.Key.Key_H:
            self.zoom_mode = ZoomMode.HEIGHT
            print(f"缩放模式已切换为：高度缩放")
        elif event.key() == Qt.Key.Key_C:
            self.zoom_mode = ZoomMode.CENTER
            print(f"缩放模式已切换为：中心缩放")
        else:
            super().keyPressEvent(event)

    def zoom(self, factor):
        """根据当前缩放模式进行视图缩放。

        以视图中心为基准进行缩放。

        Args:
            factor (float): 缩放因子。小于1表示放大，大于1表示缩小。

        Example:
            >>> plot = PlotWidget()
            >>> plot.zoom(0.5)  # 放大一倍
        """
        x_center = (self.x_min_view + self.x_max_view) / 2
        y_center = (self.y_min_view + self.y_max_view) / 2

        x_range = self.x_max_view - self.x_min_view
        y_range = self.y_max_view - self.y_min_view

        if self.zoom_mode == ZoomMode.WIDTH:
            new_x_range = x_range * factor
            self.x_min_view = x_center - new_x_range / 2
            self.x_max_view = x_center + new_x_range / 2
        elif self.zoom_mode == ZoomMode.HEIGHT:
            new_y_range = y_range * factor
            self.y_min_view = y_center - new_y_range / 2
            self.y_max_view = y_center + new_y_range / 2
        else:
            new_x_range = x_range * factor
            new_y_range = y_range * factor
            self.x_min_view = x_center - new_x_range / 2
            self.x_max_view = x_center + new_x_range / 2
            self.y_min_view = y_center - new_y_range / 2
            self.y_max_view = y_center + new_y_range / 2

        self.update()

    def pan(self, dx_ratio, dy_ratio):
        """按比例平移视图。

        Args:
            dx_ratio (float): X轴平移比例，相对于当前视图范围。
            dy_ratio (float): Y轴平移比例，相对于当前视图范围。

        Example:
            >>> plot = PlotWidget()
            >>> plot.pan(0.1, 0)  # 向右平移10%视图宽度
        """
        x_range = self.x_max_view - self.x_min_view
        y_range = self.y_max_view - self.y_min_view

        x_shift = x_range * dx_ratio
        y_shift = y_range * dy_ratio

        self.x_min_view += x_shift
        self.x_max_view += x_shift
        self.y_min_view += y_shift
        self.y_max_view += y_shift

        self.update()

    def paintEvent(self, event):
        """绘制事件处理，绘制整个图表。

        绘制内容包括：标题、网格线、坐标轴、刻度标签、
        垂直标记线和数据曲线。

        Args:
            event (QPaintEvent): 绘制事件对象。
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        margin = 60
        plot_rect = QRectF(margin, margin,
                          self.width() - 2 * margin,
                          self.height() - 2 * margin)

        if self.title:
            painter.setFont(QFont("Arial", 14, QFont.Weight.Bold))
            painter.drawText(QRectF(0, 0, self.width(), margin),
                           Qt.AlignmentFlag.AlignCenter, self.title)

        if len(self.x_data) < 2:
            return

        x_min, x_max = self.x_min_view, self.x_max_view
        y_min, y_max = self.y_min_view, self.y_max_view

        x_range = x_max - x_min
        y_range = y_max - y_min
        if x_range == 0:
            x_range = 1
        if y_range == 0:
            y_range = 1

        painter.setPen(QColor(200, 200, 200))
        for i in range(5):
            y_pixel = plot_rect.top() + (i / 4.0) * plot_rect.height()
            painter.drawLine(QPointF(plot_rect.left(), y_pixel),
                           QPointF(plot_rect.right(), y_pixel))
            x_pixel = plot_rect.left() + (i / 4.0) * plot_rect.width()
            painter.drawLine(QPointF(x_pixel, plot_rect.top()),
                           QPointF(x_pixel, plot_rect.bottom()))

        painter.setPen(QColor(0, 0, 0))
        painter.drawLine(QPointF(plot_rect.left(), plot_rect.bottom()),
                        QPointF(plot_rect.right(), plot_rect.bottom()))
        painter.drawLine(QPointF(plot_rect.left(), plot_rect.top()),
                        QPointF(plot_rect.left(), plot_rect.bottom()))

        painter.setFont(QFont("Arial", 10))
        painter.drawText(QRectF(0, plot_rect.bottom(), plot_rect.left(), 30),
                        Qt.AlignmentFlag.AlignCenter, self.x_label)
        painter.save()
        painter.translate(15, plot_rect.center().y())
        painter.rotate(-90)
        painter.drawText(QRectF(-50, -15, 100, 30),
                        Qt.AlignmentFlag.AlignCenter, self.y_label)
        painter.restore()

        for i in range(5):
            x_val = x_min + (i / 4.0) * (x_max - x_min)
            x_pixel = plot_rect.left() + (i / 4.0) * plot_rect.width()
            painter.drawText(QPointF(x_pixel - 30, plot_rect.bottom() + 20),
                           self.format_number(x_val))

            y_val = y_max - (i / 4.0) * (y_max - y_min)
            y_pixel = plot_rect.top() + (i / 4.0) * plot_rect.height()
            painter.drawText(QPointF(5, y_pixel + 5),
                           self.format_number(y_val))

        self.paintEventPart2(painter, plot_rect, x_min, x_max, y_min, y_max)

    def format_number(self, num):
        """格式化数字显示，避免科学计数法。

        根据数值大小选择合适的小数位数，使数据更易读。

        Args:
            num (float): 待格式化的数字。

        Returns:
            str: 格式化后的数字字符串。

        Example:
            >>> plot = PlotWidget()
            >>> plot.format_number(1234.567)
            '1234.567'
            >>> plot.format_number(0.000123)
            '0.000123'
        """
        if num == 0:
            return "0"

        abs_num = abs(num)

        if abs_num >= 1000000:
            return f"{num:.1f}"
        elif abs_num >= 1000:
            return f"{int(num):d}"
        elif abs_num >= 1:
            return f"{num:.3f}"
        elif abs_num >= 0.001:
            return f"{num:.6f}"
        elif abs_num >= 0.000001:
            return f"{num:.9f}"
        else:
            return f"{num:.12f}"

    def paintEventPart2(self, painter, plot_rect, x_min, x_max, y_min, y_max):
        """绘制垂直线和数据曲线（paintEvent 的第二部分）。

        为避免 paintEvent 函数过长，将垂直线和数据曲线的绘制
        分离到此函数中。

        Args:
            painter (QPainter): 绘图对象。
            plot_rect (QRectF): 绘图区域矩形。
            x_min (float): X轴视图最小值。
            x_max (float): X轴视图最大值。
            y_min (float): Y轴视图最小值。
            y_max (float): Y轴视图最大值。
        """
        x_range = x_max - x_min
        y_range = y_max - y_min

        if self.axv_line:
            axv_x, axv_color, axv_label = self.axv_line
            if x_min <= axv_x <= x_max:
                norm_x = (axv_x - x_min) / x_range
                pixel_x = plot_rect.left() + norm_x * plot_rect.width()
                painter.setPen(QPen(axv_color, 2, Qt.PenStyle.DashLine))
                painter.drawLine(QPointF(pixel_x, plot_rect.top()),
                                QPointF(pixel_x, plot_rect.bottom()))

                if axv_label:
                    painter.setPen(axv_color)
                    painter.drawText(QPointF(pixel_x + 5, plot_rect.top() + 20),
                                   axv_label)

        painter.setPen(QPen(QColor(30, 144, 255), 1.5))

        mask = (self.x_data >= x_min - x_range * 0.1) & (self.x_data <= x_max + x_range * 0.1)
        visible_x = self.x_data[mask]
        visible_y = self.y_data[mask]

        downsampled_x, downsampled_y = decimate_data(visible_x, visible_y, max_points=5000)

        points = []
        for x_val, y_val in zip(downsampled_x, downsampled_y):
            if x_min <= x_val <= x_max:
                norm_x = (x_val - x_min) / (x_max - x_min)
                norm_y = 1.0 - (y_val - y_min) / (y_max - y_min)
                px = plot_rect.left() + norm_x * plot_rect.width()
                py = plot_rect.top() + norm_y * plot_rect.height()
                points.append(QPointF(px, py))

        if len(points) > 1:
            polygon = QPolygonF(points)
            painter.drawPolyline(polygon)


class WaveformWindow(QDialog):
    """波形显示窗口对话框。

    包含 PlotWidget 绘图控件和控制按钮，用于显示波形图或频谱图。
    支持切换缩放模式、重置视图、保存图片等功能。

    Attributes:
        plot_widget (PlotWidget): 绘图控件对象。
        width_zoom_btn (QPushButton): 宽度缩放按钮。
        height_zoom_btn (QPushButton): 高度缩放按钮。
        center_zoom_btn (QPushButton): 中心缩放按钮。
        zoom_buttons (list): 缩放按钮列表，用于互斥管理。
        reset_btn (QPushButton): 重置视图按钮。
        save_btn (QPushButton): 保存图片按钮。
        close_btn (QPushButton): 关闭窗口按钮。
        hint_label (QLabel): 操作提示标签。

    Example:
        >>> window = WaveformWindow()
        >>> window.plot(voltage_data, 0, 1000)
        >>> window.show()
    """

    def __init__(self, parent=None):
        """初始化波形窗口。

        创建绘图控件和控制按钮，设置布局和信号连接。

        Args:
            parent (QWidget, optional): 父窗口对象。默认值为 None。
        """
        super().__init__(parent)
        self.setWindowTitle("波形图")
        self.setMinimumSize(1000, 600)

        layout = QVBoxLayout()
        self.plot_widget = PlotWidget()
        layout.addWidget(self.plot_widget, stretch=1)

        btn_layout = QHBoxLayout()

        self.width_zoom_btn = QPushButton("宽度缩放 (W)")
        self.width_zoom_btn.setCheckable(True)
        self.width_zoom_btn.setChecked(True)
        self.width_zoom_btn.setStyleSheet(self.get_zoom_button_style())
        btn_layout.addWidget(self.width_zoom_btn)

        self.height_zoom_btn = QPushButton("高度缩放 (H)")
        self.height_zoom_btn.setCheckable(True)
        self.height_zoom_btn.setChecked(False)
        self.height_zoom_btn.setStyleSheet(self.get_zoom_button_style())
        btn_layout.addWidget(self.height_zoom_btn)

        self.center_zoom_btn = QPushButton("中心缩放 (C)")
        self.center_zoom_btn.setCheckable(True)
        self.center_zoom_btn.setChecked(False)
        self.center_zoom_btn.setStyleSheet(self.get_zoom_button_style())
        btn_layout.addWidget(self.center_zoom_btn)

        self.zoom_buttons = [
            self.width_zoom_btn,
            self.height_zoom_btn,
            self.center_zoom_btn
        ]

        self.width_zoom_btn.clicked.connect(self.on_zoom_mode_clicked)
        self.height_zoom_btn.clicked.connect(self.on_zoom_mode_clicked)
        self.center_zoom_btn.clicked.connect(self.on_zoom_mode_clicked)

        self.plot_widget.zoom_mode = ZoomMode.WIDTH

        btn_layout.addSpacing(20)

        self.reset_btn = QPushButton("重置视图 (Home)")
        self.reset_btn.clicked.connect(self.reset_view)
        btn_layout.addWidget(self.reset_btn)

        self.save_btn = QPushButton("保存图片")
        self.save_btn.clicked.connect(self.save_image)
        btn_layout.addWidget(self.save_btn)

        btn_layout.addStretch()

        self.close_btn = QPushButton("关闭")
        self.close_btn.clicked.connect(self.close)
        btn_layout.addWidget(self.close_btn)

        layout.addLayout(btn_layout)
        self.setLayout(layout)

        self.hint_label = QLabel("提示：鼠标左键拖动平移 | 滚轮缩放 | 方向键平移 | +/- 缩放 | W/H/C 切换缩放模式")
        self.hint_label.setStyleSheet("color: gray; font-size: 12px;")
        btn_layout.addWidget(self.hint_label)

    def on_zoom_mode_clicked(self):
        """处理缩放模式按钮点击事件。

        实现按钮的手动互斥逻辑，并更新绘图控件的缩放模式。
        """
        clicked_btn = self.sender()

        for btn in self.zoom_buttons:
            if btn == clicked_btn:
                btn.setChecked(True)
            else:
                btn.setChecked(False)

        if self.width_zoom_btn.isChecked():
            self.plot_widget.zoom_mode = ZoomMode.WIDTH
            print("当前：宽度缩放")
        elif self.height_zoom_btn.isChecked():
            self.plot_widget.zoom_mode = ZoomMode.HEIGHT
            print("当前：高度缩放")
        elif self.center_zoom_btn.isChecked():
            self.plot_widget.zoom_mode = ZoomMode.CENTER
            print("当前：中心缩放")

    def set_zoom_mode(self, mode):
        """设置缩放模式（同步更新按钮状态）。

        Args:
            mode (int): 缩放模式，见 ZoomMode 类定义。

        Example:
            >>> window = WaveformWindow()
            >>> window.set_zoom_mode(ZoomMode.CENTER)
        """
        self.plot_widget.zoom_mode = mode

        if mode == ZoomMode.WIDTH:
            self.width_zoom_btn.setChecked(True)
            self.height_zoom_btn.setChecked(False)
            self.center_zoom_btn.setChecked(False)
        elif mode == ZoomMode.HEIGHT:
            self.width_zoom_btn.setChecked(False)
            self.height_zoom_btn.setChecked(True)
            self.center_zoom_btn.setChecked(False)
        elif mode == ZoomMode.CENTER:
            self.width_zoom_btn.setChecked(False)
            self.height_zoom_btn.setChecked(False)
            self.center_zoom_btn.setChecked(True)

    def reset_view(self):
        """重置视图为原始数据范围。

        Example:
            >>> window = WaveformWindow()
            >>> window.reset_view()
        """
        self.plot_widget.reset_view()

    def plot(self, voltage_data, start_idx, end_idx):
        """绘制电压波形图。

        对电压数据进行降采样处理后绘制波形图，
        X轴显示数据点序号范围。

        Args:
            voltage_data (array_like): 电压数据数组。
            start_idx (int): 起始数据点序号（从1开始）。
            end_idx (int): 结束数据点序号（从1开始）。

        Example:
            >>> window = WaveformWindow()
            >>> window.plot([0, 1, 2, 3, 4], 1, 5)
        """
        x_data = np.array(range(start_idx, end_idx + 1))
        y_data = np.array(voltage_data)

        x_data, y_data = decimate_data(x_data, y_data, max_points=5000)

        self.plot_widget.set_data(x_data, y_data)
        self.plot_widget.set_title(f"第 {start_idx} - 第 {end_idx} 个数据点")
        self.plot_widget.clear_vertical_line()

    def plot_spectrum(self, fundamental_volt_dict, flag_frep):
        """绘制频谱分析图。

        根据频率-电压字典数据绘制频谱图，并标记目标频率或峰值。

        Args:
            fundamental_volt_dict (dict): 频率数据字典，键为频率（Hz），
                值为包含 "volt" 和 "dbm" 的字典。
            flag_frep (int): 标记频率（Hz），若存在则标记该点，
                否则标记峰值点。

        Example:
            >>> data = {1000: {"volt": 1.0, "dbm": 10}, 2000: {"volt": 0.5, "dbm": 5}}
            >>> window = WaveformWindow()
            >>> window.plot_spectrum(data, 1000)
        """
        frequencies = sorted(fundamental_volt_dict.keys())
        dbm_values = [fundamental_volt_dict[f]["dbm"] for f in frequencies]
        voltage_values = [fundamental_volt_dict[f]["volt"] for f in frequencies]

        # 过滤非有限值（nan/inf），避免污染坐标 min/max 导致刻度显示 nan
        valid = [i for i, d in enumerate(dbm_values) if math.isfinite(d)]
        frequencies = [frequencies[i] for i in valid]
        dbm_values = [dbm_values[i] for i in valid]
        voltage_values = [voltage_values[i] for i in valid]

        if not frequencies or not dbm_values:
            QMessageBox.warning(self, "数据错误", "无有效频谱数据可绘制！")
            return

        frequencies = np.array(frequencies)
        dbm_values = np.array(dbm_values)

        self.plot_widget.set_data(frequencies, dbm_values)
        self.plot_widget.set_labels("频率 (Hz)", "功率幅值 (dBm)")
        self.plot_widget.set_title("频谱分析图")

        if flag_frep in fundamental_volt_dict:
            target_dbm = fundamental_volt_dict[flag_frep]["dbm"]
            target_volt = fundamental_volt_dict[flag_frep]["volt"]
            label = f"目标频率: {flag_frep} Hz\n幅值: {target_volt:.3f} V\n{target_dbm:.1f} dBm"
            self.plot_widget.set_vertical_line(flag_frep, QColor(255, 165, 0), label)
        else:
            peak_idx = np.argmax(dbm_values)
            flag_freq = frequencies[peak_idx]
            target_dbm = dbm_values[peak_idx]
            target_volt = voltage_values[peak_idx]
            label = f"峰值: {flag_freq} Hz\n幅值: {target_volt:.3f} V\n{target_dbm:.1f} dBm"
            self.plot_widget.set_vertical_line(flag_freq, QColor(255, 0, 0), label)

    def save_image(self):
        """保存当前绘图为图片文件。

        弹出文件保存对话框，将绘图控件内容保存为 PNG 图片。

        Example:
            >>> window = WaveformWindow()
            >>> window.save_image()
        """
        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存图片", "", "PNG Files (*.png);;All Files (*)"
        )
        if file_path:
            pixmap = self.plot_widget.grab()
            pixmap.save(file_path, "PNG")
            QMessageBox.information(self, "成功", "图片已保存！")

    def get_zoom_button_style(self):
        """获取缩放按钮的样式表。

        定义按钮在普通、悬停、选中状态下的外观样式。

        Returns:
            str: Qt 样式表字符串。

        Example:
            >>> window = WaveformWindow()
            >>> style = window.get_zoom_button_style()
        """
        return """
            QPushButton {
                background-color: #e0e0e0;
                border: 1px solid #a0a0a0;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 12px;
                color: #333333;
            }
            QPushButton:hover {
                background-color: #d0d0d0;
            }
            QPushButton:checked {
                background-color: #3498db;
                border: 1px solid #2980b9;
                color: white;
            }
            QPushButton:checked:hover {
                background-color: #2980b9;
            }
        """


class WaveformPlugin(QWidget):
    """波形分析插件主类。

    提供波形分析的主要功能界面，包括二进制文件解码、
    频率计算、FFT分析、波形显示和频谱分析等功能。

    Attributes:
        version (str): 插件版本号。
        comboBox_frep_1 (QComboBox): 频率选择下拉框。
        radio_group (QButtonGroup): 窗函数选择按钮组。
        textBrowser (QTextBrowser): 日志输出文本框。

    Example:
        >>> plugin = WaveformPlugin()
        >>> plugin.show()
    """

    def __init__(self):
        """初始化波形分析插件。

        加载 UI 界面，初始化控件，连接信号槽。
        """
        super().__init__()
        self.version = 'v3'
        ui_path = get_resource_path('main.ui')
        loadUi(ui_path, self)
        self.setWindowTitle(f'Waveform {self.version} by:zjx')

        self.comboBox_frep_1.addItems(["120000","210000","400000","300000","550000","500000","112000", "238000", "322000", "406000", "464000", "498000"])
        enable_drag_drop(self.textEdit_binPath)
        enable_drag_drop(self.textEdit_csvPath)

        self.radio_group = QButtonGroup(self)
        self.radio_group.setExclusive(True)
        self.radio_group.addButton(self.radioButton_window)
        self.radio_group.addButton(self.radioButton_flattop_window)
        self.radio_group.addButton(self.radioButton_hanning_window)
        self.radio_group.addButton(self.radioButton_blackman_harris_window)
        self.radioButton_flattop_window.setChecked(True)

        self.pushButton_bin.clicked.connect(self.analysis_bin)
        self.pushButton_csv.clicked.connect(self.analysis_csv)
        self.pushButton_time.clicked.connect(self.plot_voltage_range_waveform)
        self.pushButton_frep.clicked.connect(self.spectrum_diagram_waveform)
        self.pushButton_dbm_help.clicked.connect(self.show_dbm_help)

    def get_widget(self):
        """获取插件的主窗口控件。

        Returns:
            QWidget: 插件主窗口对象（即自身）。

        Example:
            >>> plugin = WaveformPlugin()
            >>> widget = plugin.get_widget()
        """
        return self

    def show_dbm_help(self):
        img_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dbm.png")
        if not os.path.exists(img_path):
            QMessageBox.warning(self, "提示", f"未找到dbm介绍图片：{img_path}")
            return

        original_pixmap = QPixmap(img_path)
        if original_pixmap.isNull():
            QMessageBox.warning(self, "提示", f"无法加载dbm介绍图片：{img_path}")
            return

        # 定义最大显示尺寸
        max_width = 900
        max_height = 700

        # 如果图片超过最大尺寸，则进行缩放
        if original_pixmap.width() > max_width or original_pixmap.height() > max_height:
            # scaled 保持宽高比 (Qt.KeepAspectRatio)，使用平滑变换 (Qt.SmoothTransformation)
            scaled_pixmap = original_pixmap.scaled(
                max_width, 
                max_height, 
                Qt.AspectRatioMode.KeepAspectRatio, 
                Qt.TransformationMode.SmoothTransformation
            )
        else:
            scaled_pixmap = original_pixmap

        dialog = QDialog(self)
        dialog.setWindowTitle("dbm计算逻辑介绍")
        
        label = QLabel()
        label.setPixmap(scaled_pixmap) # 显示缩放后的图片
        
        scroll_area = QtWidgets.QScrollArea(dialog)
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(label)
        
        layout = QVBoxLayout(dialog)
        layout.addWidget(scroll_area)
        
        # 对话框大小略大于图片，留出边距
        dialog.resize(scaled_pixmap.width() + 20, scaled_pixmap.height() + 20)
        dialog.exec()

    def get_name(self):
        """获取插件名称。

        Returns:
            str: 插件名称，包含版本号。

        Example:
            >>> plugin = WaveformPlugin()
            >>> print(plugin.get_name())
            Waveform v1
        """
        return f'Waveform {self.version}'

    def analysis_bin(self):
        """解析二进制文件并生成 CSV 文件。

        读取用户指定的二进制文件路径，验证文件格式后，
        调用解码函数将二进制数据转换为 CSV 格式的电压数据。

        Returns:
            bool: 成功返回 True，失败返回 False。

        Example:
            >>> plugin = WaveformPlugin()
            >>> plugin.textEdit_binPath.setPlainText("data.bin")
            >>> plugin.analysis_bin()
        """
        bin_path = self.textEdit_binPath.toPlainText()
        if not os.path.exists(bin_path):
            QMessageBox.critical(self, "错误", f"文件不存在：{bin_path}")
            return False

        if not bin_path.lower().endswith(".bin"):
            QMessageBox.critical(self, "错误", f"文件格式错误！\n请选择 .bin 格式文件")
            return False

        self.textBrowser.append("开始解析 Bin 文件======")
        try:
            DBM_gain = float(self.lineEdit_DBM_gain.text())
        except ValueError:
            self.show_message("错误", "衰减倍数获取失败")
            return
        # 能力1：bin 直接解码为单列电压幅值 CSV
        csv_path = fft_processor.generate_amplitude_csv(
            bin_path, os.path.splitext(bin_path)[0] + ".csv",
            gain=DBM_gain)
        self.textEdit_csvPath.setPlainText(csv_path)
        self.textBrowser.append(f'<font color="green">[成功]</font> 生成 CSV 文件：{csv_path}')



    def calculate_dbm(self, csv_path):
        """计算指定频率的 dBm 值。

        对 CSV 数据进行 FFT 分析，计算目标频率处的电压幅值
        和 dBm 值，并输出结果到日志窗口。

        Args:
            csv_path (str): CSV 文件路径。

        Example:
            >>> plugin = WaveformPlugin()
            >>> plugin.calculate_dbm("data.csv")
        """
        self.textBrowser.append("开始计算dbm")
        sample_rate = int(self.lineEdit_sample_rate.text())

        selected_radio = self.radio_group.checkedButton()
        if selected_radio:
            selected_text = selected_radio.text()
            if selected_text == "无窗":
                window_type = 0
            elif selected_text == "平定窗":
                window_type = 1
            elif selected_text == "汉宁窗":
                window_type = 2
            elif selected_text == "布莱克曼-哈里斯窗":
                window_type = 3
        try:
            load_impedance = float(self.lineEdit_impedance.text())
            cal_constant = float(self.lineEdit_cal_constant.text())
            gain = float(self.lineEdit_gain1.text())
            offset = float(self.lineEdit_offset.text())
        except ValueError:
            self.show_message("错误", "负载阻抗或校准常数或gain或offset有误")
            return

        target_freq = float(self.comboBox_frep_1.currentText())
        # 能力3：单频率查询（基频/该频率幅值/该频率dbm/THD/THD+N）
        try:
            info = fft_processor.get_frequency_info(
                csv_path, target_freq, sample_rate, window_type, gain,
                dbm_gain=gain, cal_constant=cal_constant, offset=offset)
        except RuntimeError as e:
            self.show_message("错误", f"FFT 分析失败：{e}")
            return
        fundamental_voltage = info["该频率电压幅值"]
        fundamental_freq = info["基频频率"]
        fundamental_rms = info["基频RMS"]
        dbm_value_1 = info["该频率dbm"]
        print(f"===============================================")
        print(f"对应 dBm 值：{dbm_value_1:.2f} dBm")
        print(f"对应 幅值：{fundamental_voltage:.2f} V")
        print(f"===============================================")

        self.textBrowser.append(f"FFT分析结果：")
        self.textBrowser.append(f"基频频率: {fundamental_freq:.9f} Hz")
        self.textBrowser.append(f"基频RMS: {fundamental_rms:.9f} V")
        self.textBrowser.append(f"计算频率: {target_freq:.9f} Hz")
        self.textBrowser.append(f"该频率电压幅值: {fundamental_voltage:.9f} V")
        self.textBrowser.append(f"gain: {gain:.9f}")
        self.textBrowser.append(f"offset: {offset:.9f}")
        if dbm_value_1 is not None:
            self.textBrowser.append(
                f"频率-dbm计算结果（负载阻抗{load_impedance}Ω）：{dbm_value_1:.9f} dBm")

    def analysis_csv(self):
        """解析 CSV 文件并执行完整分析。

        验证 CSV 文件路径后，依次执行频率计算和 dBm 计算。

        Returns:
            bool: 成功返回 True，失败返回 False。

        Example:
            >>> plugin = WaveformPlugin()
            >>> plugin.textEdit_csvPath.setPlainText("data.csv")
            >>> plugin.analysis_csv()
        """
        csv_path = self.textEdit_csvPath.toPlainText()
        if not os.path.exists(csv_path):
            QMessageBox.critical(self, "错误", f"文件不存在：{csv_path}")
            return False

        if not csv_path.lower().endswith(".csv"):
            QMessageBox.critical(self, "错误", f"文件格式错误！\n请选择 .csv 格式文件")
            return False

        self.textBrowser.append("\n=== 开始解析 csv 文件 ===\n")
        self.calculate_dbm(csv_path)

    def plot_voltage_range_waveform(self):
        """绘制指定范围内的电压波形图。

        从 CSV 文件读取数据，根据用户指定的起始和结束点
        绘制电压波形图，在新窗口中显示。

        Returns:
            bool: 成功返回 True，失败返回 False。

        Example:
            >>> plugin = WaveformPlugin()
            >>> plugin.plot_voltage_range_waveform()
        """
        csv_path = self.textEdit_csvPath.toPlainText()
        if not os.path.exists(csv_path):
            QMessageBox.critical(self, "错误", f"文件不存在：{csv_path}")
            return False

        if not csv_path.lower().endswith(".csv"):
            QMessageBox.critical(self, "错误", f"文件格式错误！\n请选择 .csv 格式文件")
            return False

        try:
            start_idx = int(self.lineEdit_start.text())
            end_idx = int(self.lineEdit_end.text())
        except ValueError:
            self.show_message("错误", "起始/结束点必须是整数！")
            return

        if start_idx < 1 or end_idx < 1:
            QMessageBox.warning(self, "输入错误", "起始点/结束点不能小于1！")
            return
        if start_idx >= end_idx:
            QMessageBox.warning(self, "输入错误", "起始点不能大于等于结束点！")
            return

        try:
            # 本地读取单列电压幅值 CSV（替代原 FFT.read_voltage_from_csv）
            voltage_data = []
            with open(csv_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            voltage_data.append(float(line))
                        except ValueError:
                            continue
            if not voltage_data:
                return

            total_data = len(voltage_data)
            print(f"读取到 {total_data} 个电压数据点")

            start = start_idx - 1
            end = end_idx - 1
            start = max(0, start)
            end = min(total_data - 1, end)
            actual_start = start + 1
            actual_end = end + 1

            filtered_voltage = voltage_data[start:end+1]
            print(f"筛选区间：第 {actual_start} - 第 {actual_end} 个数据，共 {len(filtered_voltage)} 个点")

        except FileNotFoundError:
            QMessageBox.critical(self, "文件错误", f"未找到CSV文件：{csv_path}")
            return
        except Exception as e:
            QMessageBox.critical(self, "处理错误", f"数据处理失败：{str(e)}")
            return

        self.waveform_window = WaveformWindow(self)
        self.waveform_window.plot(filtered_voltage, actual_start, actual_end)
        self.waveform_window.show()

    def show_message(self, title, content):
        """显示消息提示框。

        Args:
            title (str): 消息框标题。
            content (str): 消息内容。

        Example:
            >>> plugin = WaveformPlugin()
            >>> plugin.show_message("提示", "操作成功")
        """
        QMessageBox.information(self, title, content)

    def spectrum_diagram_waveform(self):
        """绘制频谱分析图。

        对 CSV 数据进行 FFT 分析，计算指定频率范围内的
        频谱数据，并在新窗口中绘制频谱图。

        Returns:
            bool: 成功返回 True，失败返回 False。

        Example:
            >>> plugin = WaveformPlugin()
            >>> plugin.spectrum_diagram_waveform()
        """
        csv_path = self.textEdit_csvPath.toPlainText()
        if not os.path.exists(csv_path):
            QMessageBox.critical(self, "错误", f"文件不存在：{csv_path}")
            return False

        if not csv_path.lower().endswith(".csv"):
            QMessageBox.critical(self, "错误", f"文件格式错误！\n请选择 .csv 格式文件")
            return False

        try:
            start_frep = int(self.lineEdit_start_frep.text())
            end_frep = int(self.lineEdit_end_frep.text())
            step_frep = int(self.lineEdit_step_frep.text())
            flag_frep = int(self.lineEdit_flag_frep.text())
            gain = float(self.lineEdit_gain1.text())
        except ValueError:
            self.show_message("错误", "频谱图的参数必须是整数！")
            return

        selected_radio = self.radio_group.checkedButton()
        if selected_radio:
            selected_text = selected_radio.text()
            if selected_text == "无窗":
                window_type = 0
            elif selected_text == "平定窗":
                window_type = 1
            elif selected_text == "汉宁窗":
                window_type = 2
            elif selected_text == "布莱克曼-哈里斯窗":
                window_type = 3

        try:
            load_impedance = float(self.lineEdit_impedance.text())
            cal_constant = float(self.lineEdit_cal_constant.text())
            gain = float(self.lineEdit_gain1.text())
            offset = float(self.lineEdit_offset.text())
        except ValueError:
            self.show_message("错误", "负载阻抗或校准常数或gain或offset有误")
            return

        sample_rate = int(self.lineEdit_sample_rate.text())

        # 能力2：按 start/step/end 生成 频率/幅值/dbm 三列 CSV
        spectrum_csv = os.path.join(PLUGIN_DIR, "spectrum_data.csv")
        try:
            fft_processor.generate_fft_csv(
                csv_path, spectrum_csv,
                start_frep, step_frep, end_frep,
                sample_rate, window_type, gain,
                dbm_gain=gain, cal_constant=cal_constant, offset=offset)
        except RuntimeError as e:
            self.show_message("错误", f"FFT 频谱生成失败：{e}")
            return

        # 读取三列 CSV，构建 {频率: {"volt": .., "dbm": ..}} 字典
        data_dict = {}
        with open(spectrum_csv, 'r', encoding='utf-8') as f:
            next(f)  # 跳过表头 frequency_hz,magnitude_v,dbm
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(",")
                if len(parts) != 3:
                    continue
                freq = int(float(parts[0]))
                volt = float(parts[1])
                dbm = float(parts[2])
                # 跳过无效数据点：旁瓣谷底插值可能产生负幅值，
                # 使 dbm 为 nan/inf，否则会污染坐标 min/max 导致刻度显示 nan
                if not (math.isfinite(volt) and math.isfinite(dbm)):
                    continue
                data_dict[freq] = {
                    "volt": volt,
                    "dbm": dbm,
                }
        if not data_dict:
            self.show_message("错误", "无有效频谱数据可绘制！")
            return

        self.textBrowser.append('<font color="green">[成功]</font> 频谱数据已生成')

        self.spectrum_window = WaveformWindow(self)
        self.spectrum_window.plot_spectrum(data_dict, flag_frep)
        self.spectrum_window.show()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = WaveformPlugin()
    window.show()
    sys.exit(app.exec())
