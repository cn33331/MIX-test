# rsync_plugin 文件同步与部署工具

## 插件概述

rsync_plugin 是一个基于 SSH 和 rsync 的文件同步与部署工具，提供网络设备扫描、FinalShell 风格双栏文件管理器、多设备文件同步推送、远程文件拉取、交互式 SSH Shell、指令批量发送、一键自动部署、VNC 远程连接等功能。基于 PyQt6 开发，采用模块化架构，适配低分辨率工控机。

**版本**：v1.0

## 工作模式

插件提供两种工作模式，通过顶部模式按钮切换：

### 调试模式（index=0）

整合文件管理器与指令面板，适合日常设备调试：

- **上半部分**：FinalShell 风格双栏文件管理器（占主要空间）
- **下半部分**：交互式指令面板（命令行 + 历史列表 + 会话 CWD 显示）

### 一键自动部署（index=1，默认启动模式）

实现"扫描 → rsync 同步 → 指令序列执行"的完整部署流水线，支持 JSON 脚本加载/编辑/保存。

## 主要功能

### 1. 设备扫描

- **SSH 设备发现**：扫描指定 IP 范围，检测哪些设备可通过 SSH 连接
- **系统信息获取**：使用 `uname -a` 显示远程设备的系统名称和版本信息
- **主机名过滤**：支持按 hostname 关键字过滤扫描结果
- **多线程扫描**：支持 20 线程并发扫描，快速发现设备
- **IP 范围格式**：支持多种格式
  - 单个 IP：`10.8.30.14`
  - 范围：`10.8.30.14-23`
  - CIDR：`10.8.30.0/24`
  - 逗号分隔：`10.8.30.14,10.8.30.20`

### 2. FinalShell 风格文件管理器

双栏文件浏览器（`file_browser_panel.py`），左侧本地、右侧远程：

- **本地文件浏览**：使用 QFileSystemModel，显示名称/大小/类型/修改时间/权限
- **远程文件浏览**：通过 SSH 列出远程文件，同样表格展示
- **拖拽传输**：
  - 从 Finder 拖文件到远程面板 → 上传到远程当前目录
  - 从远程面板拖到本地面板 → 下载到本地当前目录
- **方向按钮**：→ 上传 / ← 下载 / 刷新 / 删除 / 新建文件夹
- **单通道串行传输**：所有 rsync 任务通过 TransferQueueManager 串行排队，同一时间只允许一个传输任务运行
- **删除同步选项**：支持 `--delete` 选项

### 3. 交互式 SSH Shell

基于 PTY 的交互式 Shell 会话（`ssh_manager.py` 中的 `InteractiveShell`）：

- **指令连续性**：所有命令通过同一 shell 会话发送，`cd` / `export` / `source` 等效果持续到后续命令
- **PTY 伪终端**：使用 `pty.fork()` 创建拥有 controlling TTY 的 SSH 子进程
- **命令标记**：通过特殊标记检测命令执行完成并提取返回码
- **会话缓存**：按设备 IP 缓存 shell 会话，文件管理器与指令面板共用同一连接

### 4. VNC 远程连接

- **一键 VNC**：点击设备列表中的 VNC 按钮即可远程连接对应 IP
- **macOS 屏幕共享**：通过 `open vnc://IP` 启动系统自带的屏幕共享应用
- **vncloc 文件管理**：支持动态创建和管理 .vncloc 配置文件

### 5. 配置管理

- **SSH 配置**：用户名、密码、SSH 端口
- **扫描范围**：配置默认扫描的 IP 范围
- **同步路径**：保存推送和拉取的本地/远程路径
- **三级配置加载**：代码兜底 → 模板默认（config.default.json）→ 实际配置（config.json）
- **配置持久化**：所有配置自动保存，随插件目录分发，打开即用

### 6. 多设备文件同步推送

- **批量推送**：选中多台设备，一键将本地文件夹同步到所有设备
- **rsync 增量同步**：使用 `rsync -avhz` 实现增量同步，高效传输
- **同步删除选项**：支持 `--delete` 选项，确保目标与源端完全一致
- **多线程并发**：最多 5 台设备同时同步

### 7. 远程文件拉取（单设备）

- **文件列表获取**：列出远程设备指定路径下的所有文件和目录
- **文件拉取**：将远程文件/目录拉取到本地指定路径
- **单设备操作**：拉取功能针对单台设备，适合获取日志等文件

### 8. 指令批量发送

- **多设备命令执行**：向选中的多台设备同时发送 SSH 命令
- **交互式会话**：每台设备使用独立的 InteractiveShell，保持指令连续性
- **命令历史**：保存最近执行的命令（最多 30 条），双击可快速重用
- **实时输出**：每台设备的返回结果实时显示在日志区域

### 9. 一键自动部署

实现"先同步文件，再执行指令序列"的完整部署工作流：

- **JSON 脚本管理**：支持加载/保存/另存/新建部署脚本
- **三步流水线**：
  1. **扫描目标设备**：支持自动扫描或手动指定 IP，可按 hostname 过滤
  2. **rsync 同步**：将本地文件夹同步到所有目标设备（最多 5 台并发）
  3. **指令序列执行**：对同步成功的设备依次执行指令（某条失败则停止该设备后续指令）
- **脚本格式**：JSON 文件，包含 SSH 凭据、目标设备配置、同步路径、指令列表

## 文件结构

```
rsync_plugin/
├── rsync_plugin.py           # 主插件类（入口，v1.0）
├── file_browser_panel.py     # FinalShell 风格双栏文件管理器
├── ssh_manager.py            # SSH 管理模块（扫描/命令/InteractiveShell）
├── rsync_manager.py          # Rsync 管理模块（推送/拉取）
├── vnc_manager.py            # VNC 连接管理模块
├── config_dialog.py          # 配置管理（继承 BaseJsonConfig）
├── config.default.json       # 模板默认配置（随插件分发）
├── config.json               # 实际配置（打开即用）
├── scripts/                  # 部署脚本目录
│   └── B632环境部署脚步.json #   B632 环境部署示例脚本
├── styles/                   # QSS 样式表目录
│   └── deploy_btn.qss        #   部署按钮样式（紫色，热重载）
├── vncloc/                   # VNC 连接文件目录
└── readme.md                 # 本文档
```

## 核心模块

### 主插件类 (`rsync_plugin.py`)

```python
class RsyncPlugin(QWidget):
    version = 'v1.0'
    # 两种工作模式：0=调试模式 1=一键自动部署
    # 调试模式：文件管理器 + 指令面板
    # 部署模式：脚本加载/编辑 → 三步流水线
```

**内置工作线程类**：

| 类名 | 职责 |
|------|------|
| `ScanWorker` | 后台扫描 IP 列表，通过信号通知进度和结果 |
| `SyncWorker` | 后台执行 rsync 推送，多设备并发 |
| `CommandWorker` | 通过 InteractiveShell 发送命令，保持指令连续性 |
| `LogWindow` | 独立日志窗口（置顶小窗口，可拖拽） |

### SSH 管理模块 (`ssh_manager.py`)

负责所有 SSH 相关操作，包含两个核心类：

```python
class InteractiveShell:
    """交互式 SSH Shell 会话 — PTY 伪终端，保持指令连续性"""
    def __init__(username, password, ip, port=22, connect_timeout=15)
    def send_command(command, timeout=30) -> (return_code, output)
    def close()

class SSHManager:
    """SSH 管理器 — 设备扫描、命令执行、文件列表"""
    def __init__(username, password, port)
    def execute_command(ip, command, timeout) -> (code, stdout, stderr)
    def get_uname(ip, timeout) -> str
    def check_ssh_available(ip, timeout) -> (bool, str)
    def list_remote_files(ip, remote_path, timeout) -> list
    def scan_network(ip_list, max_workers, progress_callback) -> list
```

**关键函数**：
- `parse_ip_range(ip_range_str)` — 解析多种 IP 范围格式
- `check_port_open(ip, port, timeout)` — 检测端口是否开放
- `check_expect()` — 检测 expect 是否安装

**密码认证机制**：
- `InteractiveShell`：使用 `pty.fork()` 创建 PTY 子进程，直接向 PTY 写入密码
- `SSHManager`：使用 expect 脚本包装 ssh，密码通过 `RSYNC_PWD` 环境变量传递

### 文件管理器面板 (`file_browser_panel.py`)

FinalShell 风格双栏文件管理器：

```python
class FinalShellFileBrowser(QWidget):
    """双栏文件浏览器 — 左本地 / 右远程，支持拖拽传输"""
    # 拖拽：Finder→远程面板=上传，远程面板→本地面板=下载
    # 传输：TransferQueueManager 串行排队，同一时间一个任务
```

**数据结构**：

```python
@dataclass
class FileEntry:
    """通用文件条目（本地/远程共用）"""
    name: str
    path: str            # 完整路径
    is_dir: bool
    size: int            # 字节
    mtime: str           # 修改时间
    perms: str           # 权限，例 drwxr-xr-x
    owner: str           # 所有者，例 root:root
```

### Rsync 管理模块 (`rsync_manager.py`)

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

### VNC 管理模块 (`vnc_manager.py`)

```python
class VNCManager:
    def __init__(vncloc_dir)
    def open_vnc(ip, port) -> bool
    def create_vncloc(ip, port, filename) -> str
    def open_vncloc(filepath) -> bool
    def open_vnc_by_ip(ip, port) -> bool
```

### 配置管理模块 (`config_dialog.py`)

继承通用基类 `utils.json_config.BaseJsonConfig`：

```python
class RsyncConfig(BaseJsonConfig):
    # 三级加载：代码兜底 → config.default.json → config.json
    def get_ssh_credentials() -> (username, password, port)
    def get_devices() / set_devices(devices)
    def get_command_history() / set_command_history(commands)  # 最多 30 条
```

**配置文件结构**（`config.default.json`）：

```json
{
  "ssh": { "username": "gdlocal", "password": "gdlocal", "port": 22 },
  "scan": { "range": "10.8.30.14-23" },
  "paths": {
    "deploy_script_path": "",
    "browser_local_path": "",
    "browser_remote_path": "/",
    "browser_target_ip": ""
  },
  "sync": { "push_delete": false, "pull_delete": false },
  "browser": { "delete_sync": false },
  "devices": [],
  "command_history": [],
  "ui": { "log_expanded": true, "last_mode": 1, "device_filter": "" }
}
```

## 部署脚本格式

部署脚本为 JSON 文件，存储在 `scripts/` 目录下：

```json
{
  "name": "B632环境部署脚步",
  "ssh": {
    "username": "gdlocal",
    "password": "gdlocal",
    "port": 22
  },
  "step1_targets": {
    "mode": "scan",              // "scan" 自动扫描 | "manual" 手动指定
    "ip_range": "10.8.30.1-100",
    "manual_ips": "10.8.30.16",
    "hostname_filter": "FCT"     // 按 hostname 过滤
  },
  "step2_push": {
    "local_path": "/Users/gdadmin/Documents/ZJX/ZJX_backup",
    "remote_path": "/vault/ZJX_backup",
    "delete": true
  },
  "step3_commands": [
    "killall shTool",
    "open /vault/ZJX_backup/shTool.app/Contents/Resources/Tool/auto",
    "cp -r /vault/ZJX_backup/MIX-Tool/ /Users/gdlocal/.MIX-Tool/",
    "ln -s /vault/ZJX_backup/shTool/AtlasDataProcessorPlus.app ~/Desktop"
  ]
}
```

| 字段 | 说明 |
|------|------|
| `step1_targets.mode` | `scan` 扫描 IP 范围 / `manual` 手动指定 IP |
| `step1_targets.hostname_filter` | 按 hostname 关键字过滤（如 `FCT`） |
| `step2_push.delete` | 是否删除目标端多余文件（`--delete`） |
| `step3_commands` | 指令序列，空行和 `#` 开头的注释行自动忽略 |

## 界面布局

采用紧凑垂直单列布局，适配低分辨率工控机（最小支持 800×480）：

```
┌──────────────────────────────────────────────────────────────────┐
│  Rsync-Sync v1.0 by:zjx                                           │
├──────────────────────────────────────────────────────────────────┤
│  扫描: [10.8.30.14-23    ] [扫描] [停止] [配置]      [▾日志]      │  ← 工具栏
│  ▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆  │  ← 进度条(4px)
├──────────────────────────────────────────────────────────────────┤
│  [○调试模式] [●一键自动部署]  | [全选][取消全选]     已选 3 台    │  ← 模式切换
├──────┬──────────────┬──────────────────┬──────────────────────────┤
│  选  │ IP地址        │ 主机名            │ VNC                      │  ← 设备表(4列)
│  ☑   │ 10.8.30.14   │ JQ02-3F-RD01     │ [VNC]                    │
│  ☑   │ 10.8.30.17   │ JQ02-3F-RD02     │ [VNC]                    │
├──────────────────────────────────────────────────────────────────┤
│  ═══════════ 调试模式：文件管理器 + 指令面板 ═══════════          │
│  ┌─────────────────┬─────────────────┐                          │
│  │  本地文件浏览器  │  远程文件浏览器  │  ← 拖拽传输               │
│  │                 │                 │                          │
│  └─────────────────┴─────────────────┘                          │
│  命令: [cd /tmp 再 ls — 目录保持          ] [发送]               │
│  历史命令列表                                                     │
├──────────────────────────────────────────────────────────────────┤
│  或                                                                │
│  ═══════════ 一键自动部署：脚本加载 → 三步流水线 ═══════════      │
│  部署脚本: B632环境部署脚步    [加载][保存][另存为][新建]         │
│  SSH: [gdlocal] [****] [22]  目标: ○扫描 ●手动 [10.8.30.16]     │
│  同步: [本地路径] → [远程路径] ☐删除                             │
│  指令序列:                                                        │
│    killall shTool                                                 │
│    open /vault/ZJX_backup/...                                     │
│                                            [部署到已选]           │
├──────────────────────────────────────────────────────────────────┤
│  日志（独立窗口）                                    [清空]       │
└──────────────────────────────────────────────────────────────────┘
```

**布局特点**：
- 垂直单列，设备表占据主要区域
- 模式按钮使用 QStackedWidget 切换（调试模式 / 一键自动部署）
- 调试模式内含上下 QSplitter（文件管理器占 4/5，指令面板占 1/5）
- 字体 9pt，间距 2px，按钮高度 22px，紧凑显示
- 日志支持独立窗口模式（置顶小窗口，可拖拽）

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

### 4. 调试模式 — 文件管理器

1. 切换到"调试模式"
2. 在设备列表中选中一台目标设备
3. 左侧浏览本地文件，右侧浏览远程文件
4. 拖拽文件进行上传/下载，或使用方向按钮

### 5. 调试模式 — 交互式指令

1. 在设备列表中选中目标设备
2. 在命令输入框中输入命令（如 `cd /tmp`）
3. 按回车或点击"发送"
4. 后续命令在同一 shell 会话中执行，`cd` 等效果保持

### 6. VNC 远程连接

- 点击设备列表中的"VNC"按钮
- macOS 将自动打开屏幕共享应用连接到对应 IP

### 7. 文件同步推送

1. 在设备列表中选中目标设备
2. 设置本地路径和远程路径
3. 勾选"删除"（可选，确保目标与源端完全一致）
4. 点击"推送到已选"
5. 查看日志区域了解同步进度

### 8. 一键自动部署

1. 切换到"一键自动部署"模式
2. 点击"加载"选择部署脚本 JSON 文件（或直接在界面编辑）
3. 配置 SSH 凭据、目标设备、同步路径、指令序列
4. 在设备列表中选中目标设备（或使用脚本中的扫描配置）
5. 点击"部署到已选"

**执行流程**：
- 阶段 1：扫描目标设备（自动扫描或手动指定）
- 阶段 2：rsync 同步本地文件夹到所有目标设备（最多 5 台并发）
- 阶段 3：对同步成功的设备，依次执行指令序列（某条失败则停止该设备后续指令）

## 技术特点

- **双模式架构**：调试模式（文件管理器+交互式Shell）与部署模式（脚本化流水线）切换
- **FinalShell 风格文件管理器**：双栏拖拽传输，本地/远程统一交互
- **InteractiveShell PTY 会话**：指令连续性保持，`cd`/`export`/`source` 效果持续
- **expect 密码认证**：使用系统自带的 expect 包装 ssh/rsync，无需安装额外依赖
- **模块化架构**：SSH、Rsync、VNC、Config、FileBrowser 各自独立模块
- **多线程并发**：扫描、同步、命令发送均使用多线程，UI 不阻塞
- **信号槽机制**：后台线程通过 PyQt 信号安全更新 UI
- **三级配置加载**：代码兜底 → 模板默认 → 实际配置，深度合并补全缺失字段
- **QSS 热重载**：样式表抽离为 .qss 文件，保存即生效（通过 StyleSheetManager）
- **部署脚本持久化**：JSON 格式脚本，支持加载/保存/另存/新建
- **IP 范围解析**：支持单 IP、范围、CIDR、逗号分隔等多种格式
- **紧凑布局**：适配低分辨率工控机，最小支持 800×480

### 线程模型

```
┌─────────────────┐
│   主线程        │
│  (PyQt UI)      │
└────────┬────────┘
         │ PyQt Signals
    ┌────┼────┬────┬────┬────┐
    ▼    ▼    ▼    ▼    ▼
  扫描  同步  拉取  命令  部署
  线程  线程  线程  线程  线程
   │     │    │    │    │
   ▼     ▼    ▼    ▼    ▼
  SSH  rsync rsync Shell rsync+Shell
 expect expect expect PTY  expect+PTY
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

### InteractiveShell PTY 认证流程

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ Python       │ ──▶ │ pty.fork()   │ ──▶ │ ssh 进程     │
│ (主线程)     │     │ (子进程拥有  │     │ (controlling │
│              │     │  controlling │     │  TTY)        │
│              │     │  TTY)        │     │              │
└──────────────┘     └──────────────┘     └──────────────┘
      │                                           │
      │──── 写入密码到 PTY master ──────────────▶│
      │──── 写入命令到 PTY master ──────────────▶│
      │◀── 读取 PTY master 获取输出 ─────────────│
```

## 依赖项

- PyQt6 >= 6.0
- Python 3.8+
- expect（系统命令，macOS/Linux 系统自带，路径通常为 `/usr/bin/expect`）
- rsync（系统自带）
- ssh（系统自带）
- pty（Python 标准库，打包补丁位于 `plugins/libs/pty.py`）

## QSS 样式表

插件使用 StyleSheetManager 管理 QSS 样式表，支持热重载：

| 文件 | 用途 |
|------|------|
| `styles/deploy_btn.qss` | 部署按钮样式（紫色，突出"一键部署"语义） |

样式文件保存后 UI 立即生效，无需重启应用。用户自定义样式保存在 `~/.MIX-Tool/styles/` 目录。

## 注意事项

- 确保系统已安装 expect（macOS/Linux 通常自带，无需额外安装）
- 扫描范围过大时（如 /16 网络）会耗时较长
- 同步删除（--delete）会删除目标端多余文件，请谨慎使用
- 密码以明文形式存储在配置文件中，请注意安全
- 密码通过环境变量传递给 expect 脚本，不会出现在命令行参数中（避免进程列表泄露）
- InteractiveShell 使用 PTY 伪终端，每台设备独立会话，关闭插件时自动清理
- VNC 功能在 macOS 上使用系统自带的屏幕共享应用
- 文件管理器传输任务串行排队，同一时间只允许一个传输任务运行

## 作者

zjx - Rsync文件同步工具 by zjx

## 版本历史

- v1.0: 初始版本，支持设备扫描、文件同步、文件拉取、指令发送、VNC连接
  - 双模式架构：调试模式（FinalShell 风格文件管理器 + 交互式 Shell）+ 一键自动部署
  - 认证方式由 sshpass 改为 expect（系统自带，零依赖）
  - InteractiveShell 基于 PTY，保持指令连续性
  - 部署脚本 JSON 持久化，支持加载/保存/另存/新建
  - QSS 样式表热重载
  - UI 紧凑化，适配低分辨率工控机
