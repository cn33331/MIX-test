import struct
import sys
import os
import csv
import numpy as np

# b'\x00\x00\xa0\x05'
# 5a
# 小端排序
# \x05\xa0\x00\x00'

def code_to_mvolt2(code, gain=58.3,mvref=1000):
    # 从 32 位数据中提取最高 12 位
    # 05a
    code >>= 20  # 右移20位
    # print(code)
    # print(co2123de)
    if code >= 0x800:  # 处理负数（补码）
        code -= 0x1000
    print(gain)
    return code / 0x7ff * gain # 计算毫伏值

def code_to_mvolt(code, mvref=1000):
    code >>= 20  # 右移20位
    if code >= 0x800:  # 处理负数（补码）
        code -= 0x1000
    return code * mvref / 0x7ff  # 计算毫伏值

def code_to_mvolt10(code, mvref=1000):
    code >>= 10  # 右移10位
    if code >= 0x800:
        code -= 0x1000
    return code * mvref / 0x7ff

def code_to_mvolt0(code, mvref=1000):
    return code * mvref / 0x7ff  # 不位移，直接计算

def to_12bit_signed(value):
    """Convert 12-bit value to signed integer using two's complement"""
    # Mask to ensure we only have 12 bits
    value = value & 0xFFF
    
    # Check if negative (bit 11 is set)
    if value & 0x800:
        # Two's complement conversion for negative numbers
        return value - 0x1000
    else:
        # Positive number
        return value

def decode_bin_to_csv(bin_path,gain):
    # 生成CSV文件路径（与bin文件同目录、同名）
    csv_path = os.path.splitext(bin_path)[0] + ".csv"
    
    try:
        with open(bin_path, 'rb') as bin_file, open(csv_path, 'w') as csv_file:
            while True:
                data = bin_file.read(4)
                # print(data)
                if not data:
                    break  # 文件读取完毕
                
                code = struct.unpack('<I', data)[0]  # 解析为32位无符号整数（小端
                # print(code)
                # 解码为毫伏值
                voltage = code_to_mvolt2(code,gain)
                # 每行写入一个数据
                csv_file.write(f"{voltage:.6f}\n")
        
        print(f"解码完成，CSV文件已保存至：{csv_path}")
    
    except Exception as e:
        print(f"处理失败：{str(e)}")
        # 若出错删除可能的不完整CSV文件
        if os.path.exists(csv_path):
            os.remove(csv_path)
    return csv_path

    
def calculate_frequency(raw_values, reference, interval, sample_rate):
    """
    根据原始数据计算频率
    
    参数:
        raw_values: 原始数据列表
        reference: 参考值
        interval: 间隔值
        sample_rate: 采样率
    返回:
        计算得到的频率
    """
    period = 0
    start_flag = False
    start_collect_index = -1
    end_collect_index = -1
    last_index = -1
    count = len(raw_values)
    
    i = 1
    while i < count:
        # 获取当前值和前一个值
        curr = float(raw_values[i][0])
        prev = float(raw_values[i-1][0])
        
        # 计算长度
        remaining = count - i
        if remaining > interval:
            length = interval - 1
        else:
            length = remaining - 2  # 对应原代码中的_rawValues.count - i - 2
        
        if prev < reference and curr >= reference:
            if length <= 0 :
                print(length)
                print(i)
            if (i - last_index) < interval:
                print(i)

        # 上升沿到达参考电压
        if (prev < reference and curr >= reference and 
            length > 0 and (i - last_index) > interval):
        # if prev < reference and curr >= reference:
            if not start_flag:
                # 第一次满足条件，标记开始
                start_flag = True
                start_collect_index = i
                last_index = start_collect_index
            else:
                # 后续满足条件，累加周期并标记结束
                period += 1
                end_collect_index = i
            
            # 跳过间隔
            i += interval
        else:
            # 不满足条件，正常递增
            i += 1
    
    # 计算频率
    freq = 0.0
    if period > 0:
        # 确保开始和结束索引有效
        if start_collect_index != -1 and end_collect_index != -1:
            freq = sample_rate / (end_collect_index - start_collect_index) * period

    print("end_collect_index:",end_collect_index)
    print("start_collect_index:",start_collect_index)
    print("period:",period)
    
    return freq,end_collect_index,start_collect_index,period

if __name__ == "__main__":
    while True:
        print("用法：将bin文件拖入终端,按下回车")
        bin_file_path = input("输入log文件夹路径: ").strip()
        # 检查文件是否存在
        if not os.path.isfile(bin_file_path):
            print(f"错误：文件不存在 - {bin_file_path}")
            sys.exit(1)
        
        # 检查文件后缀是否为bin
        if not bin_file_path.lower().endswith('.bin'):
            print(f"错误：请提供.bin格式的文件")
            sys.exit(1)
        
        decode_bin_to_csv(bin_file_path)

        referVolt=5
        intervalCount=30
        _sampleRate = 125000000
        raw_data = []
        csv_path = os.path.splitext(bin_file_path)[0] + ".csv"
        with open(csv_path, 'r') as csvfile:
            # reader = csv.DictReader(csvfile)
            reader = csv.reader(csvfile)
            for i in reader:
                raw_data.append(i)

        print(len(raw_data))
        # print(type(raw_data[0][0]))
        frequency = calculate_frequency(raw_data, referVolt, intervalCount, _sampleRate)
        print(f"计算得到的频率: {frequency}")

