#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Qt学习插件 - 极简框架示例
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLabel
from PyQt6.QtCore import Qt

class QtStudyPlugin(QWidget):
    """
    Qt学习插件 - 极简框架示例
    
    包含一个按钮组件，点击后显示消息提示。
    """
    
    def __init__(self):
        super().__init__()
        self.version = 'v1.0'
        self.setWindowTitle(f'Qt-Study {self.version}')
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        label = QLabel('Qt学习插件')
        label.setStyleSheet('font-size: 18px; font-weight: bold; color: #333;')
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.click_btn = QPushButton('点击我')
        self.click_btn.setStyleSheet(
            'QPushButton { padding: 12px 32px; font-size: 16px; }'
        )
        self.click_btn.clicked.connect(self.on_button_click)
        
        self.status_label = QLabel('')
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet('color: #666; margin-top: 10px;')
        
        layout.addWidget(label)
        layout.addWidget(self.click_btn)
        layout.addWidget(self.status_label)
    
    def on_button_click(self):
        self.status_label.setText('按钮被点击了！')
    
    def get_widget(self):
        return self
    
    def get_name(self):
        return f'Qt-Study {self.version}'
