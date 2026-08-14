"""fft_processor —— 配合 fft_processor.c 的 FFT 处理封装。

不依赖 FFT.py / scipy，全部 FFT 与频谱算法在 fft_processor.c 中完成。
本模块负责：
    1. 校验 fft_processor 可执行文件已存在（缺失时报错，不自动编译）。
    2. 封装三种能力：
        - generate_amplitude_csv() : 读取 ADC bin 文件，直接解码为单列电压
          幅值 CSV（不做 FFT），格式与 code_to_mvolt.decode_bin_to_csv 一致。
        - generate_fft_csv()        : 读取 bin 文件，按 start/step/end 频率范围，
          生成三列 CSV（频率/幅值/dbm），幅值经加窗FFT+二次插值，
          dbm 对齐 FFT.py voltage_to_dbm_Fixture。
        - get_frequency_info()      : 读取 bin 文件，给定一个频率，
          返回基频频率/基频RMS/计算频率/该频率电压幅值/该频率dbm/
          基频幅值/基频dbm/THD/THD+N 等信息。

ADC bin 格式与 code_to_mvolt.decode_bin_to_csv 一致：每 4 字节为一个小端
uint32，由 fft_processor.c 按 code_to_mvolt2 规则解码为电压值。
freq/fft 模式的输入支持 bin 文件或 csv 模式生成的单列幅值 CSV（按扩展名分派）。

命令行用法：
    python fft_processor.py csv  <输入.bin> <输出.csv> <采样率> <窗类型> <增益>
    python fft_processor.py freq <输入.bin> <目标频率Hz> <采样率> <窗类型> <增益> [谐波数] [dbm_gain] [cal_constant] [offset]
    python fft_processor.py fft <输入.bin> <输出.csv> <采样率> <窗类型> <增益> <start> <step> <end> [dbm_gain] [cal_constant] [offset]
窗类型: 0矩形 1平顶 2汉宁 3布莱克曼-哈里斯 4Nuttall
"""

import os
import re
import subprocess

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
C_EXE = os.path.join(PLUGIN_DIR, "fft_processor")

# 默认参数与 Waveform_plugin 默认保持一致
DEFAULT_SAMPLE_RATE = 125000000
DEFAULT_WINDOW = 1            # 平顶窗
DEFAULT_GAIN = 58.3          # ADC 增益（与 code_to_mvolt2 默认一致）
DEFAULT_HARMONIC_COUNT = 5   # 谐波次数


def _check_executable():
    """检查 fft_processor 可执行文件是否存在，不存在则报错（不自动编译）。

    Raises:
        RuntimeError: 可执行文件缺失时抛出，提示用户手动编译。
    """
    if not os.path.exists(C_EXE):
        raise RuntimeError(
            f"未找到 fft_processor 可执行文件：{C_EXE}\n"
            f"请先手动编译：cc -O2 -o fft_processor fft_processor.c -lm"
        )


def generate_amplitude_csv(bin_path, output_csv=None, sample_rate=DEFAULT_SAMPLE_RATE,
                           window_type=DEFAULT_WINDOW, gain=DEFAULT_GAIN):
    """读取 ADC bin 文件，直接解码为单列电压幅值 CSV（不做 FFT）。

    输出格式与 code_to_mvolt.decode_bin_to_csv 一致：每行一个幅值（%.6f）。
    采样率/窗类型仅作参数占位，本模式不参与计算。

    Args:
        bin_path: ADC 原始 bin 文件路径。
        output_csv: 输出 CSV 路径；为 None 时取 bin 同名 .csv。
        sample_rate: 采样率（Hz），占位参数，本模式不使用。
        window_type: 窗函数类型 0-4，占位参数，本模式不使用。
        gain: ADC 增益。

    Returns:
        生成的 CSV 文件路径。
    """
    _check_executable()
    if output_csv is None:
        output_csv = os.path.splitext(bin_path)[0] + "_amp.csv"

    proc = subprocess.run(
        [C_EXE, "csv", bin_path, output_csv,
         str(sample_rate), str(window_type), str(gain)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"fft_processor csv 失败({proc.returncode}): {proc.stderr.strip()}")
    if proc.stdout.strip():
        print(proc.stdout.strip())
    return output_csv


def get_frequency_info(bin_path, target_freq, sample_rate=DEFAULT_SAMPLE_RATE,
                       window_type=DEFAULT_WINDOW, gain=DEFAULT_GAIN,
                       harmonic_count=DEFAULT_HARMONIC_COUNT,
                       dbm_gain=1.0, cal_constant=10.79, offset=0.0):
    """读取 bin/csv 文件，给定频率，返回基频/RMS/该频率幅值/dbm/THD/THD+N 等信息。

    Args:
        bin_path: ADC 原始 bin 文件路径，或 csv 模式生成的单列幅值 CSV 路径。
            （按扩展名分派：.csv 直接读取幅值，否则按 bin 解码。）
        target_freq: 目标频率（Hz）。
        sample_rate: 采样率（Hz）。
        window_type: 窗函数类型 0-4。
        gain: ADC 增益。
        harmonic_count: THD 计算的谐波次数。
        dbm_gain: dbm 计算的增益系数，默认 1.0。
        cal_constant: dbm 校准常数，默认 10.79。
        offset: dbm 偏移量，默认 0.0。

    Returns:
        dict: 键为中文标签（基频频率/基频RMS/计算频率/该频率电压幅值/
        该频率dbm/基频幅值/基频dbm/THD/THD+N），值为 float。
    """
    _check_executable()
    cmd = [C_EXE, "freq", bin_path, str(target_freq),
           str(sample_rate), str(window_type), str(gain), str(harmonic_count),
           str(dbm_gain), str(cal_constant), str(offset)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"fft_processor freq 失败({proc.returncode}): {proc.stderr.strip()}")
    return parse_freq_output(proc.stdout)


def generate_fft_csv(bin_path, output_csv, start_freq, step_freq, end_freq,
                     sample_rate=DEFAULT_SAMPLE_RATE, window_type=DEFAULT_WINDOW,
                     gain=DEFAULT_GAIN, dbm_gain=1.0, cal_constant=10.79, offset=0.0):
    """读取 bin/csv 文件，按 start/step/end 频率范围生成三列 CSV（频率/幅值/dbm）。

    幅值经加窗FFT + 二次插值（get_frequency_magnitude）+ 补偿归一化，
    dbm 对齐 FFT.py voltage_to_dbm_Fixture：
        dbm = 20 * log10(幅值 * dbm_gain / sqrt(2)) + cal_constant + offset

    Args:
        bin_path: ADC 原始 bin 文件路径，或 csv 模式生成的单列幅值 CSV 路径。
            （按扩展名分派：.csv 直接读取幅值，否则按 bin 解码。）
        output_csv: 输出 CSV 路径。
        start_freq: 起始频率（Hz，含）。
        step_freq: 频率步进（Hz）。
        end_freq: 结束频率（Hz，不含）。
        sample_rate: 采样率（Hz）。
        window_type: 窗函数类型 0-4。
        gain: ADC 增益（bin 解码）。
        dbm_gain: dbm 计算的增益系数，默认 1.0。
        cal_constant: dbm 校准常数，默认 10.79。
        offset: dbm 偏移量，默认 0.0。

    Returns:
        生成的 CSV 文件路径。
    """
    _check_executable()
    proc = subprocess.run(
        [C_EXE, "fft", bin_path, output_csv,
         str(sample_rate), str(window_type), str(gain),
         str(start_freq), str(step_freq), str(end_freq),
         str(dbm_gain), str(cal_constant), str(offset)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"fft_processor fft 失败({proc.returncode}): {proc.stderr.strip()}")
    if proc.stdout.strip():
        print(proc.stdout.strip())
    return output_csv


def parse_freq_output(text):
    """解析 fft_processor freq 模式的 stdout 为字典。"""
    info = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(.+?):\s*([-+0-9.eE]+)\s*(.*)$", line)
        if m:
            key = m.group(1).strip()
            info[key] = float(m.group(2))
    return info


def _cli():
    import sys
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    mode = sys.argv[1]
    if mode == "csv":
        if len(sys.argv) != 7:
            print("用法: python fft_processor.py csv <输入.bin> <输出.csv> "
                  "<采样率> <窗类型> <增益>")
            return 1
        generate_amplitude_csv(
            sys.argv[2], sys.argv[3], float(sys.argv[4]),
            int(sys.argv[5]), float(sys.argv[6]))
        return 0

    if mode == "freq":
        if len(sys.argv) < 7 or len(sys.argv) > 11:
            print("用法: python fft_processor.py freq <输入.bin> <目标频率Hz> "
                  "<采样率> <窗类型> <增益> [谐波数] [dbm_gain] [cal_constant] [offset]")
            return 1
        harmonic_count = int(sys.argv[7]) if len(sys.argv) >= 8 else DEFAULT_HARMONIC_COUNT
        kwargs = {}
        if len(sys.argv) >= 9:
            kwargs["dbm_gain"] = float(sys.argv[8])
        if len(sys.argv) >= 10:
            kwargs["cal_constant"] = float(sys.argv[9])
        if len(sys.argv) >= 11:
            kwargs["offset"] = float(sys.argv[10])
        info = get_frequency_info(
            sys.argv[2], float(sys.argv[3]), float(sys.argv[4]),
            int(sys.argv[5]), float(sys.argv[6]), harmonic_count, **kwargs)
        for k, v in info.items():
            print(f"{k}: {v}")
        return 0

    if mode == "fft":
        if len(sys.argv) < 10 or len(sys.argv) > 13:
            print("用法: python fft_processor.py fft <输入.bin> <输出.csv> "
                  "<采样率> <窗类型> <增益> <start> <step> <end> "
                  "[dbm_gain] [cal_constant] [offset]")
            return 1
        kwargs = {}
        if len(sys.argv) >= 11:
            kwargs["dbm_gain"] = float(sys.argv[10])
        if len(sys.argv) >= 12:
            kwargs["cal_constant"] = float(sys.argv[11])
        if len(sys.argv) >= 13:
            kwargs["offset"] = float(sys.argv[12])
        generate_fft_csv(
            sys.argv[2], sys.argv[3],
            float(sys.argv[7]), float(sys.argv[8]), float(sys.argv[9]),
            float(sys.argv[4]), int(sys.argv[5]), float(sys.argv[6]),
            **kwargs)
        return 0

    print(f"未知模式: {mode}")
    print(__doc__)
    return 1


if __name__ == "__main__":
    import sys
    sys.exit(_cli())
