# MIX_debug_plugin MIX设备调试插件

## 插件概述

MIX_debug_plugin 是一个功能完整的MIX设备调试工具，提供多通道RPC通信管理、命令自动提示、指令序列执行等功能。基于PyQt6开发，支持MIX_2.0协议。

## 主要功能

### 1. 通道管理

- **多通道配置**：支持同时管理多个MIX设备连接（最多24个通道）
- **批量操作**：支持批量连接和断开选中通道
- **配置导入导出**：自动保存和加载通道配置
- **智能IP生成**：支持自动生成设备IP地址（基于槽位号）

### 2. RPC通信

- **MIX_2.0协议支持**：完整支持MIX_2.0 RPC通信协议
- **ZeroMQ传输**：基于ZeroMQ DEALER-ROUTER模式
- **自动注册机制**：客户端自动注册到服务器，支持重试机制（最多3次）
- **命令自动发现**：连接时自动获取设备支持的所有命令

### 3. 命令提示系统

- **智能提示**：输入命令时自动显示匹配的命令列表
- **命令文档**：显示命令的详细说明和参数信息
- **参数类型识别**：支持识别扩展参数格式

### 4. 指令序列

- **序列编辑**：支持创建包含指令、延迟、暂停的复杂序列
- **序列组管理**：支持保存和加载序列组到CSV文件
- **执行控制**：支持勾选控制执行项，可随时暂停
- **循环执行**：支持设置循环次数

### 5. 日志系统

- **实时日志**：显示所有操作和设备响应
- **历史记录**：保存已发送的命令历史
- **右键菜单**：支持清空、添加、删除等操作

## 文件结构

```
MIX_debug_plugin/
├── MIX_debug_plugin.py      # 主插件类 (v4)
├── MIX_debug_plugin.ui      # Qt Designer 界面文件
├── rpc_client.py            # RPC 客户端封装
├── mix/                     # MIX 协议实现
│   ├── mix8_rpc_client.py   #   MIX8 RPC 客户端（ZeroMQ DEALER）
│   ├── mix8_rpc_server.py   #   模拟 RPC 服务器（开发测试用）
│   ├── mix8_rpc_server.sh   #   服务器启动脚本（自动关闭端口占用）
│   └── readme.md            #   MIX_2.0 RPC 协议注册机制详解
└── readme.md                # 本文档
```

## 核心模块

### RPC客户端 (`rpc_client.py`)

RPC客户端封装类，负责与MIX设备通信：

- 连接管理：建立和关闭与设备的连接
- 服务发现：获取设备支持的服务列表
- 命令发送：发送RPC命令到设备
- 错误处理：健壮的异常处理机制

主要方法：

```python
class RpcClient:
    def __init__(self, ip, port, log_callback=None)
    def connect() -> bool
    def list_remote_services() -> list
    def send_command(service_name, method_name, *args, **kwargs)
    def get_all_commands() -> dict
    def close()
```

### MIX8 RPC客户端 (`mix/mix8_rpc_client.py`)

MIX8 RPC通信实现，遵循MIX_2.0协议：

- ZeroMQ DEALER套接字通信
- JSON-RPC 2.0消息格式
- 自动客户端注册
- 心跳检测机制
- 重试机制

### 模拟服务器 (`mix/mix8_rpc_server.py`)

用于开发和测试的模拟 RPC 服务器：

- 模拟多个设备服务（power、relay、baseboard）
- 支持注册失败模拟测试
- 兼容 RPC8 和 RPC7 格式

### 服务器启动脚本 (`mix/mix8_rpc_server.sh`)

便捷的模拟服务器启动脚本：

- 自动检测并关闭占用 7801 端口的进程
- 自动激活虚拟环境
- 支持 `--test-reg-fail` 参数模拟注册失败场景

### MIX_2.0 协议文档 (`mix/readme.md`)

详细的协议注册机制文档，包含：

- DEALER-ROUTER 通信模式架构图
- 完整的注册时序（version → hello → get_all_services）
- 客户端 ID 生成与管理机制
- 服务端请求分发验证逻辑
- 常见错误码与故障排除

## 使用方法

### 1. 添加通道

- 右键通道列表选择"新增一行"添加单个通道
- 或选择"配置通道"批量配置多个通道
- 输入设备IP地址和端口

### 2. 连接设备

- 点击通道对应行的"连接"按钮
- 连接成功后状态显示"已连接"
- 自动获取设备命令列表

### 3. 发送命令

- 在命令输入框输入命令（如：`power.measure`）
- 使用Tab键选择提示的命令
- 在参数框添加参数（如：`channel=1 count=100`）
- 点击"发送"按钮发送到所有已连接通道

### 4. 管理序列

- 右键序列列表选择"添加指令"、"添加延迟"或"添加暂停"
- 通过拖拽调整顺序
- 点击"执行序列"按钮运行

## 技术特点

- **协议兼容**：同时支持MIX_2.0和JSON-RPC 2.0协议
- **线程安全**：UI更新使用信号槽机制
- **配置持久化**：自动保存配置到用户目录
- **错误恢复**：自动重连和错误处理
- **调试友好**：详细的日志输出

## 依赖项

- PyQt6 >= 6.0
- pyzmq >= 4.0
- numpy >= 1.20

## 注意事项

- 确保设备IP地址和端口配置正确
- 某些命令需要设备先注册才能使用
- 批量操作时请注意网络带宽
- 序列执行过程中可以随时停止

## 开发扩展

### 添加新服务

在 `mix/mix8_rpc_server.py` 中添加新的服务类：

```python
class NewService:
    def new_method(self, param1, param2):
        """新方法的文档"""
        return {"result": "success"}
```

在服务器初始化时注册：

```python
self.register_service("new_service", NewService())
```

### 修改协议格式

RPC消息格式定义在 `mix/mix8_rpc_client.py` 中，可根据实际设备要求调整。

## 作者

zjx - MIX调试工具 by zjx

## 版本历史

- v4: 优化协议实现，添加详细调试日志，完善通道管理
- v2.0: 优化协议实现，添加详细调试日志
- v1.0: 初始版本
