import sys
import os
import csv
import importlib
import numpy as np
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QButtonGroup, QLineEdit, QLabel, QDialog, 
                             QSizePolicy, QCompleter, QMessageBox, QApplication,
                             QStylePainter, QStyleOptionFrame, QFileDialog)
from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import QPainter, QPen, QColor, QFont, QPolygonF

import FFT
import code_to_mvolt
from PyQt6.uic import loadUi

# 添加插件目录到路径
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PLUGIN_DIR)

def get_resource_path(relative_path):
    """
    获取资源文件的绝对路径（插件目录在外部，不从MEIPASS加载）
    """
    return os.path.join(PLUGIN_DIR, relative_path)


def load_external_file(file_name):
    """
    动态加载外部文件（可执行文件所在目录下的file_name）
    :param file_name: 要加载的外部文件名（如config.py）
    :return: 加载后的模块对象（可像正常import一样使用）
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
    """
    使给定的 QLineEdit 具有拖放功能。
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
    """
    数据降采样函数：将大数据集降采样到指定的最大点数
    使用LTTB算法（Largest Triangle Three Buckets）保持视觉特征
    """
    n = len(x)
    if n <= max_points:
        return x, y
    
    # 计算步长
    step = n / max_points
    result_x = []
    result_y = []
    
    # 添加第一个点
    result_x.append(x[0])
    result_y.append(y[0])
    
    for i in range(1, max_points - 1):
        # 当前桶的范围
        bucket_start = int((i - 1) * step)
        bucket_end = int(i * step)
        next_bucket_end = int((i + 1) * step)
        
        # 找到桶内的最大三角形面积点
        max_area = -1
        max_idx = bucket_start
        
        # 前一个点
        prev_x = result_x[-1]
        prev_y = result_y[-1]
        
        # 下一个桶的平均点（作为三角形的第三个点）
        next_avg_x = np.mean(x[min(bucket_end, n-1):min(next_bucket_end, n-1)])
        next_avg_y = np.mean(y[min(bucket_end, n-1):min(next_bucket_end, n-1)])
        
        for j in range(bucket_start, min(bucket_end, n-1)):
            # 计算三角形面积（使用简化公式，忽略1/2因子）
            area = abs((x[j] - prev_x) * (next_avg_y - prev_y) - 
                       (next_avg_x - prev_x) * (y[j] - prev_y))
            if area > max_area:
                max_area = area
                max_idx = j
        
        result_x.append(x[max_idx])
        result_y.append(y[max_idx])
    
    # 添加最后一个点
    result_x.append(x[-1])
    result_y.append(y[-1])
    
    return np.array(result_x), np.array(result_y)


class ZoomMode:
    WIDTH = 0      # 仅宽度缩放
    HEIGHT = 1     # 仅高度缩放
    CENTER = 2     # 中心缩放（默认）


class PlotWidget(QWidget):
    """轻量的绘图控件，使用QPainter绘制，支持平移和缩放"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.x_data = []
        self.y_data = []
        self.x_label = "X"
        self.y_label = "Y"
        self.title = ""
        self.axv_line = None  # (x, color, label)
        self.setMinimumSize(600, 400)
        self.setBackgroundRole(QtGui.QPalette.ColorRole.Base)
        self.setAutoFillBackground(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)  # 启用键盘焦点
        
        # 平移和缩放相关变量
        self.x_min_view = None
        self.x_max_view = None
        self.y_min_view = None
        self.y_max_view = None
        self.is_dragging = False
        self.last_pos = QPointF()
        self.setCursor(Qt.CursorShape.CrossCursor)
        
        # 缩放模式（默认使用宽度缩放）
        self.zoom_mode = ZoomMode.WIDTH
        
    def get_zoom_mode_name(self):
        """获取当前缩放模式名称"""
        if self.zoom_mode == ZoomMode.WIDTH:
            return "宽度缩放"
        elif self.zoom_mode == ZoomMode.HEIGHT:
            return "高度缩放"
        else:
            return "中心缩放"
        
    def set_data(self, x, y):
        self.x_data = np.array(x)
        self.y_data = np.array(y)
        # 初始化视图范围
        if len(self.x_data) > 0:
            self.x_min_view = np.min(self.x_data)
            self.x_max_view = np.max(self.x_data)
        if len(self.y_data) > 0:
            self.y_min_view = np.min(self.y_data)
            self.y_max_view = np.max(self.y_data)
        self.update()
        
    def set_labels(self, x_label, y_label):
        self.x_label = x_label
        self.y_label = y_label
        self.update()
        
    def set_title(self, title):
        self.title = title
        self.update()
        
    def set_vertical_line(self, x, color=QColor(255, 165, 0), label=""):
        self.axv_line = (x, color, label)
        self.update()
        
    def clear_vertical_line(self):
        self.axv_line = None
        self.update()
        
    def reset_view(self):
        """重置视图为原始数据范围"""
        if len(self.x_data) > 0:
            self.x_min_view = np.min(self.x_data)
            self.x_max_view = np.max(self.x_data)
        if len(self.y_data) > 0:
            self.y_min_view = np.min(self.y_data)
            self.y_max_view = np.max(self.y_data)
        self.update()
        
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_dragging = True
            self.last_pos = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            
    def mouseMoveEvent(self, event):
        if self.is_dragging and len(self.x_data) > 0:
            delta_x = event.position().x() - self.last_pos.x()
            delta_y = event.position().y() - self.last_pos.y()
            
            margin = 60
            plot_width = self.width() - 2 * margin
            plot_height = self.height() - 2 * margin
            
            # 计算平移量（转换为数据坐标）
            x_range = self.x_max_view - self.x_min_view
            y_range = self.y_max_view - self.y_min_view
            
            x_shift = -delta_x * x_range / plot_width
            y_shift = delta_y * y_range / plot_height
            
            # 更新视图范围
            self.x_min_view += x_shift
            self.x_max_view += x_shift
            self.y_min_view += y_shift
            self.y_max_view += y_shift
            
            self.last_pos = event.position()
            self.update()
            
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_dragging = False
            self.setCursor(Qt.CursorShape.CrossCursor)
            
    def wheelEvent(self, event):
        if len(self.x_data) == 0:
            return
            
        # 获取鼠标位置对应的坐标
        margin = 60
        x = event.position().x()
        y = event.position().y()
        
        # 计算鼠标位置对应的归一化坐标
        plot_width = self.width() - 2 * margin
        plot_height = self.height() - 2 * margin
        
        if plot_width <= 0 or plot_height <= 0:
            return
            
        norm_x = (x - margin) / plot_width
        norm_y = (y - margin) / plot_height
        
        # 限制在有效范围内
        norm_x = max(0.0, min(1.0, norm_x))
        norm_y = max(0.0, min(1.0, norm_y))
        
        # 计算鼠标位置对应的实际数据值
        x_center = self.x_min_view + norm_x * (self.x_max_view - self.x_min_view)
        y_center = self.y_min_view + (1 - norm_y) * (self.y_max_view - self.y_min_view)
        
        # 缩放因子
        zoom_factor = 0.9 if event.angleDelta().y() > 0 else 1.1
        
        # 根据缩放模式执行不同的缩放策略
        x_range = self.x_max_view - self.x_min_view
        y_range = self.y_max_view - self.y_min_view
        
        if self.zoom_mode == ZoomMode.WIDTH:
            # 仅宽度缩放
            new_x_range = x_range * zoom_factor
            x_ratio = (x_center - self.x_min_view) / x_range
            self.x_min_view = x_center - x_ratio * new_x_range
            self.x_max_view = self.x_min_view + new_x_range
            
        elif self.zoom_mode == ZoomMode.HEIGHT:
            # 仅高度缩放
            new_y_range = y_range * zoom_factor
            y_ratio = (y_center - self.y_min_view) / y_range
            self.y_min_view = y_center - y_ratio * new_y_range
            self.y_max_view = self.y_min_view + new_y_range
            
        else:
            # 中心缩放（默认）
            new_x_range = x_range * zoom_factor
            new_y_range = y_range * zoom_factor
            
            # 保持鼠标位置不变
            x_ratio = (x_center - self.x_min_view) / x_range
            self.x_min_view = x_center - x_ratio * new_x_range
            self.x_max_view = self.x_min_view + new_x_range
            
            y_ratio = (y_center - self.y_min_view) / y_range
            self.y_min_view = y_center - y_ratio * new_y_range
            self.y_max_view = self.y_min_view + new_y_range
        
        # 限制最小缩放范围
        min_x_range = (np.max(self.x_data) - np.min(self.x_data)) * 0.01
        min_y_range = (np.max(self.y_data) - np.min(self.y_data)) * 0.01
        
        if self.x_max_view - self.x_min_view < min_x_range:
            self.x_max_view = self.x_min_view + min_x_range
        if self.y_max_view - self.y_min_view < min_y_range:
            self.y_max_view = self.y_min_view + min_y_range
            
        self.update()
        
    def keyPressEvent(self, event):
        """键盘事件处理：快捷键支持"""
        if len(self.x_data) == 0:
            return
            
        zoom_factor = 0.8  # 键盘缩放因子
        
        if event.key() == Qt.Key.Key_Plus or event.key() == Qt.Key.Key_Equal:
            # 放大
            self.zoom(zoom_factor)
        elif event.key() == Qt.Key.Key_Minus or event.key() == Qt.Key.Key_Underscore:
            # 缩小
            self.zoom(1 / zoom_factor)
        elif event.key() == Qt.Key.Key_Left:
            # 向左平移
            self.pan(-0.1, 0)
        elif event.key() == Qt.Key.Key_Right:
            # 向右平移
            self.pan(0.1, 0)
        elif event.key() == Qt.Key.Key_Up:
            # 向上平移
            self.pan(0, 0.1)
        elif event.key() == Qt.Key.Key_Down:
            # 向下平移
            self.pan(0, -0.1)
        elif event.key() == Qt.Key.Key_Home:
            # 重置视图
            self.reset_view()
        elif event.key() == Qt.Key.Key_W:
            # 切换到宽度缩放模式
            self.zoom_mode = ZoomMode.WIDTH
            print(f"缩放模式已切换为：宽度缩放")
        elif event.key() == Qt.Key.Key_H:
            # 切换到高度缩放模式
            self.zoom_mode = ZoomMode.HEIGHT
            print(f"缩放模式已切换为：高度缩放")
        elif event.key() == Qt.Key.Key_C:
            # 切换到中心缩放模式
            self.zoom_mode = ZoomMode.CENTER
            print(f"缩放模式已切换为：中心缩放")
        else:
            super().keyPressEvent(event)
            
    def zoom(self, factor):
        """根据当前缩放模式进行缩放"""
        x_center = (self.x_min_view + self.x_max_view) / 2
        y_center = (self.y_min_view + self.y_max_view) / 2
        
        x_range = self.x_max_view - self.x_min_view
        y_range = self.y_max_view - self.y_min_view
        
        if self.zoom_mode == ZoomMode.WIDTH:
            # 仅宽度缩放
            new_x_range = x_range * factor
            self.x_min_view = x_center - new_x_range / 2
            self.x_max_view = x_center + new_x_range / 2
        elif self.zoom_mode == ZoomMode.HEIGHT:
            # 仅高度缩放
            new_y_range = y_range * factor
            self.y_min_view = y_center - new_y_range / 2
            self.y_max_view = y_center + new_y_range / 2
        else:
            # 中心缩放（同时缩放宽度和高度）
            new_x_range = x_range * factor
            new_y_range = y_range * factor
            self.x_min_view = x_center - new_x_range / 2
            self.x_max_view = x_center + new_x_range / 2
            self.y_min_view = y_center - new_y_range / 2
            self.y_max_view = y_center + new_y_range / 2
        
        self.update()
        
    def pan(self, dx_ratio, dy_ratio):
        """按比例平移视图"""
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
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # 边界留边距
        margin = 60
        plot_rect = QRectF(margin, margin, 
                          self.width() - 2 * margin, 
                          self.height() - 2 * margin)
        
        # 绘制标题
        if self.title:
            painter.setFont(QFont("Arial", 14, QFont.Weight.Bold))
            painter.drawText(QRectF(0, 0, self.width(), margin), 
                           Qt.AlignmentFlag.AlignCenter, self.title)
        
        # 没有数据直接返回
        if len(self.x_data) < 2:
            return
            
        # 使用视图范围
        x_min, x_max = self.x_min_view, self.x_max_view
        y_min, y_max = self.y_min_view, self.y_max_view
        
        # 确保范围有效
        x_range = x_max - x_min
        y_range = y_max - y_min
        if x_range == 0:
            x_range = 1
        if y_range == 0:
            y_range = 1
            
        # 绘制网格
        painter.setPen(QColor(200, 200, 200))
        for i in range(5):
            # 水平线
            y_pixel = plot_rect.top() + (i / 4.0) * plot_rect.height()
            painter.drawLine(QPointF(plot_rect.left(), y_pixel), 
                           QPointF(plot_rect.right(), y_pixel))
            # 垂直线
            x_pixel = plot_rect.left() + (i / 4.0) * plot_rect.width()
            painter.drawLine(QPointF(x_pixel, plot_rect.top()), 
                           QPointF(x_pixel, plot_rect.bottom()))
        
        # 绘制坐标轴
        painter.setPen(QColor(0, 0, 0))
        painter.drawLine(QPointF(plot_rect.left(), plot_rect.bottom()), 
                        QPointF(plot_rect.right(), plot_rect.bottom()))
        painter.drawLine(QPointF(plot_rect.left(), plot_rect.top()), 
                        QPointF(plot_rect.left(), plot_rect.bottom()))
        
        # 绘制轴线标签
        painter.setFont(QFont("Arial", 10))
        painter.drawText(QRectF(0, plot_rect.bottom(), plot_rect.left(), 30),
                        Qt.AlignmentFlag.AlignCenter, self.x_label)
        painter.save()
        painter.translate(15, plot_rect.center().y())
        painter.rotate(-90)
        painter.drawText(QRectF(-50, -15, 100, 30),
                        Qt.AlignmentFlag.AlignCenter, self.y_label)
        painter.restore()
        
        # 绘制刻度
        for i in range(5):
            x_val = x_min + (i / 4.0) * (x_max - x_min)
            x_pixel = plot_rect.left() + (i / 4.0) * plot_rect.width()
            painter.drawText(QPointF(x_pixel - 30, plot_rect.bottom() + 20),
                           self.format_number(x_val))
            
            y_val = y_max - (i / 4.0) * (y_max - y_min)
            y_pixel = plot_rect.top() + (i / 4.0) * plot_rect.height()
            painter.drawText(QPointF(5, y_pixel + 5),
                           self.format_number(y_val))
        
        # 绘制垂直线和数据曲线
        self.paintEventPart2(painter, plot_rect, x_min, x_max, y_min, y_max)
            
    def format_number(self, num):
        """格式化数字，避免科学计数法，显示完整数据"""
        if num == 0:
            return "0"
        
        # 根据数值大小选择合适的显示格式
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
        """绘制垂直线和数据曲线（分离出来避免代码过长）"""
        # 计算范围
        x_range = x_max - x_min
        y_range = y_max - y_min
        
        # 绘制垂直线（标记点）
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
        
        # 绘制数据曲线（降采样后绘制，提升性能）
        painter.setPen(QPen(QColor(30, 144, 255), 1.5))
        
        # 筛选在当前视图范围内的数据点
        mask = (self.x_data >= x_min - x_range * 0.1) & (self.x_data <= x_max + x_range * 0.1)
        visible_x = self.x_data[mask]
        visible_y = self.y_data[mask]
        
        # 降采样到合适的点数
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
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("波形图")
        self.setMinimumSize(1000, 600)
        
        layout = QVBoxLayout()
        self.plot_widget = PlotWidget()
        layout.addWidget(self.plot_widget, stretch=1)
        
        btn_layout = QHBoxLayout()
        
        # 缩放模式切换按钮 —— 【无 QButtonGroup，纯手动互斥，100% 可用】
        self.width_zoom_btn = QPushButton("宽度缩放 (W)")
        self.width_zoom_btn.setCheckable(True)
        self.width_zoom_btn.setChecked(True)  # 未选中
        self.width_zoom_btn.setStyleSheet(self.get_zoom_button_style())
        btn_layout.addWidget(self.width_zoom_btn)
        
        self.height_zoom_btn = QPushButton("高度缩放 (H)")
        self.height_zoom_btn.setCheckable(True)
        self.height_zoom_btn.setChecked(False)  # 默认选中
        self.height_zoom_btn.setStyleSheet(self.get_zoom_button_style())
        btn_layout.addWidget(self.height_zoom_btn)
        
        self.center_zoom_btn = QPushButton("中心缩放 (C)")
        self.center_zoom_btn.setCheckable(True)
        self.center_zoom_btn.setChecked(False)  # 未选中
        self.center_zoom_btn.setStyleSheet(self.get_zoom_button_style())
        btn_layout.addWidget(self.center_zoom_btn)
        
        # 把所有按钮放进列表，方便统一管理
        self.zoom_buttons = [
            self.width_zoom_btn,
            self.height_zoom_btn,
            self.center_zoom_btn
        ]
        
        # 绑定点击事件
        self.width_zoom_btn.clicked.connect(self.on_zoom_mode_clicked)
        self.height_zoom_btn.clicked.connect(self.on_zoom_mode_clicked)
        self.center_zoom_btn.clicked.connect(self.on_zoom_mode_clicked)
        
        # 确保 PlotWidget 的初始缩放模式与按钮状态一致
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
        
        # 添加提示标签
        self.hint_label = QLabel("提示：鼠标左键拖动平移 | 滚轮缩放 | 方向键平移 | +/- 缩放 | W/H/C 切换缩放模式")
        self.hint_label.setStyleSheet("color: gray; font-size: 12px;")
        btn_layout.addWidget(self.hint_label)
        
    def on_zoom_mode_clicked(self):
        """处理缩放模式按钮点击 —— 纯手动互斥"""
        # 点击谁，就只让它选中，其他全部取消
        clicked_btn = self.sender()
        
        for btn in self.zoom_buttons:
            if btn == clicked_btn:
                btn.setChecked(True)
            else:
                btn.setChecked(False)
        
        # 设置对应的缩放模式
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
        """设置缩放模式（通过快捷键调用）"""
        self.plot_widget.zoom_mode = mode
        
        # 更新按钮状态
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
        """重置视图为原始数据范围"""
        self.plot_widget.reset_view()
        
    def plot(self, voltage_data, start_idx, end_idx):
        # 降采样处理：500000个点太多，降采样到最大5000个点
        x_data = np.array(range(start_idx, end_idx + 1))
        y_data = np.array(voltage_data)
        
        # 降采样
        x_data, y_data = decimate_data(x_data, y_data, max_points=5000)
        
        self.plot_widget.set_data(x_data, y_data)
        # self.plot_widget.set_labels("数据点序号（1开始）", "电压值 (V)")
        self.plot_widget.set_title(f"第 {start_idx} - 第 {end_idx} 个数据点")
        self.plot_widget.clear_vertical_line()
        
    def plot_spectrum(self, fundamental_volt_dict, flag_frep):
        frequencies = sorted(fundamental_volt_dict.keys())
        dbm_values = [fundamental_volt_dict[f]["dbm"] for f in frequencies]
        voltage_values = [fundamental_volt_dict[f]["volt"] for f in frequencies]
        
        if not frequencies or not dbm_values:
            QMessageBox.warning(self, "数据错误", "无有效频谱数据可绘制！")
            return
            
        # 转换为numpy数组
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
        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存图片", "", "PNG Files (*.png);;All Files (*)"
        )
        if file_path:
            pixmap = self.plot_widget.grab()
            pixmap.save(file_path, "PNG")
            QMessageBox.information(self, "成功", "图片已保存！")
        
    def get_zoom_button_style(self):
        """获取缩放按钮的样式表，明确区分选中和未选中状态"""
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
    def __init__(self):
        super().__init__()
        self.version = 'v1'
        ui_path = get_resource_path('main.ui')
        loadUi(ui_path, self)
        self.setWindowTitle(f'Waveform {self.version} by:zjx')

        self.comboBox_frep_1.addItems(["112000", "238000", "322000", "406000", "464000", "498000"])
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

    def get_widget(self):
        return self

    def get_name(self):
        """
        返回插件名称
        """
        return f'Waveform {self.version}'

    def analysis_bin(self):
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
        csv_path = code_to_mvolt.decode_bin_to_csv(bin_path,DBM_gain)
        self.textEdit_csvPath.setPlainText(csv_path)
        self.textBrowser.append(f'<font color="green">[成功]</font> 生成 CSV 文件：{csv_path}')

    def calculate_frequency(self, csv_path):
        self.textBrowser.append("开始计算频率")
        referVolt = int(self.lineEdit_referVolt.text())
        intervalCount = int(self.lineEdit_intervalCount.text()) 
        _sampleRate = int(self.lineEdit_sample_rate.text())
        raw_data = []
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            for row in reader:
                raw_data.append(row)
        freq, end_collect_index, start_collect_index, period = code_to_mvolt.calculate_frequency(
            raw_data, referVolt, intervalCount, _sampleRate)
        self.textBrowser.append(f"frequency: {freq}")
        self.textBrowser.append(f"end_collect_index: {end_collect_index}")
        self.textBrowser.append(f"start_collect_index: {start_collect_index}")
        self.textBrowser.append(f"period: {period}")
        self.textBrowser.append(f"计算得到的频率：{freq}")

    def calculate_dbm(self, csv_path):
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
        except ValueError:
            self.show_message("错误", "负载阻抗或校准常数或gain有误")
            return

        selected_radio_vpp = "fixture"
        selected_radio_dbm = "fixture"
        if selected_radio_vpp == "apple":
            dbm_value_1, fundamental_voltage = FFT.get_dbm_by_frequency(
                csv_path, sample_rate, load_impedance, 
                float(self.comboBox_frep_1.currentText()), selected_radio_dbm)
        else:
            raw_voltage = FFT.read_voltage_from_csv(csv_path)
            fft_result = FFT.fft_analysis(
                raw_voltage, sample_rate, window_type, 
                float(self.comboBox_frep_1.currentText()))
            fundamental_voltage = fft_result["fundamental_voltage"]
            if selected_radio_dbm == "fixture":
                dbm_value_1 = FFT.voltage_to_dbm_Fixture(
                    fundamental_voltage, gain, load_impedance, cal_constant)
            else:
                dbm_value_1 = FFT.voltage_to_dbm_apple(
                    fundamental_voltage, gain, load_impedance, cal_constant)
            print(f"===============================================")
            print(selected_radio_dbm)
            print(f"对应 dBm 值：{dbm_value_1:.2f} dBm")
            print(f"对应 幅值：{fundamental_voltage:.2f} V")
            print(f"===============================================")

        self.textBrowser.append(f"FFT分析结果：")
        self.textBrowser.append(f"gain: {gain:.9f}")
        self.textBrowser.append(f"频率电压幅值: {fundamental_voltage:.9f} V")
        if dbm_value_1 is not None:
            self.textBrowser.append(
                f"频率-dbm计算结果（负载阻抗{load_impedance}Ω）：{dbm_value_1:.9f} dBm")

    def analysis_csv(self):
        csv_path = self.textEdit_csvPath.toPlainText()
        if not os.path.exists(csv_path):
            QMessageBox.critical(self, "错误", f"文件不存在：{csv_path}")
            return False

        if not csv_path.lower().endswith(".csv"):
            QMessageBox.critical(self, "错误", f"文件格式错误！\n请选择 .csv 格式文件")
            return False

        self.textBrowser.append("\n=== 开始解析 csv 文件 ===\n")
        self.calculate_frequency(csv_path)
        self.calculate_dbm(csv_path)

    def plot_voltage_range_waveform(self):
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
            voltage_data = FFT.read_voltage_from_csv(csv_path)
            if voltage_data is None:
                return

            total_data = len(voltage_data)
            print(f"读取到 {total_data} 个电压数据点")

            # 索引转换
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
        QMessageBox.information(self, title, content)

    def spectrum_diagram_waveform(self):
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
        except ValueError:
            self.show_message("错误", "负载阻抗或校准常数或gain有误")
            return

        sample_rate = int(self.lineEdit_sample_rate.text())

        selected_radio_vpp = "fixture"
        selected_radio_dbm = "fixture"

        # 直接导入 FFT 而不是加载外部文件
        data_dict = FFT.get_fundamental_volt(
            csv_path, sample_rate, window_type,
            start_frep, end_frep, step_frep,
            gain, load_impedance, cal_constant,
            selected_radio_vpp, selected_radio_dbm)
        if data_dict is None:
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
