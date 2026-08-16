# qt_study_plugin Qt 学习插件

## 插件概述

qt_study_plugin 是一个极简的插件框架示例，用于学习 MIX 自动化测试平台的插件开发接口。包含一个按钮组件，点击后显示消息提示，演示了插件的最小实现方式。

**版本**：v1.0

## 主要功能

- **按钮交互演示**：点击按钮后显示状态文字
- **插件接口示例**：展示 `get_widget()` 和 `get_name()` 的最小实现

## 文件结构

```
qt_study_plugin/
├── qt_study_plugin.py      # 主插件类（极简单文件）
└── readme.md               # 本文档
```

## 核心代码

```python
class QtStudyPlugin(QWidget):
    def __init__(self):
        super().__init__()
        self.version = 'v1.0'
        self.init_ui()

    def get_widget(self):
        return self

    def get_name(self):
        return f'Qt-Study {self.version}'
```

## 使用方法

1. 在主应用菜单栏「插件」菜单中选择「Qt Study」
2. 插件加载后显示在标签页中
3. 点击"点击我"按钮，下方显示状态文字

## 开发说明

本插件作为新插件开发的起点模板：

1. 复制 `qt_study_plugin/` 目录并重命名
2. 修改类名（遵循 `XxxPlugin` 命名约定）
3. 在 `init_ui()` 中构建自己的界面
4. 实现 `get_widget()` 返回主部件
5. 实现 `get_name()` 返回插件名称（含版本号）

## 依赖项

- PyQt6 >= 6.0

## 作者

zjx

## 版本历史

- v1.0: 初始版本，极简框架示例
