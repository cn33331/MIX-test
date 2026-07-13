import struct
import sys
import os
import csv
import numpy as np


def code_to_mvolt2(code, gain=58.3, mvref=1000):
    """将32位原始编码转换为毫伏值（使用增益参数版本）。

    从32位数据中提取最高12位作为有效数据，通过补码处理负数，
    最终转换为对应的毫伏值。

    Args:
        code (int): 32位原始编码数据。
        gain (float, optional): 增益系数，用于计算毫伏值。默认值为 58.3。
        mvref (float, optional): 参考电压（毫伏）。默认值为 1000。

    Returns:
        float: 转换后的毫伏值。

    Example:
        >>> code = 0x05a00000
        >>> voltage = code_to_mvolt2(code, gain=58.3)
        >>> print(voltage)

    Warning:
        输入的 code 应为32位无符号整数。若超出范围可能导致结果异常。
    """
    code >>= 20
    if code >= 0x800:
        code -= 0x1000
    # print(gain)
    return code / 0x7ff * gain


def code_to_mvolt(code, mvref=1000):
    """将32位原始编码转换为毫伏值（右移20位版本）。

    从32位数据中提取最高12位作为有效数据（右移20位），
    通过补码处理负数，最终转换为对应的毫伏值。

    Args:
        code (int): 32位原始编码数据。
        mvref (float, optional): 参考电压（毫伏）。默认值为 1000。

    Returns:
        float: 转换后的毫伏值。

    Example:
        >>> code = 0x05a00000
        >>> voltage = code_to_mvolt(code, mvref=1000)
        >>> print(voltage)
    """
    code >>= 20
    if code >= 0x800:
        code -= 0x1000
    return code * mvref / 0x7ff


def code_to_mvolt10(code, mvref=1000):
    """将原始编码转换为毫伏值（右移10位版本）。

    从数据中右移10位提取有效数据，通过补码处理负数，
    最终转换为对应的毫伏值。

    Args:
        code (int): 原始编码数据。
        mvref (float, optional): 参考电压（毫伏）。默认值为 1000。

    Returns:
        float: 转换后的毫伏值。

    Example:
        >>> code = 0x5a0
        >>> voltage = code_to_mvolt10(code, mvref=1000)
        >>> print(voltage)
    """
    code >>= 10
    if code >= 0x800:
        code -= 0x1000
    return code * mvref / 0x7ff


def code_to_mvolt0(code, mvref=1000):
    """将原始编码直接转换为毫伏值（不位移版本）。

    不对输入数据进行位移操作，直接使用完整数据计算毫伏值。
    适用于数据已经是正确格式的场景。

    Args:
        code (int): 原始编码数据（已为有效格式）。
        mvref (float, optional): 参考电压（毫伏）。默认值为 1000。

    Returns:
        float: 转换后的毫伏值。

    Example:
        >>> code = 2047
        >>> voltage = code_to_mvolt0(code, mvref=1000)
        >>> print(voltage)
    """
    return code * mvref / 0x7ff


def to_12bit_signed(value):
    """将12位无符号值转换为有符号整数（使用二进制补码）。

    对输入值进行12位掩码处理后，检查最高位（第11位）是否为1。
    若为1则表示负数，通过补码转换为有符号整数；否则直接返回正值。

    Args:
        value (int): 输入的12位无符号整数值。

    Returns:
        int: 转换后的有符号整数值，范围为 -2048 到 2047。

    Example:
        >>> to_12bit_signed(0xFFF)
        -1
        >>> to_12bit_signed(0x7FF)
        2047
    """
    value = value & 0xFFF

    if value & 0x800:
        return value - 0x1000
    else:
        return value


def decode_bin_to_csv(bin_path, gain):
    """将二进制文件解码为CSV格式的电压数据文件。

    读取二进制文件，每次读取4字节数据解析为32位无符号整数（小端模式），
    然后转换为毫伏值并写入CSV文件。CSV文件与源文件同目录、同名。

    Args:
        bin_path (str): 二进制文件路径。
        gain (float): 增益系数，用于电压计算。

    Returns:
        str: 生成的CSV文件路径。

    Raises:
        FileNotFoundError: 当 bin_path 指定的文件不存在时。
        Exception: 文件读取或写入过程中发生的其他异常。

    Example:
        >>> csv_path = decode_bin_to_csv("data.bin", gain=58.3)
        >>> print(csv_path)
        data.csv

    Warning:
        若处理过程中发生错误，会自动删除已生成的不完整CSV文件。
    """
    csv_path = os.path.splitext(bin_path)[0] + ".csv"

    try:
        with open(bin_path, 'rb') as bin_file, open(csv_path, 'w') as csv_file:
            while True:
                data = bin_file.read(4)
                if not data:
                    break

                code = struct.unpack('<I', data)[0]
                voltage = code_to_mvolt2(code, gain)
                csv_file.write(f"{voltage:.6f}\n")

        print(f"解码完成，CSV文件已保存至：{csv_path}")

    except Exception as e:
        print(f"处理失败：{str(e)}")
        if os.path.exists(csv_path):
            os.remove(csv_path)
    return csv_path


def calculate_frequency(raw_values, reference, interval, sample_rate):
    """根据原始电压数据计算信号频率。

    通过检测上升沿穿过参考电压的时间点来计算信号周期，
    进而计算出信号频率。使用间隔采样策略避免误触发。

    Args:
        raw_values (list): 原始数据列表，每个元素为包含电压值的列表。
        reference (float): 参考电压值，用于判断上升沿。
        interval (int): 上升沿检测的最小间隔点数，用于防抖。
        sample_rate (float): 采样率（Hz）。

    Returns:
        tuple: 包含以下元素的元组：
            - freq (float): 计算得到的频率（Hz）。
            - end_collect_index (int): 最后一个上升沿的索引位置。
            - start_collect_index (int): 第一个上升沿的索引位置。
            - period (int): 检测到的周期个数。

    Example:
        >>> raw_data = [[1.0], [2.0], [3.0], [2.0], [1.0], [2.0], [3.0]]
        >>> freq, end_idx, start_idx, period = calculate_frequency(
        ...     raw_data, reference=2.0, interval=2, sample_rate=1000)
        >>> print(f"频率: {freq} Hz")

    Warning:
        若数据中上升沿数量不足，返回的频率可能为0。
    """
    period = 0
    start_flag = False
    start_collect_index = -1
    end_collect_index = -1
    last_index = -1
    count = len(raw_values)

    i = 1
    while i < count:
        curr = float(raw_values[i][0])
        prev = float(raw_values[i-1][0])

        remaining = count - i
        if remaining > interval:
            length = interval - 1
        else:
            length = remaining - 2

        if prev < reference and curr >= reference:
            if length <= 0:
                print(length)
                print(i)
            if (i - last_index) < interval:
                print(i)

        if (prev < reference and curr >= reference and
            length > 0 and (i - last_index) > interval):
            if not start_flag:
                start_flag = True
                start_collect_index = i
                last_index = start_collect_index
            else:
                period += 1
                end_collect_index = i

            i += interval
        else:
            i += 1

    freq = 0.0
    if period > 0:
        if start_collect_index != -1 and end_collect_index != -1:
            freq = sample_rate / (end_collect_index - start_collect_index) * period

    print("end_collect_index:", end_collect_index)
    print("start_collect_index:", start_collect_index)
    print("period:", period)

    return freq, end_collect_index, start_collect_index, period


if __name__ == "__main__":
    while True:
        print("用法：将bin文件拖入终端,按下回车")
        bin_file_path = input("输入log文件夹路径: ").strip()
        if not os.path.isfile(bin_file_path):
            print(f"错误：文件不存在 - {bin_file_path}")
            sys.exit(1)

        if not bin_file_path.lower().endswith('.bin'):
            print(f"错误：请提供.bin格式的文件")
            sys.exit(1)

        decode_bin_to_csv(bin_file_path)

        referVolt = 5
        intervalCount = 30
        _sampleRate = 125000000
        raw_data = []
        csv_path = os.path.splitext(bin_file_path)[0] + ".csv"
        with open(csv_path, 'r') as csvfile:
            reader = csv.reader(csvfile)
            for i in reader:
                raw_data.append(i)

        print(len(raw_data))
        frequency = calculate_frequency(raw_data, referVolt, intervalCount, _sampleRate)
        print(f"计算得到的频率: {frequency}")
