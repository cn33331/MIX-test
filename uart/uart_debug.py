import serial
import serial.tools.list_ports
import threading
import sys

def scan_serial_ports():
    """
    扫描系统中所有可用的串口（标准路径：/dev/ttyUSB*, /dev/ttyACM*, /dev/ttyAMA* 等）
    返回：列表 [设备路径, 描述]
    """
    ports = serial.tools.list_ports.comports()
    port_list = []
    for port, desc, hwid in sorted(ports):
        port_list.append((port, desc))
    return port_list

def read_serial(ser):
    """
    子线程：持续读取串口数据并打印到终端
    """
    try:
        while ser.is_open:
            # 读取数据（二进制转字符串，兼容普通串口）
            data = ser.readline()
            if data:
                # 解码并打印，避免乱码
                print(data.decode('utf-8', errors='replace').strip())
    except:
        pass

def main():
    print("===== Python 通用串口工具 (替代 nanocom) =====")
    print("支持：任意路径串口 / 标准串口 / 自定义参数")
    print("退出方式：按下 Ctrl + C\n")

    # 1. 扫描可用串口
    print("=== 扫描到的标准串口 ===")
    ports = scan_serial_ports()
    if ports:
        for i, (port, desc) in enumerate(ports):
            print(f"{i+1}. {port}  | 描述：{desc}")
    else:
        print("未扫描到标准串口，可手动输入自定义路径")
    print("-" * 50)

    # 2. 选择串口方式：自动/手动
    choice = input("选择方式：\n1. 使用扫描到的串口\n2. 手动输入自定义串口路径\n请输入数字(1/2)：")
    
    if choice == "1" and ports:
        idx = int(input("输入串口编号：")) - 1
        serial_port = ports[idx][0]
    else:
        # 核心：支持输入任意路径！！！
        serial_port = input("请输入自定义串口完整路径（如：/dev/ttyMySerial）：")

    # 3. 配置串口参数（默认和 nanocom 一致）
    baudrate = int(input("请输入波特率（默认 115200）：") or 115200)
    bytesize = serial.EIGHTBITS
    parity = serial.PARITY_NONE
    stopbits = serial.STOPBITS_ONE

    print(f"\n=== 连接信息 ===")
    print(f"串口路径：{serial_port}")
    print(f"参数：{baudrate} 8N1")
    print("-" * 50)

    # 4. 连接串口
    try:
        ser = serial.Serial(
            port=serial_port,
            baudrate=baudrate,
            bytesize=bytesize,
            parity=parity,
            stopbits=stopbits,
            timeout=1
        )

        if ser.is_open:
            print(f"✅ 串口连接成功！开始收发数据（Ctrl+C 退出）\n")

            # 启动子线程读取串口数据
            thread = threading.Thread(target=read_serial, args=(ser,), daemon=True)
            thread.start()

            # 主线程：发送用户输入的数据
            while True:
                try:
                    send_data = input()
                    ser.write((send_data + '\n').encode('utf-8'))
                except KeyboardInterrupt:
                    print("\n\n✅ 已断开串口连接")
                    ser.close()
                    sys.exit(0)

    except Exception as e:
        print(f"❌ 连接失败：{str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()