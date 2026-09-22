#!/bin/bash

# 关闭占用7801端口的进程
echo "正在检查7801端口..."
PID=$(lsof -t -i:7801)

if [ ! -z "$PID" ]; then
    echo "发现占用7801端口的进程，PID: $PID"
    echo "正在关闭进程..."
    kill -9 $PID
    echo "进程已关闭"
else
    echo "7801端口未被占用"
fi

# 等待端口释放
sleep 2

# 激活虚拟环境
echo "正在激活虚拟环境..."
source /Users/gdlocal/Desktop/env_sum/vis/bin/activate

# 启动RPC服务器
echo "正在启动RPC服务器..."

# 检查是否传入了测试模式参数
if [ "$1" == "--test-reg-fail" ]; then
    echo "注意: 已启用注册失败模拟模式"
    if [ ! -z "$2" ] && [[ "$2" == --fail-rate* ]]; then
        python3 mix8_rpc_server.py "$1" "$2" "$3"
    else
        python3 mix8_rpc_server.py "$1"
    fi
else
    python3 mix8_rpc_server.py
fi
