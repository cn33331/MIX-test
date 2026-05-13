# MIX自动化测试平台

## 项目简介

MIX自动化测试平台是一个基于插件化架构的通用测试工具集，专为工业自动化测试场景设计。平台采用Python和PyQt6构建，提供模块化的插件管理系统，支持多协议通信、数据采集、信号分析等功能。

### 核心特性

- **插件化架构**：采用标准插件接口，支持动态加载和卸载功能模块
- **多协议支持**：内置MIX_2.0、TCP、UART等常用工业通信协议
- **可视化分析**：集成波形显示和频谱分析功能
- **自动化测试**：支持指令序列编辑和批量执行
- **跨平台运行**：基于Python开发，支持Windows、macOS、Linux系统

## 系统架构

### 架构分层图

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              应用层 (Application Layer)                          │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │                           main_application.py                              │    │
│  │                         插件管理器 · 标签页切换                             │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
├─────────────────────────────────────────────────────────────────────────────────┤
│                               插件层 (Plugin Layer)                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ MIX_debug    │  │  TCP_debug   │  │ UART_debug   │  │ Waveform     │      │
│  │   插件        │  │    插件       │  │    插件       │  │   插件        │      │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘      │
├─────────────────────────────────────────────────────────────────────────────────┤
│                               工具层 (Utils Layer)                              │
│  ┌──────────────────────────────┐  ┌──────────────────────────────────────┐    │
│  │         config.py            │  │              logger.py                │    │
│  │        配置管理               │  │             日志管理                   │    │
│  └──────────────────────────────┘  └──────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 模块说明

| 层级 | 模块 | 说明 |
|------|------|------|
| **应用层** | main_application.py | 主应用程序入口，负责插件加载、标签页管理和全局事件处理 |
| **插件层** | plugins/* | 功能插件目录，每个子目录为一个独立插件 |
| **工具层** | utils/* | 公共工具模块，提供配置管理和日志记录功能 |

### 插件接口规范

所有插件必须实现以下接口方法：

```python
class BasePlugin:
    def get_widget(self) -> QWidget:
        """返回插件的主窗口部件"""
        pass
    
    def get_name(self) -> str:
        """返回插件名称"""
        pass
```

## 插件概览

### MIX_debug 插件

**功能定位**：MIX设备调试工具，用于连接和控制MIX系列设备。

**主要功能**：

- 多通道设备连接管理
- RPC命令发送与响应接收
- 命令自动提示和文档显示
- 指令序列编辑与批量执行

**详细文档**：[plugins/MIX_debug_plugin/readme.md](plugins/MIX_debug_plugin/readme.md)

### TCP_debug 插件

**功能定位**：TCP网络调试工具，支持TCP服务器和客户端模式。

**主要功能**：

- TCP服务器模式（支持多客户端）
- TCP客户端模式
- 双向数据收发
- 实时通信日志

**详细文档**：[plugins/TCP_debug_plugin/readme.md](plugins/TCP_debug_plugin/readme.md)

### UART_debug 插件

**功能定位**：串口通信调试工具，用于串口设备调试。

**主要功能**：

- 串口扫描与选择
- 串口参数配置
- 数据收发与显示
- 自动重连机制

**详细文档**：[plugins/UART_debug_plugin/readme.md](plugins/UART_debug_plugin/readme.md)

### Waveform 插件

**功能定位**：信号分析工具，用于波形和频谱分析。

**主要功能**：

- 二进制数据解析（Bin文件）
- CSV数据读取分析
- FFT频谱计算
- 波形可视化显示

**详细文档**：[plugins/Waveform_plugin/readme.md](plugins/Waveform_plugin/readme.md)

## 项目结构

```
MIX-test/
├── main_application.py       # 主应用程序入口
├── main.py                  # 独立运行入口（MIX-debug）
│
├── plugins/                  # 插件目录
│   ├── plugins.json         # 插件配置文件
│   ├── MIX_debug_plugin/    # MIX调试插件
│   │   ├── MIX_debug_plugin.py
│   │   ├── MIX_debug_plugin.ui
│   │   ├── rpc_client.py
│   │   ├── mix/
│   │   │   ├── mix8_rpc_client.py
│   │   │   └── mix8_rpc_server.py
│   │   └── readme.md
│   │
│   ├── TCP_debug_plugin/    # TCP调试插件
│   │   ├── TCP_debug_plugin.py
│   │   └── readme.md
│   │
│   ├── UART_debug_plugin/   # 串口调试插件
│   │   ├── UART_debug_plugin.py
│   │   ├── UART_debug_plugin.ui
│   │   ├── uart_manager.py
│   │   ├── uart/
│   │   │   └── uart_debug_Virtual.py
│   │   └── readme.md
│   │
│   └── Waveform_plugin/     # 波形分析插件
│       ├── Waveform_plugin.py
│       ├── FFT.py
│       ├── code_to_mvolt.py
│       ├── ui/
│       │   ├── main.py
│       │   └── main.ui
│       └── readme.md
│
├── utils/                   # 公共工具
│   ├── config.py           # 配置管理
│   └── logger.py           # 日志管理
│
├── static/                  # 静态资源
│   └── sword.icns          # 应用图标
│
└── readme.md               # 项目说明文档
```

## 快速开始

### 1. 环境准备

```bash
# 激活虚拟环境
cd /Users/gdlocal/Desktop/myCode/myAPP/MIX-test
source /Users/gdlocal/Desktop/env_sum/vis/bin/activate
```

### 2. 运行主应用

```bash
# 运行主应用程序（支持插件集成）
python3 main_application.py

# 或直接运行MIX-debug插件
python3 main.py
```

### 3. 加载插件

主应用程序启动后会自动扫描 `plugins` 目录下的插件，并在标签页中显示。

## 插件开发指南

### 创建新插件

1. 在 `plugins` 目录下创建新文件夹
2. 创建主插件类，实现 `get_widget()` 和 `get_name()` 接口
3. 创建Qt Designer界面文件（.ui）
4. 在 `plugins.json` 中注册插件（可选）

### 插件示例

```python
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel

class MyPlugin(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout()
        layout.addWidget(QLabel("我的插件"))
        self.setLayout(layout)
    
    def get_widget(self):
        return self
    
    def get_name(self):
        return "我的插件 v1.0"
```

## 配置文件说明

### 插件配置（plugins.json）

定义插件的加载顺序和基本属性：

```json
{
    "plugins": [
        {
            "name": "MIX_debug",
            "enabled": true
        },
        {
            "name": "TCP_debug",
            "enabled": true
        }
    ]
}
```

### 用户配置

用户配置存储在 `~/.MIX-Tool/` 目录下：

- `config.json` - 通道配置和历史记录
- `commands_info.json` - 命令信息缓存
- `logs/` - 日志文件目录

## 依赖项

### 核心依赖

- Python >= 3.8
- PyQt6 >= 6.0

### 插件依赖

| 插件 | 额外依赖 |
|------|---------|
| MIX_debug | pyzmq |
| TCP_debug | - |
| UART_debug | pyserial |
| Waveform | numpy, scipy |

完整依赖列表见 `requirements.txt`。

## 构建与打包

### 安装依赖

```bash
pip install -r requirements.txt
```

### 使用PyInstaller打包

```bash
# 打包主应用
pyinstaller main_application.spec

# 打包独立版本
pyinstaller -F main.py
```

### CI/CD构建

项目使用GitHub Actions进行自动化构建，构建配置见 `.github/workflows/build.yml`。

## 相关文档

- [MIX_debug_plugin 详细文档](plugins/MIX_debug_plugin/readme.md)
- [TCP_debug_plugin 详细文档](plugins/TCP_debug_plugin/readme.md)
- [UART_debug_plugin 详细文档](plugins/UART_debug_plugin/readme.md)
- [Waveform_plugin 详细文档](plugins/Waveform_plugin/readme.md)

## 注意事项

1. **运行环境**：请确保已激活正确的虚拟环境
2. **插件路径**：插件目录在外部，不从MEIPASS加载
3. **配置文件**：用户配置保存在用户主目录的 `.MIX-Tool` 文件夹中
4. **串口权限**：Linux系统可能需要添加用户到dialout组

## 版本信息

- 平台版本：2.0
- Python版本：3.8+
- PyQt版本：6.0+
