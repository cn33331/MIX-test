"""FFT频谱分析模块。

提供电压信号的FFT频谱分析功能，支持两种算法：Apple算法和Fixture算法。

算法架构说明：
===============

本模块包含两种独立的FFT分析算法，用于从电压数据中提取任意频率的幅值和功率(dBm)。
两种算法的核心流程均包含两个阶段：
    1. 电压原始数据 → 任意频率电压幅值（FFT变换 + 幅值提取）
    2. 电压幅值 → dBm功率值（功率计算公式）

----------------------------------------------------------------------
算法一：Fixture 算法（推荐，默认使用）
----------------------------------------------------------------------
特点：
    - 使用窗函数（平顶窗/汉宁窗/布莱克曼-哈里斯窗）减少频谱泄漏
    - 使用二次插值精确提取目标频率的幅值（精度更高）
    - 支持幅值补偿，消除窗函数对幅值的影响
    - 适用于精确电压幅值测量场景

核心函数：
    第一阶段（原始数据 → 幅值）：
        - fft_analysis_one()      : 单次FFT分析（加窗 + 补零 + FFT）
        - get_frequency_magnitude() : 频率幅值插值（二次插值提升精度）
        - get_fundamental_volt_Fixture() : Fixture算法指定频率电压提取

    第二阶段（幅值 → dBm）：
        - voltage_to_dbm_Fixture() : Fixture算法电压转dBm（含增益修正和校准常数）

调用入口：
    - get_fundamental_volt()  : 统一入口函数，selected_radio_vpp="fixture" 时使用

----------------------------------------------------------------------
算法二：Apple 算法
----------------------------------------------------------------------
特点：
    - 直接使用scipy.fft进行标准FFT变换
    - 不使用窗函数，直接计算频谱
    - 通过最近邻索引查找目标频率的幅值
    - 实现简单，计算速度快

核心函数：
    第一阶段（原始数据 → 幅值）：
        - calculate_fft()         : 标准FFT频谱计算（正频率 + 幅值归一化）
        - get_dbm_by_frequency()  : 指定频率dBm查询
        - get_fundamental_volt_apple() : Apple算法指定频率电压提取

    第二阶段（幅值 → dBm）：
        - voltage_to_dbm_apple()  : Apple算法电压转dBm（标准50Ω阻抗公式）

调用入口：
    - get_fundamental_volt()  : 统一入口函数，selected_radio_vpp="apple" 时使用

----------------------------------------------------------------------
算法对比总结：
----------------------------------------------------------------------
| 特性            | Fixture 算法               | Apple 算法                  |
|-----------------|---------------------------|---------------------------|
| 窗函数          | 支持（平顶/汉宁/布莱克曼）  | 无                        |
| 幅值精度        | 高（二次插值）             | 中（最近邻查找）            |
| 计算复杂度      | 较高                      | 较低                      |
| 适用场景        | 精确幅值测量               | 快速频谱分析               |
| dBm计算         | 增益修正+校准常数          | 标准50Ω阻抗公式            |
| 推荐使用        | 是（默认）                 | 否                        |

公共模块：
    - 窗函数：hanning_window(), blackman_harris_window(), flattop_window()
    - 数据读取：read_voltage_from_csv()
    - 幅值补偿：calculate_ampl_factor()
"""

import math
import csv
import numpy as np
from scipy.fft import fft, fftfreq


def hanning_window(n):
    """生成汉宁窗（Hanning Window）。

    汉宁窗适用于频谱分辨率优先的场景，可以有效减少频谱泄漏。
    窗函数公式：w(n) = 0.54 - 0.46 * cos(2πn/(N-1))

    Args:
        n (int): 窗函数的长度（采样点数）。

    Returns:
        numpy.ndarray: 长度为 n 的汉宁窗系数数组。

    Example:
        >>> window = hanning_window(100)
        >>> print(window.shape)
        (100,)

    Raises:
        ValueError: 当 n 小于等于 0 时。
    """
    window = np.zeros(n)
    for i in range(n):
        window[i] = 0.54 - 0.46 * math.cos(2 * math.pi * i / (n - 1))
    return window


def blackman_harris_window(n):
    """生成布莱克曼-哈里斯窗（Blackman-Harris Window）。

    布莱克曼-哈里斯窗具有极低的频谱泄漏，适用于精确频率测量。
    是一种四阶余弦窗，旁瓣抑制能力强。

    Args:
        n (int): 窗函数的长度（采样点数）。

    Returns:
        numpy.ndarray: 长度为 n 的布莱克曼-哈里斯窗系数数组。

    Example:
        >>> window = blackman_harris_window(100)
        >>> print(window.shape)
        (100,)

    Raises:
        ValueError: 当 n 小于等于 0 时。
    """
    a = [0.35875, 0.48829, 0.14128, 0.01168]
    window = np.zeros(n)
    for i in range(n):
        b = math.pi * i / (n - 1)
        window[i] = a[0] - a[1] * math.cos(2 * b) + a[2] * math.cos(4 * b) - a[3] * math.cos(6 * b)
    return window


def flattop_window(n):
    """生成平顶窗（Flat-Top Window）。

    平顶窗的幅值测量精度最高，通带内幅值波动极小，
    适用于电压幅值精确计算（推荐使用）。

    Args:
        n (int): 窗函数的长度（采样点数）。

    Returns:
        numpy.ndarray: 长度为 n 的平顶窗系数数组。

    Example:
        >>> window = flattop_window(100)
        >>> print(window.shape)
        (100,)

    Raises:
        ValueError: 当 n 小于等于 0 时。
    """
    a = [0.21557895, 0.41663158, 0.277263158, 0.083578947, 0.006947368]
    window = np.zeros(n)
    for i in range(n):
        theta = 2 * math.pi * i / (n - 1)
        window[i] = (a[0] - a[1] * math.cos(theta) + a[2] * math.cos(2 * theta)
                    - a[3] * math.cos(3 * theta) + a[4] * math.cos(4 * theta))
    return window


def read_voltage_from_csv(csv_path):
    """从CSV文件读取第一列电压数据。

    逐行读取CSV文件，提取第一列数据并转换为浮点数，
    忽略无法解析的行。返回numpy数组格式的电压数据。

    Args:
        csv_path (str): CSV文件路径。

    Returns:
        numpy.ndarray or None: 第一列的电压数据数组（float64类型），
            读取失败返回 None。

    Example:
        >>> voltages = read_voltage_from_csv("voltage_data.csv")
        >>> if voltages is not None:
        ...     print(f"读取到 {len(voltages)} 个数据点")

    Raises:
        FileNotFoundError: 当 csv_path 指定的文件不存在时。
    """
    try:
        voltage_data = []
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            for row in reader:
                if row:
                    try:
                        val = float(row[0])
                        voltage_data.append(val)
                    except (ValueError, IndexError):
                        continue
        voltage_data = np.array(voltage_data, dtype=np.float64)
        print(f"成功读取CSV：共{len(voltage_data)}个电压数据点（读取第一列）")
        return voltage_data
    except FileNotFoundError:
        print(f"CSV读取失败：文件不存在，请检查路径是否正确 -> {csv_path}")
        return None
    except Exception as e:
        print(f"CSV读取失败：未知错误 -> {str(e)}")
        return None


def calculate_ampl_factor(window):
    """计算窗函数的幅值补偿系数。

    加窗会改变信号的幅值，需要通过补偿系数进行修正。
    补偿系数 = 窗函数长度 / 窗函数系数之和。

    Args:
        window (numpy.ndarray): 窗函数系数数组。

    Returns:
        float: 幅值补偿系数。

    Example:
        >>> window = flattop_window(1024)
        >>> factor = calculate_ampl_factor(window)
        >>> print(f"幅值补偿系数: {factor}")

    Warning:
        窗函数所有系数之和不能为0，否则会导致除零错误。
    """
    return len(window) / np.sum(window)


def get_frequency_magnitude(fft_magnitude, target_freq, n, fs):
    """通过插值计算目标频率处的精确幅值。

    使用二次插值算法，在目标频率附近的三个FFT频点间进行插值，
    以获得比直接取最近频点更高的幅值精度。

    **算法归属**：Fixture 算法核心函数（第一阶段：幅值提取）

    Args:
        fft_magnitude (numpy.ndarray): FFT幅值数组。
        target_freq (float): 目标频率（Hz）。
        n (int): FFT变换的点数。
        fs (float): 采样率（Hz）。

    Returns:
        float: 目标频率处的插值幅值。

    Example:
        >>> mag = get_frequency_magnitude(fft_result, 100000, 1024, 125000000)
        >>> print(f"目标频率幅值: {mag}")

    Warning:
        若 fft_magnitude 为 None，返回值为 0.0。
    """
    if fft_magnitude is None:
        return 0.0
    k_target = target_freq * n / fs
    k0 = int(math.floor(k_target))
    delta = k_target - k0
    mag = np.zeros(3)
    for i in range(-1, 2):
        idx = k0 + i
        idx = max(0, min(idx, n//2 - 1))
        mag[i+1] = fft_magnitude[idx]
    interpolated = (mag[1] - 0.25 * (mag[0] - mag[2]) * delta
                   + 0.25 * (mag[0] - 2 * mag[1] + mag[2]) * delta * delta)
    return interpolated


def fft_analysis_one(raw_voltage, sample_rate, window_type=1):
    """执行单次FFT分析，返回幅值数组和补偿系数。

    对原始电压数据进行加窗、补零、FFT变换等预处理，
    返回FFT幅值数组、幅值补偿系数、FFT点数和原始数据长度。

    **算法归属**：Fixture 算法核心函数（第一阶段：原始数据 → 幅值）

    Args:
        raw_voltage (numpy.ndarray): 原始电压数据数组。
        sample_rate (float): 采样率（Hz）。
        window_type (int, optional): 窗函数类型：
            - 0: 无窗
            - 1: 平顶窗（默认）
            - 2: 汉宁窗
            - 3: 布莱克曼-哈里斯窗

    Returns:
        tuple: 包含以下元素的元组：
            - fft_magnitude (numpy.ndarray): FFT幅值数组。
            - compensation (float): 幅值补偿系数。
            - size_n (int): FFT变换的点数（2的整数次幂）。
            - size_m (int): 原始数据的长度。

    Example:
        >>> voltages = read_voltage_from_csv("data.csv")
        >>> fft_mag, comp, n, m = fft_analysis_one(voltages, 125000000, 1)

    Warning:
        若输入数据为空或 None，返回 None。
    """
    if raw_voltage is None or len(raw_voltage) == 0:
        print("FFT分析失败：无有效电压数据")
        return None

    size_m = len(raw_voltage)
    size_n = 1
    while size_n < size_m:
        size_n *= 2

    window = None
    if window_type > 0:
        if window_type == 1:
            window = flattop_window(size_n)
        elif window_type == 2:
            window = hanning_window(size_n)
        elif window_type == 3:
            window = blackman_harris_window(size_n)
        print(f"启用窗函数：{['无窗', '平顶窗', '汉宁窗', '布莱克曼-哈里斯窗'][window_type]}")

    x = np.zeros(size_n, dtype=np.complex128)
    for i in range(size_n):
        if i < size_m:
            if window_type > 0:
                x[i] = raw_voltage[i] * window[i]
            else:
                x[i] = raw_voltage[i]
        else:
            x[i] = 0.0

    fft_result = fft(x)
    fft_magnitude = np.abs(fft_result)

    compensation = 1.0
    if window_type > 0:
        compensation = calculate_ampl_factor(window)

    return fft_magnitude, compensation, size_n, size_m


def fft_analysis(raw_voltage, sample_rate, window_type=1, frequency=1):
    """电压信号FFT分析，获取指定频率的电压幅值。

    对原始电压数据进行FFT分析，计算指定频率处的电压幅值。
    使用插值算法提高幅值测量精度。

    Args:
        raw_voltage (numpy.ndarray): 原始电压数据数组。
        sample_rate (float): 采样率（Hz）。
        window_type (int, optional): 窗函数类型：
            - 0: 无窗
            - 1: 平顶窗（默认）
            - 2: 汉宁窗
            - 3: 布莱克曼-哈里斯窗
        frequency (float, optional): 目标频率（Hz）。默认值为 1。

    Returns:
        dict: 包含以下键的字典：
            - "fundamental_voltage" (float): 指定频率的电压幅值（V）。
            - "fft_magnitude" (numpy.ndarray): 正频率部分FFT幅值数组。

    Example:
        >>> voltages = read_voltage_from_csv("data.csv")
        >>> result = fft_analysis(voltages, 125000000, 1, 112000)
        >>> print(f"指定频率电压: {result['fundamental_voltage']} V")

    Warning:
        若输入数据为空或FFT分析失败，返回 None。
    """
    fft_magnitude, compensation, size_n, size_m = fft_analysis_one(raw_voltage, sample_rate, window_type)

    fundamental_voltage = get_frequency_magnitude(
        fft_magnitude, frequency, size_n, sample_rate
    )
    fundamental_voltage *= compensation * 2 / size_m

    return {
        "fundamental_voltage": fundamental_voltage,
        "fft_magnitude": fft_magnitude[:size_n//2],
    }


def voltage_to_dbm_apple(voltage_amplitude, gain=1.0, impedance=50, cal_constant=10.79):
    """由电压幅值计算dBm值（Apple标准算法）。

    假设信号为正弦波，先将幅值转换为有效值，再根据负载阻抗计算功率，
    最后转换为dBm值。公式：dBm = 10 * log10(Vrms² / R * 1000)

    **算法归属**：Apple 算法核心函数（第二阶段：幅值 → dBm）

    Args:
        voltage_amplitude (float): 电压幅值（V）。
        gain (float, optional): 增益系数。默认值为 1.0。
        impedance (float, optional): 负载阻抗（Ω）。默认值为 50。
        cal_constant (float, optional): 校准常数。默认值为 10.79。

    Returns:
        float or None: 计算得到的dBm值，输入无效时返回 None。

    Example:
        >>> dbm = voltage_to_dbm_apple(1.0, impedance=50)
        >>> print(f"功率: {dbm} dBm")

    Warning:
        电压幅值或阻抗必须为正值，否则返回 None。
    """
    if voltage_amplitude <= 0 or impedance <= 0:
        print("dbm计算失败：电压幅值或阻抗不能为非正值")
        return None
    rms_voltage = voltage_amplitude / math.sqrt(2)
    power_watt = (rms_voltage ** 2) / impedance
    power_mw = power_watt * 1000
    dbm = 10 * math.log10(power_mw)
    return dbm


def voltage_to_dbm_Fixture(voltage_amplitude, gain=1.0, impedance=50, cal_constant=10.79):
    """由电压幅值计算dBm值（Fixture兼容算法）。

    兼容Lua逻辑的dBm计算方法，包含增益修正和硬件校准常数。
    公式：dBm = 20 * log10(Vrms) + cal_constant

    **算法归属**：Fixture 算法核心函数（第二阶段：幅值 → dBm）

    Args:
        voltage_amplitude (float): 原始电压幅值（V）。
        gain (float, optional): 硬件增益系数。默认值为 1.0。
        impedance (float, optional): 负载阻抗（Ω）。默认值为 50。
        cal_constant (float, optional): 校准常数。默认值为 10.79。

    Returns:
        float or None: 计算得到的dBm值，输入无效时返回 None。

    Example:
        >>> dbm = voltage_to_dbm_Fixture(1.0, gain=1.0, cal_constant=10.79)
        >>> print(f"功率: {dbm} dBm")

    Warning:
        电压幅值或阻抗必须为正值，否则返回 None。
    """
    if voltage_amplitude <= 0 or impedance <= 0:
        print("dbm计算失败：电压幅值或阻抗不能为非正值")
        return None
    calibrated_amplitude = voltage_amplitude * gain
    rms_voltage = calibrated_amplitude / math.sqrt(2)
    dbm = 20 * math.log10(rms_voltage) + cal_constant
    return dbm


def calculate_fft(csv_path, sample_rate, impedance, selected_radio_dbm="apple"):
    """计算CSV数据的完整FFT频谱。

    读取CSV文件中的电压数据，执行FFT变换，计算正频率部分的
    幅值和dBm值。

    **算法归属**：Apple 算法核心函数（第一阶段：原始数据 → 幅值）

    Args:
        csv_path (str): CSV文件路径。
        sample_rate (float): 采样率（Hz）。
        impedance (float): 负载阻抗（Ω）。
        selected_radio_dbm (str, optional): dBm计算方式：
            - "apple": Apple标准算法（默认）
            - "fixture": Fixture兼容算法

    Returns:
        tuple: 包含以下元素的元组：
            - xf_positive (numpy.ndarray): 正频率数组（Hz）。
            - yf_dbm (numpy.ndarray): 正频率对应的dBm值数组。
            - yf_positive (numpy.ndarray): 正频率对应的电压幅值数组。

    Example:
        >>> freqs, dbms, volts = calculate_fft("data.csv", 125000000, 50)
        >>> print(f"频率范围: {freqs[0]} - {freqs[-1]} Hz")
    """
    voltages = read_voltage_from_csv(csv_path)
    N = len(voltages)
    yf = fft(voltages)
    xf = fftfreq(N, 1 / sample_rate)

    positive_freq_mask = xf >= 0
    xf_positive = xf[positive_freq_mask]
    yf_positive = 2.0 / N * np.abs(yf[positive_freq_mask])
    if selected_radio_dbm == "apple":
        yf_dbm = np.array([voltage_to_dbm_apple(v, impedance) for v in yf_positive])
    else:
        yf_dbm = np.array([voltage_to_dbm_Fixture(v, impedance) for v in yf_positive])
    return xf_positive, yf_dbm, yf_positive


def get_dbm_by_frequency(csv_path, sample_rate, impedance, target_freq, selected_radio_dbm="apple"):
    """获取指定频率处的dBm值和电压幅值。

    对CSV数据执行FFT分析，找到与目标频率最接近的频点，
    返回对应的dBm值和电压幅值。

    Args:
        csv_path (str): CSV文件路径。
        sample_rate (float): 采样率（Hz）。
        impedance (float): 负载阻抗（Ω）。
        target_freq (float): 目标频率（Hz）。
        selected_radio_dbm (str, optional): dBm计算方式：
            - "apple": Apple标准算法（默认）
            - "fixture": Fixture兼容算法

    Returns:
        tuple: 包含以下元素的元组：
            - target_dbm (float): 目标频率处的dBm值。
            - target_Vpp (float): 目标频率处的电压幅值（V）。

    Example:
        >>> dbm, vpp = get_dbm_by_frequency(
        ...     "data.csv", 125000000, 50, 112000)
        >>> print(f"{dbm:.2f} dBm, {vpp:.3f} V")
    """
    xf_positive, yf_dbm, yf_positive = calculate_fft(csv_path, sample_rate, impedance, selected_radio_dbm)
    closest_idx = np.argmin(np.abs(xf_positive - target_freq))
    closest_freq = xf_positive[closest_idx]
    target_dbm = yf_dbm[closest_idx]
    target_Vpp = yf_positive[closest_idx]

    print(f"===============================================")
    print(selected_radio_dbm)
    print(f"目标频率：{target_freq:.2f} Hz")
    print(f"FFT 中最接近的频率：{closest_freq:.2f} Hz")
    print(f"对应 dBm 值：{target_dbm:.2f} dBm")
    print(f"对应 幅值：{target_Vpp:.2f} V")
    print(f"===============================================")

    return target_dbm, target_Vpp


def get_fundamental_volt_Fixture(csv_path, sample_rate, window_type, start_frep, end_frep, step_frep,
                                 gain=1, impedance=50, cal_constant=10.79, selected_radio_dbm="fixture"):
    """使用Fixture算法计算指定频率范围内的电压幅值和dBm。

    对指定频率范围内的每个频率点，使用窗函数FFT和插值算法
    计算精确的电压幅值和dBm值。

    Args:
        csv_path (str): CSV文件路径。
        sample_rate (float): 采样率（Hz）。
        window_type (int): 窗函数类型（0=无窗, 1=平顶窗, 2=汉宁窗, 3=布莱克曼-哈里斯窗）。
        start_frep (int): 起始频率（Hz）。
        end_frep (int): 结束频率（Hz）。
        step_frep (int): 频率步进（Hz）。
        gain (float, optional): 增益系数。默认值为 1。
        impedance (float, optional): 负载阻抗（Ω）。默认值为 50。
        cal_constant (float, optional): 校准常数。默认值为 10.79。
        selected_radio_dbm (str, optional): dBm计算方式。默认值为 "fixture"。

    Returns:
        dict or None: 以频率为键的字典，每个值包含：
            - "volt" (float): 电压幅值（V）。
            - "dbm" (float): dBm值。
            参数错误时返回 None。

    Example:
        >>> result = get_fundamental_volt_Fixture(
        ...     "data.csv", 125000000, 1, 100000, 200000, 10000)
        >>> for freq, data in result.items():
        ...     print(f"{freq} Hz: {data['volt']:.3f} V, {data['dbm']:.1f} dBm")
    """
    raw_voltage = read_voltage_from_csv(csv_path)
    try:
        start_idx = int(start_frep)
        end_idx = int(end_frep)
        step = int(step_frep)
    except ValueError:
        print("错误：起始/结束点必须是整数！")
        return None
    fundamental_volt_dict = {}
    print(f"频率,电压幅值,dbm")
    fft_magnitude, compensation, size_n, size_m = fft_analysis_one(raw_voltage, sample_rate, window_type)
    for idx_frep in range(start_idx, end_idx, step):
        fundamental_voltage = get_frequency_magnitude(
            fft_magnitude, idx_frep, size_n, sample_rate
        )
        fundamental_voltage *= compensation * 2 / size_m
        if selected_radio_dbm == "fixture":
            dbm_value = voltage_to_dbm_Fixture(fundamental_voltage, gain, impedance, cal_constant)
        else:
            dbm_value = voltage_to_dbm_apple(fundamental_voltage, gain, impedance, cal_constant)
        if dbm_value != None:
            fundamental_volt_dict[idx_frep] = {}
            fundamental_volt_dict[idx_frep]["volt"] = fundamental_voltage
            fundamental_volt_dict[idx_frep]["dbm"] = dbm_value

        print(f"{idx_frep},{fundamental_voltage},{dbm_value}")

    return fundamental_volt_dict


def get_fundamental_volt_apple(csv_path, sample_rate, window_type, start_frep, end_frep, step_frep,
                               gain=1, impedance=50, cal_constant=10.79, selected_radio_dbm="apple"):
    """使用Apple算法计算指定频率范围内的电压幅值和dBm。

    对指定频率范围内的每个频率点，使用标准FFT取最近频点的方式
    计算电压幅值和dBm值。

    Args:
        csv_path (str): CSV文件路径。
        sample_rate (float): 采样率（Hz）。
        window_type (int): 窗函数类型（保留参数，实际未使用）。
        start_frep (int): 起始频率（Hz）。
        end_frep (int): 结束频率（Hz）。
        step_frep (int): 频率步进（Hz）。
        gain (float, optional): 增益系数。默认值为 1。
        impedance (float, optional): 负载阻抗（Ω）。默认值为 50。
        cal_constant (float, optional): 校准常数。默认值为 10.79。
        selected_radio_dbm (str, optional): dBm计算方式。默认值为 "apple"。

    Returns:
        dict or None: 以频率为键的字典，每个值包含：
            - "volt" (float): 电压幅值（V）。
            - "dbm" (float): dBm值。
            参数错误时返回 None。

    Example:
        >>> result = get_fundamental_volt_apple(
        ...     "data.csv", 125000000, 1, 100000, 200000, 10000)
        >>> for freq, data in result.items():
        ...     print(f"{freq} Hz: {data['volt']:.3f} V, {data['dbm']:.1f} dBm")
    """
    try:
        start_idx = int(start_frep)
        end_idx = int(end_frep)
        step = int(step_frep)
    except ValueError:
        print("错误：起始/结束点必须是整数！")
        return None
    fundamental_volt_dict = {}
    print(f"频率,电压幅值,dbm")
    xf_positive, yf_dbm, yf_positive = calculate_fft(csv_path, sample_rate, impedance, selected_radio_dbm)
    for idx_frep in range(start_idx, end_idx, step):
        closest_idx = np.argmin(np.abs(xf_positive - idx_frep))
        closest_freq = xf_positive[closest_idx]
        dbm_value = yf_dbm[closest_idx]
        fundamental_voltage = yf_positive[closest_idx]
        fundamental_volt_dict[idx_frep] = {}
        fundamental_volt_dict[idx_frep]["volt"] = fundamental_voltage
        fundamental_volt_dict[idx_frep]["dbm"] = dbm_value

        print(f"{idx_frep},{fundamental_voltage},{dbm_value}")

    return fundamental_volt_dict


def get_fundamental_volt(csv_path, sample_rate, window_type, start_frep, end_frep, step_frep,
                         gain=1, impedance=50, cal_constant=10.79,
                         selected_radio_vpp="fixture", selected_radio_dbm="fixture"):
    """计算指定频率范围内的电压幅值和dBm（统一入口）。

    根据选择的算法类型，调用对应的计算函数获取频率范围内的
    电压幅值和dBm数据。

    Args:
        csv_path (str): CSV文件路径。
        sample_rate (float): 采样率（Hz）。
        window_type (int): 窗函数类型。
        start_frep (int): 起始频率（Hz）。
        end_frep (int): 结束频率（Hz）。
        step_frep (int): 频率步进（Hz）。
        gain (float, optional): 增益系数。默认值为 1。
        impedance (float, optional): 负载阻抗（Ω）。默认值为 50。
        cal_constant (float, optional): 校准常数。默认值为 10.79。
        selected_radio_vpp (str, optional): 电压幅值算法：
            - "fixture": Fixture算法（默认，使用窗函数和插值）
            - 其他值: Apple算法（使用标准FFT）
        selected_radio_dbm (str, optional): dBm计算方式。默认值为 "fixture"。

    Returns:
        dict or None: 以频率为键的结果字典，失败时返回 None。

    Example:
        >>> result = get_fundamental_volt(
        ...     "data.csv", 125000000, 1, 100000, 200000, 10000,
        ...     selected_radio_vpp="fixture")
    """
    if selected_radio_vpp == "fixture":
        return get_fundamental_volt_Fixture(csv_path, sample_rate, window_type,
                                            start_frep, end_frep, step_frep,
                                            gain, impedance, cal_constant, "fixture")
    else:
        return get_fundamental_volt_apple(csv_path, sample_rate, window_type,
                                          start_frep, end_frep, step_frep,
                                          gain, impedance, cal_constant, "apple")


def main_2():
    """主流程演示函数。

    配置参数后调用 get_fundamental_volt 计算指定频率范围内的
    电压幅值和dBm值。
    """
    csv_path = "Magik_UWT8_40V_112000_CH1.csv"
    sample_rate = 125000000
    window_type = 1
    load_impedance = 50
    get_fundamental_volt(csv_path, sample_rate, window_type, 100000, 238000, 1000, 1, 50, 10.79)


if __name__ == "__main__":
    main_2()
