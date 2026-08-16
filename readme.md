# MIX 自动化测试平台

## 项目简介

MIX 自动化测试平台是一个基于插件化架构的通用测试工具集，专为工业自动化测试场景设计。平台采用 Python 和 PyQt6 构建，提供模块化的插件管理系统，支持多协议通信、数据采集、信号分析、远程文件同步与部署等功能。

### 核心特性

- **插件化架构**：采用标准插件接口，支持动态加载和卸载功能模块
- **多协议支持**：内置 MIX_2.0、TCP、UART 等常用工业通信协议
- **可视化分析**：集成波形显示和 FFT 频谱分析功能（支持 C 加速）
- **远程部署**：基于 SSH/rsync 的多设备文件同步、指令执行与一键部署
- **自动化测试**：支持指令序列编辑和批量执行
- **QSS 热重载**：样式表抽离为独立 .qss 文件，保存即生效，无需重启
- **跨平台运行**：基于 Python 开发，支持 Windows、macOS、Linux 系统

## 系统架构

### 架构分层图

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                            应用层 (Application Layer)                          │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                        main_application.py                              │  │
│  │              插件管理器 · 标签页切换 · 菜单栏                            │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
├──────────────────────────────────────────────────────────────────────────────┤
│                              插件层 (Plugin Layer)                             │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌──────────┐ │
│  │ MIX_debug  │ │ TCP_debug  │ │ UART_debug │ │ Waveform   │ │ Rsync    │ │
│  │   插件     │ │   插件     │ │   插件     │ │   插件     │ │  插件    │ │
│  └────────────┘ └────────────┘ └────────────┘ └────────────┘ └──────────┘ │
├──────────────────────────────────────────────────────────────────────────────┤
│                          公共工具层 (Utils Layer)                              │
│  ┌──────────────┐ ┌──────────────┐ ┌────────────────┐ ┌──────────────────┐ │
│  │ config.py    │ │ logger.py    │ │ json_config.py │ │stylesheet_manager│ │
│  │ 配置管理     │ │ 日志管理     │ │  配置基类      │ │  QSS 热重载      │ │
│  └──────────────┘ └──────────────┘ └────────────────┘ └──────────────────┘ │
├──────────────────────────────────────────────────────────────────────────────┤
│                           系统依赖层 (System Layer)                            │
│  ┌──────────┐ ┌────────┐ ┌──────┐ ┌─────────┐ ┌──────┐ ┌────────────────┐ │
│  │  PyQt6   │ │ pyzmq  │ │numpy │ │  scipy  │ │serial│ │ expect/ssh/rsync│ │
│  └──────────┘ └────────┘ └──────┘ └─────────┘ └──────┘ └────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 模块说明

| 层级 | 模块 | 说明 |
|------|------|------|
| **应用层** | main_application.py | 主应用程序入口，负责插件加载、标签页管理和全局事件处理 |
| **插件层** | plugins/* | 功能插件目录，每个子目录为一个独立插件 |
| **工具层** | plugins/utils/* | 公共工具模块，提供配置管理、日志记录、JSON 配置基类和 QSS 样式热重载 |
| **系统补丁** | plugins/libs/* | 打包后可能缺失的标准库补丁（如 pty.py，供 pexpect/expect 依赖） |

### 插件接口规范

所有插件必须实现以下接口方法：

```python
class BasePlugin:
    def get_widget(self) -> QWidget:
        """返回插件的主窗口部件"""
        pass

    def get_name(self) -> str:
        """返回插件名称（含版本号，如 'MIX_debug v4'）"""
        pass
```

**插件类名约定**：目录名去掉 `_plugin` 后缀，按 `_` 分割后每段首字母大写拼接，再加 `Plugin`。
例如 `MIX_debug_plugin` → `MIXDebugPlugin`，`TCP_debug_plugin` → `TCPDebugPlugin`。

## 插件概览

| 插件 | 版本 | 功能定位 | 默认加载 |
|------|------|----------|----------|
| [MIX_debug](plugins/MIX_debug_plugin/readme.md) | v4 | MIX 设备 RPC 调试 | 是 |
| [TCP_debug](plugins/TCP_debug_plugin/readme.md) | v1.1 | TCP 网络调试（服务器+客户端） | 否 |
| [UART_debug](plugins/UART_debug_plugin/readme.md) | v1.0 | 串口通信调试 | 否 |
| [Waveform](plugins/Waveform_plugin/readme.md) | v3 | 信号波形与 FFT 频谱分析 | 是 |
| [Rsync](plugins/rsync_plugin/readme.md) | v1.0 | 远程文件同步与一键部署 | 是 |
| [Qt-Study](plugins/qt_study_plugin/readme.md) | v1.0 | 插件框架学习示例 | 否 |

## 快速开始

### 1. 环境准备

```bash
# 激活虚拟环境
cd /Users/gdlocal/Desktop/myCode/myAPP/MIX-test
source /Users/gdlocal/Desktop/env_sum/vis/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 2. 运行主应用

```bash
# 运行主应用程序（自动加载 plugins.json 中配置的插件）
python3 main_application.py
```

### 3. 插件加载机制

主应用程序启动后：
1. 扫描 `plugins/` 目录下所有含 `*_plugin.py` 文件的子目录
2. 读取 `plugins/plugins.json` 中配置的插件列表，自动加载
3. 在菜单栏「插件」菜单中列出所有可用插件，可手动加载未自动加载的插件

## 插件开发指南

### 创建新插件

1. 在 `plugins/` 目录下创建新文件夹，命名为 `xxx_plugin`
2. 创建主插件文件 `xxx_plugin.py`，类名约定为 `XxxPlugin`
3. 实现 `get_widget()` 和 `get_name()` 接口
4. （可选）创建 Qt Designer 界面文件（.ui）
5. 在 `plugins/plugins.json` 中注册插件名称以实现自动加载

### 插件示例

```python
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel

class MyPlugin(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.version = 'v1.0'
        layout = QVBoxLayout()
        layout.addWidget(QLabel("我的插件"))
        self.setLayout(layout)

    def get_widget(self):
        return self

    def get_name(self):
        return f'MyPlugin {self.version}'
```

### 使用公共工具模块

插件可通过 `from utils.xxx import ...` 引用公共工具：

```python
# 配置管理（继承三级加载体系）
from utils.json_config import BaseJsonConfig

# 日志系统
from utils.logger import init_logger
logger = init_logger(name="MyPlugin", log_file="my_plugin.log")

# QSS 样式表热重载
from utils.stylesheet_manager import StyleSheetManager
```

## 配置文件说明

### 插件配置（plugins/plugins.json）

定义主应用启动时自动加载的插件列表：

```json
{
    "plugins": ["rsync", "Waveform", "MIX_debug"]
}
```

> 注意：列表中的名称为插件目录名去掉 `_plugin` 后缀的部分。

### 用户配置

用户配置存储在 `~/.MIX-Tool/` 目录下（Windows 为 `%APPDATA%/MIX-Tool/`）：

| 文件/目录 | 说明 |
|-----------|------|
| `config.json` | 通道配置和历史记录 |
| `commands_info.json` | 命令信息缓存 |
| `logs/` | 日志文件目录（超过 1MB 自动轮转） |
| `styles/` | 用户自定义 QSS 样式表（优先级高于出厂样式） |

### 三级配置加载体系

各插件的配置管理继承 `utils.json_config.BaseJsonConfig`，采用三级加载优先级：

1. **代码内嵌兜底默认值** — 保证最小可用
2. **模板默认配置文件**（如 `config.default.json`）— 随插件分发
3. **实际配置文件**（如 `config.json`）— 深度合并补全缺失字段后生效

## 依赖项

### 核心依赖

| 依赖 | 版本 | 用途 |
|------|------|------|
| Python | >= 3.8 | 运行环境 |
| PyQt6 | 6.4.2 | GUI 框架 |
| pyzmq | 25.1.2 | ZeroMQ 通信（MIX_debug 插件） |
| pyserial | 3.5 | 串口通信（UART_debug 插件） |
| numpy | >= 2.0.0 | 数值计算（Waveform 插件） |
| scipy | 1.11.4 | FFT 计算（Waveform 插件） |
| ujson | 5.9.0 | 高性能 JSON 解析 |

### 插件额外依赖

| 插件 | 额外依赖 |
|------|----------|
| MIX_debug | pyzmq |
| TCP_debug | - |
| UART_debug | pyserial |
| Waveform | numpy, scipy |
| Rsync | expect, ssh, rsync（系统自带） |

完整依赖列表见 `requirements.txt`。

## 构建与打包

### 使用 PyInstaller 打包

```bash
# 打包主应用（含自动复制 plugins 目录到 app 包）
pyinstaller Automation-Platform.spec
```

打包配置（`Automation-Platform.spec`）的关键行为：
- 打包后自动将 `plugins/` 目录复制到 `.app/Contents/MacOS/plugins/`
- `plugins/libs/` 中的标准库补丁通过 `sys.path` 优先加载
- 插件目录不打包进 MEIPASS，保持外部可修改

## 相关文档

- [MIX_debug_plugin 详细文档](plugins/MIX_debug_plugin/readme.md)
- [MIX_2.0 RPC 协议注册机制详解](plugins/MIX_debug_plugin/mix/readme.md)
- [TCP_debug_plugin 详细文档](plugins/TCP_debug_plugin/readme.md)
- [UART_debug_plugin 详细文档](plugins/UART_debug_plugin/readme.md)
- [Waveform_plugin 详细文档](plugins/Waveform_plugin/readme.md)
- [rsync_plugin 详细文档](plugins/rsync_plugin/readme.md)
- [qt_study_plugin 详细文档](plugins/qt_study_plugin/readme.md)

## 注意事项

1. **运行环境**：请确保已激活正确的虚拟环境
2. **插件路径**：插件目录在外部（`plugins/`），不从 MEIPASS 加载，打包后仍可修改
3. **配置文件**：用户配置保存在用户主目录的 `.MIX-Tool` 文件夹中
4. **串口权限**：Linux 系统可能需要添加用户到 dialout 组
5. **expect 依赖**：Rsync 插件依赖系统自带的 expect（macOS/Linux 通常已预装）
6. **C 加速**：Waveform 插件的 `fft_processor` 为 C 编译的可执行文件，缺失时回退到 scipy

## 版本信息

- 平台版本：2.0
- Python 版本：3.8+
- PyQt 版本：6.4.2
