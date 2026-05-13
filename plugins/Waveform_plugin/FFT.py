import math
import csv
import numpy as np
from scipy.fft import fft, fftfreq

# --------------------------
# 1. 窗函数实现（对应原始代码逻辑）
# --------------------------
def hanning_window(n):
    """汉宁窗：适用于频谱分辨率优先的场景"""
    window = np.zeros(n)
    for i in range(n):
        window[i] = 0.54 - 0.46 * math.cos(2 * math.pi * i / (n - 1))
    return window

def blackman_harris_window(n):
    """布莱克曼-哈里斯窗：低频谱泄漏，适用于精确频率测量"""
    a = [0.35875, 0.48829, 0.14128, 0.01168]
    window = np.zeros(n)
    for i in range(n):
        b = math.pi * i / (n - 1)
        window[i] = a[0] - a[1] * math.cos(2 * b) + a[2] * math.cos(4 * b) - a[3] * math.cos(6 * b)
    return window

def flattop_window(n):
    """平顶窗：幅值测量精度最高，适用于电压幅值精确计算（推荐）"""
    a = [0.21557895, 0.41663158, 0.277263158, 0.083578947, 0.006947368]
    window = np.zeros(n)
    for i in range(n):
        theta = 2 * math.pi * i / (n - 1)
        window[i] = (a[0] - a[1] * math.cos(theta) + a[2] * math.cos(2 * theta) 
                    - a[3] * math.cos(3 * theta) + a[4] * math.cos(4 * theta))
    return window

# --------------------------
# 2. CSV数据读取函数（用内置csv模块替换pandas）
# --------------------------
def read_voltage_from_csv(csv_path):
    """
    从CSV文件读取第一列电压数据（无需列名，直接读取索引0对应的列）
    :param csv_path: CSV文件路径（如"raw_voltage_data.csv"）
    :return: 第一列的电压数据数组（numpy.ndarray），读取失败返回None
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

# --------------------------
# 3. FFT分析函数（核心：时域转频域，获取基波幅值）
# --------------------------
def calculate_ampl_factor(window):
    """计算幅值补偿系数（对应原始代码calculateAmplFactor）"""
    return len(window) / np.sum(window)

def get_frequency_magnitude(fft_magnitude, target_freq, n, fs):
    """频率幅值插值计算（提升幅值精度，对应原始代码get_frequency_magnitude）"""
    if fft_magnitude is None:
        return 0.0
    k_target = target_freq * n / fs  # 目标频率对应的FFT索引
    k0 = int(math.floor(k_target))   # 整数索引
    delta = k_target - k0            # 小数偏移量
    # 取目标索引附近3个点的幅值（防止越界）
    mag = np.zeros(3)
    for i in range(-1, 2):
        idx = k0 + i
        idx = max(0, min(idx, n//2 - 1))  # 限制索引在有效范围内
        mag[i+1] = fft_magnitude[idx]
    # 二次插值计算精确幅值
    interpolated = (mag[1] - 0.25 * (mag[0] - mag[2]) * delta 
                   + 0.25 * (mag[0] - 2 * mag[1] + mag[2]) * delta * delta)
    return interpolated

def fft_analysis_one(raw_voltage, sample_rate, window_type=1):
    """
    电压信号FFT分析：获取基波频率与基波电压幅值
    :param raw_voltage: 原始电压数据（numpy.ndarray，从CSV读取）
    :param sample_rate: 采样率（Hz，需与原始数据采集时一致，如125000000即125MHz）
    :param window_type: 窗函数类型（1=平顶窗，2=汉宁窗，3=布莱克曼-哈里斯窗，0=无窗）
    :return: 字典（含基波频率、基波电压幅值、FFT幅值数组）
    """
    if raw_voltage is None or len(raw_voltage) == 0:
        print("FFT分析失败：无有效电压数据")
        return None
    
    size_m = len(raw_voltage)        # 原始数据长度
    size_n = 1
    while size_n < size_m:           # 补零至2的整数次幂（FFT计算效率更高）
        size_n *= 2
    
    # 1. 生成窗函数（若启用）
    window = None
    if window_type > 0:
        if window_type == 1:
            window = flattop_window(size_n)
        elif window_type == 2:
            window = hanning_window(size_n)
        elif window_type == 3:
            window = blackman_harris_window(size_n)
        print(f"启用窗函数：{['无窗', '平顶窗', '汉宁窗', '布莱克曼-哈里斯窗'][window_type]}")
    
    # 2. 信号预处理（加窗 + 补零）
    x = np.zeros(size_n, dtype=np.complex128)  # FFT输入（复数数组）
    for i in range(size_n):
        if i < size_m:
            if window_type > 0:
                x[i] = raw_voltage[i] * window[i]  # 加窗处理
            else:
                x[i] = raw_voltage[i]              # 无窗处理
        else:
            x[i] = 0.0  # 补零（凑2的整数次幂）
    
    # 3. 执行FFT变换（使用scipy.fft，性能更好）
    fft_result = fft(x)
    fft_magnitude = np.abs(fft_result)  # 计算FFT幅值（复数的模）
    
    # 4. 幅值补偿（消除窗函数对幅值的影响）
    compensation = 1.0
    if window_type > 0:
        compensation = calculate_ampl_factor(window)
    
    return fft_magnitude,compensation,size_n,size_m

def fft_analysis(raw_voltage, sample_rate, window_type=1, frequency=1):

    """
    电压信号FFT分析：获取基波频率与基波电压幅值
    :param raw_voltage: 原始电压数据（numpy.ndarray，从CSV读取）
    :param sample_rate: 采样率（Hz，需与原始数据采集时一致，如125000000即125MHz）
    :param window_type: 窗函数类型（1=平顶窗，2=汉宁窗，3=布莱克曼-哈里斯窗，0=无窗）
    :return: 字典（含基波频率、基波电压幅值、FFT幅值数组）
    """
    fft_magnitude,compensation,size_n,size_m = fft_analysis_one(raw_voltage, sample_rate, window_type)
    
    # 7. 计算基波电压幅值（精确值）
    fundamental_voltage = get_frequency_magnitude(
        fft_magnitude, frequency, size_n, sample_rate
    )
    fundamental_voltage *= compensation * 2 / size_m  # 幅值补偿与归一化

    return {
        "fundamental_voltage": fundamental_voltage,      # 基波电压幅值（V）
        "fft_magnitude": fft_magnitude[:size_n//2],      # 正频率部分FFT幅值数组
    }

# --------------------------
# 4. 电压转dbm计算
# --------------------------
def voltage_to_dbm_apple(voltage_amplitude, gain=1.0, impedance=50, cal_constant=10.79):
    """
    由电压幅值计算dbm（假设信号为正弦波，取有效值）
    :param voltage_amplitude: 电压幅值（V，从FFT分析获取）
    :param impedance: 负载阻抗（Ω，默认50Ω，射频场景常用；若为其他场景可调整，如75Ω）
    :return: dbm值（float）
    """
    if voltage_amplitude <= 0 or impedance <= 0:
        print("dbm计算失败：电压幅值或阻抗不能为非正值")
        return None
    # 1. 电压幅值转有效值：正弦波有效值 = 幅值 / √2
    rms_voltage = voltage_amplitude / math.sqrt(2)
    # 2. 计算功率：P = V²/R（单位：W）
    power_watt = (rms_voltage ** 2) / impedance
    # 3. 功率转dbm：dbm = 10×log₁₀(P / 1mW) = 10×log₁₀(P×1000)
    power_mw = power_watt * 1000
    dbm = 10 * math.log10(power_mw)
    return dbm

def voltage_to_dbm_Fixture(voltage_amplitude, gain=1.0, impedance=50, cal_constant=10.79):
    """
    兼容Lua逻辑的dbm计算（含增益修正和硬件校准）
    :param voltage_amplitude: 原始电压幅值（V）
    :param gain: 硬件增益系数（默认1.0，对应Lua的gain2）
    :param impedance: 负载阻抗（默认50Ω）
    :param cal_constant: 校准常数（默认10.79，对应Lua的+10.79）
    :return: dbm值（float）
    """
    if voltage_amplitude <= 0 or impedance <= 0:
        print("dbm计算失败：电压幅值或阻抗不能为非正值")
        return None
    # 1. 增益修正：校准原始幅值
    calibrated_amplitude = voltage_amplitude * gain
    # 2. 幅值→有效值
    rms_voltage = calibrated_amplitude / math.sqrt(2)
    # 3. 有效值→dbm（使用校准常数）
    dbm = 20 * math.log10(rms_voltage) + cal_constant
    return dbm


# 标准逻辑（50Ω）：DBM = 10×log₁₀((1/√2)²/50 ×1000) ≈ -13.01 DBM
# 你的当前逻辑（忽略阻抗）：DBM = 20×log₁₀(1/√2) +10.79 ≈ -3.01 +10.79 = 7.78 DBM

# 标准逻辑 10 * math.log(((amplitude2 * gain / math.sqrt(2))*(amplitude2 * gain / math.sqrt(2))/50*1000),10)
# 当前逻辑 20 * math.log(amplitude2 * gain / math.sqrt(2), 10) + 10.79

def calculate_fft(csv_path,sample_rate,impedance,selected_radio_dbm="apple"):
    voltages = read_voltage_from_csv(csv_path)
    # Calculate FFT
    N = len(voltages)
    yf = fft(voltages)
    # yf（频率域的复数数组，长度和输入完全一致，比如 500K 个复数）。
    # 模长」（用 np.abs(yf) 计算）：对应某个频率成分的「幅值大小」（强度）；。
    # 「相位」（用 np.angle(yf) 计算）：对应某个频率成分的相位信息（你要 dBm 的话暂时用不到）。
    xf = fftfreq(N, 1 / sample_rate)
    # 告诉我们 yf 中每个复数对应的「实际频率（Hz）」，yf[0] 对应 xf[0]
    
    # Get positive frequencies only
    positive_freq_mask = xf >= 0
    xf_positive = xf[positive_freq_mask]
    yf_positive = 2.0 / N * np.abs(yf[positive_freq_mask])#正频率幅值
    if selected_radio_dbm == "apple":
        yf_dbm = np.array([voltage_to_dbm_apple(v, impedance) for v in yf_positive])
    else:
        yf_dbm = np.array([voltage_to_dbm_Fixture(v, impedance) for v in yf_positive])
    return xf_positive, yf_dbm, yf_positive



def get_dbm_by_frequency(csv_path, sample_rate, impedance, target_freq, selected_radio_dbm="apple"):
    xf_positive, yf_dbm, yf_positive= calculate_fft(csv_path, sample_rate, impedance, selected_radio_dbm)
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
    
    return target_dbm,target_Vpp


def get_fundamental_volt_Fixture(csv_path, sample_rate, window_type,start_frep,end_frep,step_frep,gain=1,impedance=50, cal_constant=10.79,selected_radio_dbm="fixture"):
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
    fft_magnitude,compensation,size_n,size_m = fft_analysis_one(raw_voltage, sample_rate, window_type)
    for idx_frep in range(start_idx, end_idx, step): 
        fundamental_voltage = get_frequency_magnitude(
            fft_magnitude, idx_frep, size_n, sample_rate
        )
        fundamental_voltage *= compensation * 2 / size_m  # 幅值补偿与归一化
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

def get_fundamental_volt_apple(csv_path, sample_rate, window_type,start_frep,end_frep,step_frep,gain=1,impedance=50, cal_constant=10.79,selected_radio_dbm="apple"):
    try:
        start_idx = int(start_frep)            
        end_idx = int(end_frep)        
        step = int(step_frep)           
    except ValueError:
        print("错误：起始/结束点必须是整数！")
        return None
    fundamental_volt_dict = {}
    print(f"频率,电压幅值,dbm")
    xf_positive, yf_dbm, yf_positive = calculate_fft(csv_path, sample_rate, impedance,selected_radio_dbm)
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


def get_fundamental_volt(csv_path, sample_rate, window_type,start_frep,end_frep,step_frep,gain=1,impedance=50, cal_constant=10.79,selected_radio_vpp="fixture",selected_radio_dbm="fixture"):

    if selected_radio_dbm == "fixture":
        return get_fundamental_volt_Fixture(csv_path, sample_rate, window_type,start_frep,end_frep,step_frep,gain,impedance, cal_constant,"fixture")
    else:
        return get_fundamental_volt_apple(csv_path, sample_rate, window_type,start_frep,end_frep,step_frep,gain,impedance, cal_constant,"apple")


# --------------------------
# 5. 主流程：串联所有步骤
# --------------------------
def main_2():
    # --------------------------
    # 配置参数（需根据实际情况调整！）
    # --------------------------
    csv_path = "Magik_UUT8_40V_112000_CH1.csv"  # 你的CSV文件路径
    sample_rate = 125000000            # 采样率（Hz，需与原始数据采集时一致，原始代码默认125MHz）
    window_type = 1                    # 窗函数类型（1=平顶窗，推荐用于幅值精确计算）
    load_impedance = 50                # 负载阻抗（Ω，默认50Ω，射频常用）
    get_fundamental_volt(csv_path, sample_rate, window_type,100000,238000,1000,1,50,10.79)

# 运行主流程
if __name__ == "__main__":
    # main()
    main_2()
