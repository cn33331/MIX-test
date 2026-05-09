#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
主应用程序 - 支持动态插件加载（从文件夹加载）
"""

from PyQt6.QtWidgets import QMainWindow, QTabWidget, QApplication, QVBoxLayout, QWidget, QMenu, QMessageBox
from PyQt6.QtGui import QAction
from PyQt6.QtCore import Qt
import sys
import os
import importlib.util
import json


def get_resource_path(relative_path):
    """
    获取资源文件的绝对路径，支持打包后的应用
    """
    if hasattr(sys, '_MEIPASS'):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


def get_plugins_dir():
    """
    获取插件目录路径（plugins目录不打包进app，放在外部方便修改）
    """
    if hasattr(sys, '_MEIPASS'):
        # 打包后：从应用程序所在目录查找plugins文件夹
        # sys.executable 指向打包后的可执行文件路径
        app_dir = os.path.dirname(sys.executable)
        # plugins目录放在可执行文件同一目录下（MacOS目录）
        plugins_dir = os.path.join(app_dir, 'plugins')
        print(f"[插件目录] 打包模式，插件目录: {plugins_dir}")
        return plugins_dir
    else:
        # 开发环境：从源码目录查找
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'plugins')


class MainApplication(QMainWindow):
    """
    主应用程序类 - 支持动态加载插件（从文件夹加载）
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Tool by:zjx")
        self.setGeometry(100, 100, 800, 600)
        self.setMinimumSize(400, 300)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self.close_tab)
        main_layout = QVBoxLayout(central_widget)
        main_layout.addWidget(self.tab_widget)

        self.loaded_plugins = {}

        self.create_menu()
        self.load_plugins_from_config()

    def create_menu(self):
        """
        创建菜单
        """
        menu_bar = self.menuBar()

        plugin_menu = menu_bar.addMenu("插件")

        available_plugins = self.scan_plugins()
        for plugin_name, plugin_info in available_plugins.items():
            action = QAction(plugin_info['name'], self)
            action.triggered.connect(lambda checked, name=plugin_name: self.load_plugin(name))
            plugin_menu.addAction(action)

    def scan_plugins(self):
        """
        扫描插件目录，返回可用插件列表（从文件夹加载）
        """
        plugins = {}
        plugins_dir = get_plugins_dir()

        if not os.path.exists(plugins_dir):
            return plugins

        for item in os.listdir(plugins_dir):
            item_path = os.path.join(plugins_dir, item)
            if os.path.isdir(item_path):
                # 检查是否是插件目录（包含_plugin.py文件）
                plugin_py_files = [f for f in os.listdir(item_path) if f.endswith('_plugin.py')]
                if plugin_py_files:
                    plugin_name = item.replace('_plugin', '')
                    plugins[plugin_name] = {
                        'path': item_path,
                        'name': plugin_name.replace('_', ' ').title(),
                        'file': plugin_py_files[0]
                    }

        return plugins

    def load_plugin(self, plugin_name):
        """
        动态加载指定插件（从文件夹加载）
        """
        if plugin_name in self.loaded_plugins:
            for i in range(self.tab_widget.count()):
                if self.tab_widget.tabText(i) == self.loaded_plugins[plugin_name]['title']:
                    self.tab_widget.setCurrentIndex(i)
                    print(f"插件 {plugin_name} 已加载，切换到该标签页")
                    return
            return

        plugins_dir = get_plugins_dir()
        plugin_dir = os.path.join(plugins_dir, f'{plugin_name}_plugin')

        if not os.path.exists(plugin_dir):
            print(f"[插件加载失败] 插件目录不存在: {plugin_dir}")
            QMessageBox.warning(self, "插件未找到", f"插件 {plugin_name} 未找到")
            return

        # 查找插件文件
        plugin_files = [f for f in os.listdir(plugin_dir) if f.endswith('_plugin.py')]
        if not plugin_files:
            print(f"[插件加载失败] 插件目录中未找到插件文件: {plugin_dir}")
            QMessageBox.warning(self, "插件格式错误", f"插件 {plugin_name} 目录中未找到插件文件")
            return

        plugin_file = plugin_files[0]
        plugin_path = os.path.join(plugin_dir, plugin_file)

        print(f"[插件加载] 开始加载插件: {plugin_name}")
        print(f"[插件加载] 插件文件路径: {plugin_path}")

        try:
            # 添加插件目录到路径
            if plugin_dir not in sys.path:
                sys.path.insert(0, plugin_dir)

            spec = importlib.util.spec_from_file_location(plugin_name, plugin_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[plugin_name] = module
            spec.loader.exec_module(module)

            # 获取插件类（类名格式：MIXDebugPlugin, UARTDebugPlugin）
            # 将下划线分割的每个部分首字母大写后拼接（保持原有的大小写）
            parts = plugin_name.split('_')
            class_name = ''.join([part[0].upper() + part[1:] for part in parts]) + 'Plugin'
            if hasattr(module, class_name):
                plugin_class = getattr(module, class_name)
                plugin_instance = plugin_class()

                widget = plugin_instance.get_widget()

                title = plugin_instance.get_name()
                index = self.tab_widget.addTab(widget, title)
                self.tab_widget.setCurrentIndex(index)

                self.loaded_plugins[plugin_name] = {
                    'instance': plugin_instance,
                    'title': title,
                    'path': plugin_path
                }

                print(f"[插件加载成功] 插件: {plugin_name} ({title})")

            else:
                print(f"[插件加载失败] 插件 {plugin_name} 中未找到 {class_name} 类")
                QMessageBox.warning(self, "插件格式错误", f"插件 {plugin_name} 中未找到 {class_name} 类")

        except Exception as e:
            print(f"[插件加载失败] 插件: {plugin_name}, 错误: {str(e)}")
            QMessageBox.critical(self, "加载插件失败", f"加载插件 {plugin_name} 失败: {str(e)}")

    def load_plugins_from_config(self):
        """
        从配置文件加载插件列表
        """
        plugins_dir = get_plugins_dir()
        config_file = os.path.join(plugins_dir, 'plugins.json')

        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    plugins_to_load = config.get('plugins', [])
                    for plugin_name in plugins_to_load:
                        self.load_plugin(plugin_name)
            except Exception as e:
                QMessageBox.warning(self, "配置文件错误", f"读取插件配置失败: {str(e)}")
                self.load_default_plugins()
        else:
            self.load_default_plugins()

    def load_default_plugins(self):
        """
        加载默认插件
        """
        self.load_plugin('MIX_debug')

    def close_tab(self, index):
        """
        关闭标签页
        """
        title = self.tab_widget.tabText(index)
        widget = self.tab_widget.widget(index)
        self.tab_widget.removeTab(index)
        widget.deleteLater()

        for plugin_name, info in list(self.loaded_plugins.items()):
            if info['title'] == title:
                del self.loaded_plugins[plugin_name]
                break


if __name__ == "__main__":
    app = QApplication(sys.argv)
    main_app = MainApplication()
    main_app.show()
    sys.exit(app.exec())