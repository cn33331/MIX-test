# 注意事项
1. 运行环境

   ```
   cd /Users/gdlocal/Desktop/myCode/myAPP/MIX-test
   source /Users/gdlocal/Desktop/env_sum/vis/bin/activate
   python3 main_application.py  # 运行主应用
   # 或
   python3 main.py  # 直接运行MIX-debug
   ```

2. ui转文件

   ```
   pyuic6 /Users/gdlocal/Desktop/myCode/monitoring_fail/ui/main.ui -o /Users/gdlocal/Desktop/myCode/monitoring_fail/ui/main.py
   ```

3. 文件打包

   ```
   pyinstaller -F /Users/gdlocal/Desktop/myCode/myAPP/MIX-test/main.py
   pyinstaller /Users/gdlocal/Desktop/myCode/myAPP/MIX-test/main.spec

   ```

# 项目介绍
自动化任务管理平台是一个用于控制和测试设备的GUI应用，采用插件化架构，支持多通道管理、RPC通信、命令自动提示和文档显示等功能。

## 项目功能
1. **主应用**：提供插件化架构，支持多插件集成和管理
   - 标签页管理：支持多个插件的切换和管理
   - 统一布局：提供一致的用户界面体验
   - 可扩展性：易于添加新的插件和功能

2. **MIX-debug插件**：用于控制和测试MIX8设备
   - 通道配置：
     - 支持多个通道的管理，每个通道可以配置IP、端口等参数
     - 通过按钮点击开始连接或取消连接
     - 通道连接状态显示
     - 对当前已连接的通道同步发送指令
   - 命令提示和文档：
     - 连接通道时自动从MIX8设备获取所有命令信息
     - 命令输入时会显示匹配的命令提示，支持点击选择
     - 选中命令后会显示该命令的详细说明和参数信息
   - 指令序列：
     - 支持创建、保存和执行指令序列
     - 支持延迟和暂停操作
     - 支持序列组的保存和加载
   - 日志和历史记录：
     - 实时显示操作日志和设备响应
     - 记录已发送的命令，支持快速重复执行

3. **串口调试插件**：用于串口设备的调试和通信
   - 串口扫描和选择：自动扫描系统中可用的串口
   - 手动输入串口地址：支持输入自定义串口路径
   - 波特率配置：可调整波特率设置
   - 实时数据收发：支持双向串口通信
   - 数据显示和日志记录：实时显示串口数据和操作日志

## 项目文档结构

   ```
MIX-test/
├── main.py                  # MIX-debug独立运行入口
├── main_application.py       # 主应用程序入口，支持插件集成
├── core/                    # 核心业务层
│   ├── cmd_manager.py       # 指令管理，处理命令的执行和参数管理
│   ├── rpc_client.py        # RPC客户端封装，处理与设备的通信
│   └── uart_manager.py      # 串口管理核心模块，处理串口通信
├── ui/                      # UI界面层
│   ├── main_window.py       # MIX-debug插件主窗口逻辑
│   ├── main_window.ui       # MIX-debug UI设计文件，定义界面布局
│   ├── uart_plugin.py       # 串口调试插件主窗口逻辑
│   └── uart_plugin.ui       # 串口调试插件UI设计文件
├── uart/                    # 串口相关工具
│   ├── uart_debug.py        # 串口调试工具
│   └── uart_debug_Virtual.py # 虚拟串口创建工具，支持自动写入功能
├── mix8/                    # RPC通信相关代码
│   └── mix8_rpc_client.py   # MIX8 RPC客户端
├── utils/                   # 工具模块
│   ├── config.py            # 配置管理
│   └── logger.py            # 日志管理
└── README.md                # 项目说明（功能、环境、运行步骤）
   ```

## 主界面

主应用程序 `main_application.py` 提供了一个基于标签页的主界面，用于管理和集成多个功能插件。

### 运行方式

```bash
# 激活虚拟环境
source /Users/gdlocal/Desktop/env_sum/vis/bin/activate

# 运行主应用
python3 main_application.py
```

### 功能特点

- **插件管理**：通过标签页切换不同的功能插件
- **统一风格**：所有插件采用一致的界面风格
- **可扩展性**：易于添加新的插件模块
- **多任务支持**：可以同时运行多个插件，处理不同的任务

## MIX-debug 插件

MIX-debug 是一个用于管理和控制 MIX 设备的插件，集成了完整的 RPC 通信和设备管理功能。

### 插件功能

- **通道管理**：添加、编辑和管理设备通道
- **RPC 通信**：发送 RPC 命令到 MIX 设备
- **指令序列**：创建和执行指令序列
- **日志显示**：实时显示操作日志和设备响应
- **历史记录**：管理已发送的命令历史

### UI 界面组件结构

| 组件名称 | 关联文件 | 功能说明 |
|---------|---------|--------|
| MainWindow | ui/main_window.py | MIX-debug插件主窗口类，包含所有UI组件，管理整体布局和事件处理 |
| ip_table | ui/main_window.py | 通道列表表格，显示和管理通道信息，支持多选、双击编辑和自动保存 |
| cmd_input | ui/main_window.py | 命令输入框，用于输入RPC命令，支持QCompleter自动提示 |
| cmd_info_text | ui/main_window.py | 命令信息显示，显示选中命令的详细说明和参数，设置了最大高度 |
| param_input | ui/main_window.py | 命令和参数输入框，cmd_input选择命令后按回车会显示命令，然后手动添加参数，作为最终发送的完整命令 |
| send_cmd_button | ui/main_window.py | 发送按钮，发送param_input中的完整命令和参数到所有已连接通道 |
| log_text | ui/main_window.py | 日志显示，显示应用运行日志和操作结果，支持右键菜单清空所有内容 |
| history_list | ui/main_window.py | 历史指令列表，显示已发送的命令，双击可直接再次发送，右击可选择删除、添加到序列或清空所有内容 |
| sequence_list | ui/main_window.py | 指令序列列表，显示添加的指令、延迟和暂停，每一行有勾选框（默认勾选），取消勾选时不执行该指令，支持按顺序执行，右击可选择修改、删除、添加延迟、添加暂停、清空序列、保存序列组、加载序列组或打开序列组原始文件 |
| execute_sequence_btn | ui/main_window.py | 执行序列按钮，按照序列列表的顺序执行指令、延迟和暂停 |

### 右键菜单功能

| 组件 | 右键菜单功能 |
|------|------------|
| 通道列表 | 新增一行、配置通道、批量连接、批量断开 |
| 日志显示 | 清空所有内容 |
| 历史指令 | 清空所有内容、添加到序列、删除 |
| 序列列表 | 添加延迟、添加暂停、清空序列、保存序列组、加载序列组、打开序列组原始文件、修改、删除 |

# 构建项目
### 1. 在 GitHub 上启用 Actions
1. 访问你的 GitHub 仓库
2. 点击 Actions 标签
3. 点击 I understand my workflows, go ahead and enable them
### 2. 手动触发构建
1. 进入 Actions 标签
2. 选择 Build Automation-Platform workflow
3. 点击 Run workflow
4. 选择 main 分支
### 3. 下载构建产物
构建完成后：

- macos-13 runner 生成 Intel x86_64 版本
- macos-14 runner 生成 Apple Silicon ARM64 版本
在 Actions 标签的 Artifacts 部分可以下载构建产物。