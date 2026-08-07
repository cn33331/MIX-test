# rsync_plugin 文件同步与获取工具

## 插件概述

rsync_plugin 是一个基于 SSH 和 rsync 的文件同步与获取工具，提供网络设备扫描、多设备文件同步推送、远程文件拉取、指令批量发送、VNC 远程连接等功能。基于 PyQt6 开发，采用模块化架构。

## 主要功能

### 1. 设备扫描

- **SSH 设备发现**：扫描指定 IP 范围，检测哪些设备可通过 SSH 连接
- **系统信息获取**：使用 `uname -a` 显示远程设备的系统名称和版本信息
- **多线程扫描**：支持 20 线程并发扫描，快速发现设备
- **IP 范围格式**：支持多种格式
  - 单个 IP：`10.8.30.14`
  - 范围：`10.8.30.14-23`
  - CIDR：`10.8.30.0/24`
  - 逗号分隔：`10.8.30.14,10.8.30.20`

### 2. VNC 远程连接

- **一键 VNC**：点击设备列表中的 VNC 按钮即可远程连接对应 IP
- **macOS 屏幕共享**：通过 `open vnc://IP` 启动系统自带的屏幕共享应用
- **vncloc 文件管理**：支持动态创建和管理 .vncloc 配置文件

### 3. 配置界面

- **SSH 配置**：用户名、密码、SSH 端口
- **扫描范围**：配置默认扫描的 IP 范围
- **同步路径**：保存推送和拉取的本地/远程路径
- **配置持久化**：所有配置自动保存到 JSON 文件

### 4. 多设备文件同步推送

- **批量推送**：选中多台设备，一键将本地文件夹同步到所有设备
- **rsync 增量同步**：使用 `rsync -avhz` 实现增量同步，高效传输
- **同步删除选项**：支持 `--delete` 选项，确保目标与源端完全一致
- **多线程并发**：最多 5 台设备同时同步

### 5. 远程文件拉取（单设备）

- **文件列表获取**：列出远程设备指定路径下的所有文件和目录
- **文件拉取**：将远程文件/目录拉取到本地指定路径
- **单设备操作**：拉取功能针对单台设备，适合获取日志等文件

### 6. 指令批量发送

- **多设备命令执行**：向选中的多台设备同时发送 SSH 命令
- **命令历史**：保存最近执行的命令，双击可快速重用
- **实时输出**：每台设备的返回结果实时显示在日志区域

## 文件结构

```
rsync_plugin/
├── rsync_plugin.py          # 主插件类（入口）
├── ssh_manager.py           # SSH管理模块（扫描、命令执行、文件列表）
├── rsync_manager.py         # Rsync管理模块（推送、拉取）
├── vnc_manager.py           # VNC连接管理模块
├── config_dialog.py         # 配置管理与配置对话框
├── readme.md                # 本文档
├── 参考/
│   ├── JSYNC-PUSH           # 参考脚本（expect，批量推送）
│   ├── JSYNC-GET_14         # 参考脚本（expect，批量拉取）
│   └── USSH_JQ02-3F-RD01_1_MLB-FCT.vncloc  # 参考vncloc文件
```

## 核心模块

### SSH管理模块 (`ssh_manager.py`)

负责所有 SSH 相关操作，使用 expect 包装 ssh 实现密码认证：

```python
class SSHManager:
    def __init__(username, password, port)
    def execute_command(ip, command, timeout) -> (code, stdout, stderr)
    def get_uname(ip, timeout) -> str
    def get_hostname(ip, timeout) -> str
    def check_ssh_available(ip, timeout) -> (bool, str)
    def list_remote_files(ip, remote_path, timeout) -> list
    def scan_network(ip_list, max_workers, progress_callback) -> list
```

**关键函数**：
- `parse_ip_range(ip_range_str)` - 解析多种 IP 范围格式
- `check_port_open(ip, port, timeout)` - 检测端口是否开放
- `check_expect()` - 检测 expect 是否安装（系统自带）

**密码认证机制**：
- 使用 expect 脚本包装 ssh 命令，自动处理密码输入
- 密码通过 `RSYNC_PWD` 环境变量传递给 expect 脚本，避免命令行转义问题
- 自动过滤 expect 输出中的 spawn 行和密码提示回显
- 透传 ssh 退出码（通过 `catch wait result; exit [lindex $result 3]`）

### Rsync管理模块 (`rsync_manager.py`)

负责文件同步操作，使用 expect 包装 rsync 实现密码认证：

```python
class RsyncManager:
    def __init__(username, password, port)
    def push_to_device(ip, local_path, remote_path, delete, callback) -> (code, output)
    def pull_from_device(ip, remote_path, local_path, delete, callback) -> (code, output)
    def push_to_multiple(ip_list, local_path, remote_path, delete, callback) -> dict
```

**同步策略**：
- 使用 `rsync -avhz` 归档模式、压缩传输、人类可读大小
- `--delete` 选项确保目标与源端内容一致
- 多设备并发推送，最大并发 5
- expect 脚本捕获 rsync 退出码并作为自身退出码返回

### VNC管理模块 (`vnc_manager.py`)

负责 VNC 远程桌面连接：

```python
class VNCManager:
    def __init__(vncloc_dir)
    def open_vnc(ip, port) -> bool
    def create_vncloc(ip, port, filename) -> str
    def open_vncloc(filepath) -> bool
    def open_vnc_by_ip(ip, port) -> bool
```

**工作原理**：
- macOS 上通过 `open vnc://IP` 启动屏幕共享应用
- 支持创建标准 .vncloc plist 文件

### 配置管理模块 (`config_dialog.py`)

负责配置持久化和配置界面：

```python
class RsyncConfig:
    def __init()
    def load() / save()
    def get(key, default) / set(key, value)
    def get_devices() / set_devices(devices)

class ConfigDialog(QDialog):
    # 配置对话框：用户名、密码、端口、扫描范围、同步路径
```

## 界面布局

采用紧凑垂直单列布局，适配低分辨率工控机（最小支持 800×480）：

```
┌──────────────────────────────────────────────────────────────────┐
│  Rsync-Sync v1.0 by:zjx                                           │
├──────────────────────────────────────────────────────────────────┤
│  扫描: [10.8.30.14-23    ] [扫描] [停止] [配置]      [▾日志]      │  ← 工具栏
│  ▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆  │  ← 进度条(4px)
├──────────────────────────────────────────────────────────────────┤
│  [推送][拉取][指令][部署]  | [全选][取消全选]        已选 3 台     │  ← 模式切换
├──────┬──────────────┬──────────────────┬──────────────────────────┤
│  选  │ IP地址        │ 主机名            │ VNC                      │  ← 设备表(4列)
│  ☑   │ 10.8.30.14   │ JQ02-3F-RD01     │ [VNC]                    │
│  ☑   │ 10.8.30.17   │ JQ02-3F-RD02     │ [VNC]                    │
│  ☑   │ 10.8.30.20   │ JQ02-3F-RD03     │ [VNC]                    │
├──────────────────────────────────────────────────────────────────┤
│  本地:[            ] […] 远程:[          ] ☐删除 [推送到已选]      │  ← 操作面板
├──────────────────────────────────────────────────────────────────┤
│  日志                                              [清空]         │
│  [10:23:15] 认证方式: expect                                       │  ← 可折叠
│  [在线] 10.8.30.14 - Darwin JQ02-3F-RD01 20.6.0 ...               │
└──────────────────────────────────────────────────────────────────┘
```

**布局特点**：
- 垂直单列，设备表占据主要区域，取消左右分割
- 设备表 4 列（删除冗余"状态"列，主机名仅显示 hostname，完整信息鼠标悬停查看）
- 操作面板使用模式按钮 + QStackedWidget 切换（推送/拉取/指令）
- 日志区可折叠（点击 ▾日志/▸日志 切换），默认 80px 高度
- 字体 9pt，间距 2px，按钮高度 22px，紧凑显示

## 使用方法

### 1. 环境依赖

无需额外安装，expect 为 macOS/Linux 系统自带工具：

```bash
# 验证 expect 是否可用（通常已自带）
which expect
# macOS: /usr/bin/expect
# Linux: /usr/bin/expect
```

### 2. 配置 SSH 连接

1. 点击"配置"按钮
2. 设置用户名、密码、SSH 端口
3. 设置扫描范围（如 `10.8.30.14-23`）
4. 配置同步路径（本地路径、远程路径）
5. 点击"确定"保存配置

### 3. 扫描设备

1. 在扫描范围输入框中输入 IP 范围
2. 点击"扫描"按钮
3. 等待扫描完成，可用设备将显示在设备列表中
4. 每台设备显示 IP、主机名（完整系统信息鼠标悬停查看）

### 4. VNC 远程连接

- 点击设备列表中的"VNC"按钮
- macOS 将自动打开屏幕共享应用连接到对应 IP

### 5. 文件同步推送

1. 点击"推送"模式按钮切换到推送面板
2. 设置本地路径和远程路径
3. 勾选"删除"（可选，确保目标与源端完全一致）
4. 在设备列表中选中目标设备
5. 点击"推送到已选"
6. 查看日志区域了解同步进度

### 6. 文件拉取

1. 点击"拉取"模式按钮切换到拉取面板
2. 从下拉框选择目标设备 IP
3. 输入远程路径
4. 点击"列出"查看远程文件列表
5. 设置本地保存路径
6. 点击"拉取到本地"

### 7. 指令发送

1. 点击"指令"模式按钮切换到指令面板
2. 在命令输入框中输入命令（如 `uname -a`、`hostname`、`ls /tmp`）
3. 在设备列表中选中目标设备
4. 点击"发送到已选"
5. 各设备的返回结果显示在日志区域

### 8. 部署（同步 + 指令序列）

部署模式实现"先同步文件，再执行指令序列"的完整部署工作流，参考 JSYNC-PUSH 脚本。

1. 点击"部署"模式按钮切换到部署面板
2. 设置本地路径和远程路径（用于 rsync 同步）
3. 勾选"删除"（可选，确保目标与源端完全一致）
4. 在"同步后指令"多行输入框中填写指令序列，每行一条：
   ```
   killall shTool
   open /vault/ZJX_backup/shTool.app/Contents/Resources/Tool/auto
   cp -r /vault/ZJX_backup/MIX-Tool/ /Users/gdlocal/.MIX-Tool/
   ln -s /vault/ZJX_backup/shTool/AtlasDataProcessorPlus.app ~/Desktop
   ```
   - 空行和以 `#` 开头的注释行会被自动忽略
   - 留空则仅执行同步
5. 在设备列表中选中目标设备
6. 点击"部署到已选"

**执行流程**：
- 阶段1：rsync 同步本地文件夹到所有已选设备（最多 5 台并发）
- 阶段2：对同步成功的设备，依次执行指令序列（某条失败则停止该设备后续指令）

## 技术特点

- **模块化架构**：SSH、Rsync、VNC、Config 各自独立模块，便于维护和扩展
- **expect 密码认证**：使用系统自带的 expect 包装 ssh/rsync，无需安装额外依赖
- **多线程并发**：扫描、同步、命令发送均使用多线程，UI 不阻塞
- **信号槽机制**：后台线程通过 PyQt 信号安全更新 UI
- **配置持久化**：所有配置自动保存到 JSON 文件
- **IP 范围解析**：支持单 IP、范围、CIDR、逗号分隔等多种格式
- **跨平台兼容**：VNC 模块支持 macOS 和 Linux
- **紧凑布局**：适配低分辨率工控机，最小支持 800×480

### 线程模型

```
┌─────────────────┐
│   主线程        │
│  (PyQt UI)      │
└────────┬────────┘
         │ PyQt Signals
    ┌────┼────┬────┬────┐
    ▼    ▼    ▼    ▼
  扫描  同步  拉取  命令
  线程  线程  线程  线程
   │     │    │    │
   ▼     ▼    ▼    ▼
  SSH  rsync rsync SSH
  expect expect expect expect
```

### expect 认证流程

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ Python 调用  │ ──▶ │ expect 脚本  │ ──▶ │ ssh / rsync  │
│ subprocess   │     │ (内联 -c)    │     │ (远端命令)    │
└──────────────┘     └──────┬───────┘     └──────┬───────┘
                            │                     │
                     RSYNC_PWD 环境变量      password: 提示
                     自动 send 密码          ◀── 自动响应
```

## 依赖项

- PyQt6 >= 6.0
- Python 3.8+
- expect（系统命令，macOS/Linux 系统自带，路径通常为 `/usr/bin/expect`）
- rsync（系统自带）
- ssh（系统自带）

## 参考文件说明

插件目录的 `参考/` 文件夹中包含以下参考文件（来自原始 expect 脚本，供开发参考）：

- `JSYNC-PUSH` - expect 脚本，批量 rsync 推送工具到多台电脑
- `JSYNC-GET_14` - expect 脚本，从远程设备拉取文件
- `USSH_JQ02-3F-RD01_1_MLB-FCT.vncloc` - macOS VNC 连接配置文件示例

## 注意事项

- 确保系统已安装 expect（macOS/Linux 通常自带，无需额外安装）
- 扫描范围过大时（如 /16 网络）会耗时较长
- 同步删除（--delete）会删除目标端多余文件，请谨慎使用
- 密码以明文形式存储在配置文件中，请注意安全
- 密码通过环境变量传递给 expect 脚本，不会出现在命令行参数中（避免进程列表泄露）
- VNC 功能在 macOS 上使用系统自带的屏幕共享应用

## 作者

zjx - Rsync文件同步工具 by zjx

## 版本历史

- v1.0: 初始版本，支持设备扫描、文件同步、文件拉取、指令发送、VNC连接
- v1.1: UI 紧凑化（适配低分辨率工控机）；认证方式由 sshpass 改为 expect（系统自带，零依赖）；新增「部署」模式（rsync同步+指令序列，参考 JSYNC-PUSH 工作流）
