# 注意事项
1. 运行环境

   ```
   cd /Users/gdlocal/Desktop/myCode/myAPP/MIX-test
   source /Users/gdlocal/Desktop/env_sum/vis/bin/activate
   python3 main.py
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
## 项目功能
1. 主窗口 ：多个通道IP的显示。包含参数输入、指令发送、日志显示等功能。
   1. 通道配置：
      1. 默认一个通道，可以通过添加按钮添加更多通道，每个通道可以配置IP、端口等参数
      2. 添加通道配置按钮，按下有个小窗口弹出，可以配置通道数目，通道的IP和端口，可以按照一定逻辑，自动生成。这个逻辑用个小窗口修改。
      3. 通过按钮点击开始连接,点击按钮可以取消连接。
      4. 通道连接状态：连接成功后，在通道列表中显示连接状态。
      5. 通道指令发送：对当前已连接的通道同步发送指令
      6. 通道数目可能会很多，达到24个，有一个组件方便拉动。
   2. 参考 mix8/mix8.py 中的methods_info和subMethods_info函数。命令列表在输入的时候下面，会有提示，方便补充。选中对应的命令后，另外有个小窗口，显示该命令的详细说明doc。
   3. 参考/mix8/mix8.py完成RPC通信的建立和指令的发送。
## 项目文档结构

   ```
MIX-test/
├── main.py          # 程序入口，初始化应用并加载主窗口
├── core/            # 核心业务层
│   ├── cmd_manager.py   # 指令管理，处理命令的执行和参数管理
│   └── rpc_client.py    # RPC客户端封装，处理与设备的通信
├── ui/              # UI界面层
│   ├── main_window.py  # 主窗口逻辑，包含所有UI组件和事件处理
│   └── main.ui         # UI设计文件，定义界面布局
├── mix8/            # RPC通信相关代码
│   └── MoroccoA_RPC_client_demo_v1.0.py  # RPC客户端示例代码
└── README.md        # 项目说明（功能、环境、运行步骤）
   ```

## UI 界面组件结构

| 组件名称 | 关联文件 | 功能说明 |
|---------|---------|--------|
| MainWindow | ui/main_window.py | 应用主窗口类，包含所有UI组件，管理整体布局和事件处理 |
| MainUI | ui/main.ui | UI设计文件，定义界面布局和组件排列 |
| ip_table | ui/main_window.py | 通道列表表格，显示和管理通道信息，支持多选 |
| cmd_input | ui/main_window.py | 命令输入框，用于输入RPC命令，支持自动提示 |
| command_hint_list | ui/main_window.py | 命令提示列表，根据输入显示匹配的命令，支持点击选择 |
| cmd_info_text | ui/main_window.py | 命令信息显示，显示选中命令的详细说明和参数 |
| param_input | ui/main_window.py | 命令和参数输入框，cmd_input选择命令后按回车会显示命令，然后手动添加参数，作为最终发送的完整命令 |
| send_cmd_button | ui/main_window.py | 发送按钮，发送param_input中的完整命令和参数到所有已连接通道 |
| log_text | ui/main_window.py | 日志显示，显示应用运行日志和操作结果 |
| history_list | ui/main_window.py | 历史指令列表，显示已发送的命令，点击可直接再次发送 |

