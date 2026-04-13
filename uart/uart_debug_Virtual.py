import os
import pty
import select  # ✅ 修复：放在文件顶部
import threading
import time

def echo_service(master_fd, slave_name):
    """
    回显服务：读取虚拟串口数据并原样发回
    """
    print(f"✅ 回显服务已启动，监听串口：{slave_name}")
    print("提示：用另一个终端运行之前的串口工具，连接此串口，发送数据将看到回显\n")
    
    try:
        while True:
            # 使用 select 监听文件描述符，避免阻塞
            r, w, e = select.select([master_fd], [], [], 0.1)
            if master_fd in r:
                data = os.read(master_fd, 1024)
                if data:
                    # 原样回显数据
                    os.write(master_fd, data)
                    # 打印到当前终端（方便调试）
                    print(f"📥 收到数据：{data.decode('utf-8', errors='replace').strip()}")
    except Exception as e:
        print(f"❌ 回显服务出错：{e}")
    finally:
        os.close(master_fd)

def main():
    print("===== 虚拟串口创建工具 (Linux/macOS) =====")
    print("功能：创建虚拟串口，启动回显服务，并支持发送数据\n")

    # 1. 创建虚拟串口对
    try:
        master_fd, slave_fd = pty.openpty()
    except Exception as e:
        print(f"❌ 创建虚拟串口失败：{e}")
        return

    # 2. 获取串口路径
    slave_name = os.ttyname(slave_fd)

    print("=== 虚拟串口创建成功 ===")
    print(f"测试用串口路径：{slave_name}")
    print("-" * 50)
    print("输入数据并按回车键发送，按 Ctrl+C 退出\n")

    # 3. 启动回显服务线程
    echo_thread = threading.Thread(target=echo_service, args=(master_fd, slave_name), daemon=True)
    echo_thread.start()

    # 4. 从终端读取用户输入并发送到虚拟串口
    try:
        while True:
            # 读取用户输入
            user_input = input()
            # 发送数据到虚拟串口
            os.write(master_fd, (user_input + '\n').encode('utf-8'))
            print(f"📤 发送数据：{user_input}")
    except KeyboardInterrupt:
        print("\n\n✅ 虚拟串口已关闭")
        os.close(slave_fd)

if __name__ == "__main__":
    main()