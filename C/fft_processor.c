/*********************************************************************
 * FFT频谱分析处理器（C实现，完全对齐 FFT.py 的 Fixture_plus 算法）
 *
 * 功能说明：
 *   1. 直接读取 ADC 原始 bin 文件（4字节小端 uint32），按与
 *      code_to_mvolt.code_to_mvolt2 完全一致的规则解码为电压值。
 *   2. 内置 5 种窗函数（矩形/平顶/汉宁/布莱克曼-哈里斯/Nuttall），
 *      系数与 Python 端逐一对齐。
 *   3. 内置任意点数 FFT：2 的幂走 radix-2，否则走 Bluestein chirp-z，
 *      数学结果与 scipy.fft 完全一致（精确 DFT）。
 *   4. 移植 FFT.py 的全部核心算法：
 *        - 四阶插值精确定位基频（fft_analysis_plus）
 *        - 二次插值提取任意频率幅值（get_frequency_magnitude）
 *        - 基频 RMS（去直流）
 *        - THD 与 THD+N（analyzer_plus）
 *   5. 三种工作模式：
 *        csv  : 读取 bin，解码为电压幅值 CSV（单列，每行一个幅值，不做 FFT）
 *        fft  : 读取 bin/csv，按 start/step/end 频率范围生成三列 CSV
 *               （frequency_hz,magnitude_v,dbm），幅值经加窗FFT+二次插值，
 *               dbm 对齐 FFT.py voltage_to_dbm_Fixture
 *        freq : 读取 bin/csv，给定一个频率，返回基频/RMS/该频率幅值/dbm/THD/THD+N
 *    输入文件按扩展名分派：.csv 直接读取单列幅值；其他按 bin 解码（需 gain）。
 *********************************************************************/

#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>
#include <strings.h>
#include <stdint.h>

#define PI 3.14159265358979323846

typedef struct { double re, im; } complex_t;

/* ============================ 窗函数 ============================ */

static double* rectangular_window(int n) {
    double* w = (double*)malloc(n * sizeof(double));
    for (int i = 0; i < n; i++) w[i] = 1.0;
    return w;
}

static double* nuttall_window(int n) {
    const double a[4] = {0.338946, 0.481973, 0.161054, 0.018027};
    double* w = (double*)malloc(n * sizeof(double));
    for (int i = 0; i < n; i++) {
        double t = 2.0 * PI * i / (n - 1);
        w[i] = a[0] - a[1] * cos(t) + a[2] * cos(2 * t) - a[3] * cos(3 * t);
    }
    return w;
}

static double* hanning_window(int n) {
    double* w = (double*)malloc(n * sizeof(double));
    for (int i = 0; i < n; i++)
        w[i] = 0.54 - 0.46 * cos(2.0 * PI * i / (n - 1));
    return w;
}

static double* blackman_harris_window(int n) {
    const double a[4] = {0.35875, 0.48829, 0.14128, 0.01168};
    double* w = (double*)malloc(n * sizeof(double));
    for (int i = 0; i < n; i++) {
        double b = PI * i / (n - 1);
        w[i] = a[0] - a[1] * cos(2 * b) + a[2] * cos(4 * b) - a[3] * cos(6 * b);
    }
    return w;
}

static double* flattop_window(int n) {
    const double a[5] = {0.21557895, 0.41663158, 0.277263158, 0.083578947, 0.006947368};
    double* w = (double*)malloc(n * sizeof(double));
    for (int i = 0; i < n; i++) {
        double t = 2.0 * PI * i / (n - 1);
        w[i] = a[0] - a[1] * cos(t) + a[2] * cos(2 * t) - a[3] * cos(3 * t) + a[4] * cos(4 * t);
    }
    return w;
}

static double* make_window(int type, int n) {
    switch (type) {
        case 1:  return flattop_window(n);
        case 2:  return hanning_window(n);
        case 3:  return blackman_harris_window(n);
        case 4:  return nuttall_window(n);
        default: return rectangular_window(n);
    }
}

/* 窗函数幅值补偿系数 = n / sum(window) */
static double calc_ampl_factor(const double* w, int n) {
    double s = 0.0;
    for (int i = 0; i < n; i++) s += w[i];
    return (double)n / s;
}

/* ============================ FFT ============================ */

static int is_pow2(int n) { return n > 0 && (n & (n - 1)) == 0; }

/* 原地递归 radix-2 FFT，不做缩放。
 * is_forward=1 正变换 (exp(-i*2π/N))；is_forward=0 逆变换 (exp(+i*2π/N))，调用方自行 /N。 */
static void fft_radix2(complex_t* x, int n, int is_forward) {
    if (n <= 1) return;
    complex_t* even = (complex_t*)malloc((n / 2) * sizeof(complex_t));
    complex_t* odd  = (complex_t*)malloc((n / 2) * sizeof(complex_t));
    for (int i = 0; i < n / 2; i++) { even[i] = x[2 * i]; odd[i] = x[2 * i + 1]; }
    fft_radix2(even, n / 2, is_forward);
    fft_radix2(odd,  n / 2, is_forward);

    double ang = (is_forward ? -1.0 : 1.0) * 2.0 * PI / n;
    complex_t wn = {cos(ang), sin(ang)};
    complex_t w  = {1.0, 0.0};
    for (int i = 0; i < n / 2; i++) {
        complex_t t;
        t.re = w.re * odd[i].re - w.im * odd[i].im;
        t.im = w.re * odd[i].im + w.im * odd[i].re;
        x[i].re      = even[i].re + t.re;
        x[i].im      = even[i].im + t.im;
        x[i + n / 2].re = even[i].re - t.re;
        x[i + n / 2].im = even[i].im - t.im;
        complex_t nw;
        nw.re = w.re * wn.re - w.im * wn.im;
        nw.im = w.re * wn.im + w.im * wn.re;
        w = nw;
    }
    free(even);
    free(odd);
}

/* Bluestein chirp-z，任意点数正变换，结果与 scipy.fft 数值一致。 */
static void fft_bluestein(complex_t* x, int n) {
    int M = 1;
    while (M < 2 * n - 1) M <<= 1;

    complex_t* f = (complex_t*)calloc(M, sizeof(complex_t));
    complex_t* g = (complex_t*)calloc(M, sizeof(complex_t));

    /* f[k] = x[k] * exp(-i*π*k²/n)，g[k] = exp(+i*π*k²/n) */
    for (int k = 0; k < n; k++) {
        double th = PI * fmod((double)k * k, 2.0 * n) / n;
        double c = cos(th), s = sin(th);
        /* exp(-i*th) = (c, -s) ；x * (c,-s) = (x.re*c + x.im*s, x.im*c - x.re*s) */
        f[k].re = x[k].re * c + x[k].im * s;
        f[k].im = x[k].im * c - x[k].re * s;
        g[k].re = c;
        g[k].im = s;
    }
    /* 圆周卷积折回：g[M-k] = g[k] */
    for (int k = 1; k < n; k++) g[M - k] = g[k];

    fft_radix2(f, M, 1);
    fft_radix2(g, M, 1);
    for (int i = 0; i < M; i++) {
        complex_t t;
        t.re = f[i].re * g[i].re - f[i].im * g[i].im;
        t.im = f[i].re * g[i].im + f[i].im * g[i].re;
        f[i] = t;
    }
    fft_radix2(f, M, 0);
    for (int i = 0; i < M; i++) { f[i].re /= M; f[i].im /= M; }

    /* X[k] = h[k] * exp(-i*π*k²/n) */
    for (int k = 0; k < n; k++) {
        double th = PI * fmod((double)k * k, 2.0 * n) / n;
        double c = cos(th), s = sin(th);
        complex_t r;
        r.re = f[k].re * c + f[k].im * s;
        r.im = f[k].im * c - f[k].re * s;
        x[k] = r;
    }
    free(f);
    free(g);
}

/* FFT 派发：2 的幂走 radix-2，否则 Bluestein。 */
static void do_fft(complex_t* x, int n) {
    if (is_pow2(n)) fft_radix2(x, n, 1);
    else fft_bluestein(x, n);
}

/* ============================ 算法移植 ============================ */

/* 二次插值计算目标频率处的幅值（对齐 FFT.get_frequency_magnitude）。
 * mag 为完整 FFT 幅值数组（长度 n），索引裁剪到 [0, n/2-1]。 */
static double get_frequency_magnitude(const double* mag, double target_freq, int n, double fs) {
    double k_target = target_freq * n / fs;
    int k0 = (int)floor(k_target);
    double delta = k_target - k0;
    double m[3];
    for (int i = -1; i <= 1; i++) {
        int idx = k0 + i;
        if (idx < 0) idx = 0;
        if (idx >= n / 2) idx = n / 2 - 1;
        m[i + 1] = mag[idx];
    }
    return m[1] - 0.25 * (m[0] - m[2]) * delta
               + 0.25 * (m[0] - 2.0 * m[1] + m[2]) * delta * delta;
}

/* ADC 解码，与 code_to_mvolt.code_to_mvolt2 完全一致。
 * 取高 12 位，补码还原，code/0x7ff*gain（结果单位与 Python 端一致）。 */
static double decode_code(uint32_t raw, double gain) {
    raw >>= 20;
    int32_t code = (raw >= 0x800) ? (int32_t)(raw - 0x1000) : (int32_t)raw;
    return code / (double)0x7ff * gain;
}

/* 读取 ADC bin（4 字节小端 uint32）并解码为电压数组。 */
static double* read_voltage_bin(const char* path, double gain, int* out_len) {
    FILE* f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long bytes = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (bytes < 4) { fclose(f); *out_len = 0; return NULL; }

    int len = (int)(bytes / 4);
    double* v = (double*)malloc((size_t)len * sizeof(double));
    if (!v) { fclose(f); *out_len = 0; return NULL; }

    for (int i = 0; i < len; i++) {
        uint8_t b[4];
        if (fread(b, 1, 4, f) != 4) { len = i; break; }
        uint32_t code = (uint32_t)b[0] | ((uint32_t)b[1] << 8)
                      | ((uint32_t)b[2] << 16) | ((uint32_t)b[3] << 24);
        v[i] = decode_code(code, gain);
    }
    fclose(f);
    *out_len = len;
    return v;
}

/* 读取单列幅值 CSV（每行一个电压值，格式与 csv 模式/code_to_mvolt 输出一致）。
 * CSV 已是电压值，不再乘增益。 */
static double* read_voltage_csv(const char* path, int* out_len) {
    FILE* f = fopen(path, "r");
    if (!f) return NULL;

    double* v = NULL;
    int len = 0, cap = 0;
    char line[256];
    while (fgets(line, sizeof(line), f)) {
        double val = 0.0;
        if (sscanf(line, "%lf", &val) != 1) continue;
        if (len >= cap) {
            cap = (cap == 0) ? 1024 : cap * 2;
            double* nv = (double*)realloc(v, (size_t)cap * sizeof(double));
            if (!nv) { free(v); fclose(f); *out_len = 0; return NULL; }
            v = nv;
        }
        v[len++] = val;
    }
    fclose(f);
    *out_len = len;
    return v;
}

/* 统一入口：按扩展名分派（.csv 直接读取幅值，否则按 bin 解码）。 */
static double* read_voltage_file(const char* path, double gain, int* out_len) {
    const char* dot = strrchr(path, '.');
    if (dot && (strcasecmp(dot, ".csv") == 0))
        return read_voltage_csv(path, out_len);
    return read_voltage_bin(path, gain, out_len);
}

/* 对电压数据执行加窗 + FFT，返回完整幅值数组(malloc)、补偿系数、点数。 */
static double* compute_spectrum(const double* v, int n, int win_type,
                                double* out_comp) {
    double* w = make_window(win_type, n);
    complex_t* buf = (complex_t*)malloc(n * sizeof(complex_t));
    for (int i = 0; i < n; i++) { buf[i].re = v[i] * w[i]; buf[i].im = 0.0; }
    do_fft(buf, n);

    double* mag = (double*)malloc(n * sizeof(double));
    for (int i = 0; i < n; i++)
        mag[i] = sqrt(buf[i].re * buf[i].re + buf[i].im * buf[i].im);

    *out_comp = calc_ampl_factor(w, n);
    free(w);
    free(buf);
    return mag;
}

/* 四阶插值定位基频，返回基频频率。 */
static double find_fundamental_freq(const double* mag, int n, double fs) {
    int max_idx = 1;
    double max_val = mag[1];
    for (int i = 2; i < n / 2; i++) {
        if (mag[i] > max_val) { max_val = mag[i]; max_idx = i; }
    }
    double y[4] = {mag[max_idx - 1], mag[max_idx],
                   mag[max_idx + 1], mag[max_idx + 2]};
    double delta = (3.0 * (y[2] - y[0]) + (y[3] - y[0]))
                 / (10.0 * y[1] + 3.0 * (y[0] + y[2]) + y[3]);
    return (max_idx + delta) * fs / n;
}

/* 基频 RMS（去直流，对齐 FFT.fft_analysis_plus）。 */
static double calc_fundamental_rms(const double* v, int n) {
    double avg = 0.0;
    for (int i = 0; i < n; i++) avg += v[i];
    avg /= n;
    double sq = 0.0;
    for (int i = 0; i < n; i++) { double d = v[i] - avg; sq += d * d; }
    return sqrt(sq / n);
}

/* THD 与 THD+N（对齐 FFT.analyzer_plus）。
 * bandwidth_hz 默认取 fs/2，harmonic_count 为谐波次数。 */
static void calc_thd(const double* mag, int n, double fs, double fundamental_freq,
                     int harmonic_count, double* out_thd, double* out_thdn) {
    int envelope = 4;
    double harmonic_power = 0.0, fundament_power = 0.0;

    for (int nn = 1; nn <= harmonic_count; nn++) {
        double freq = fundamental_freq * nn;
        if (freq > fs / 2.0) break;
        double k_target = freq * n / fs;
        int k1 = (int)floor(k_target);
        int k2 = k1 + 1;
        double power = 0.0;
        for (int i = k1 - envelope; i <= k2 + envelope; i++) {
            if (i >= 0 && i < n) power += mag[i] * mag[i];
        }
        if (nn == 1) fundament_power = power;
        else harmonic_power += power;
    }

    *out_thd = (fundament_power > 0)
        ? 10.0 * log10(harmonic_power / fundament_power) : 0.0;

    int ignore_bin = 8;
    int bandwidth_index = (int)((fs / 2.0) * n / fs); /* = n/2 */
    double all_power = 0.0;
    for (int i = ignore_bin; i < bandwidth_index; i++) all_power += mag[i] * mag[i];

    *out_thdn = (fundament_power > 0)
        ? 10.0 * log10((all_power - fundament_power) / fundament_power) : 0.0;
}

/* 幅值转 dBm，对齐 FFT.py voltage_to_dbm_Fixture：
 *   Vrms = 幅值 * gain / sqrt(2)
 *   dbm  = 20 * log10(Vrms) + cal_constant + offset
 * 幅值非正时返回 NAN（对数无定义）。 */
static double voltage_to_dbm_fixture(double voltage_amplitude, double gain,
                                     double cal_constant, double offset) {
    if (voltage_amplitude <= 0) return NAN;
    double rms = voltage_amplitude * gain / sqrt(2.0);
    return 20.0 * log10(rms) + cal_constant + offset;
}

/* ============================ 主入口 ============================ */

static void usage(const char* prog) {
    fprintf(stderr, "用法:\n");
    fprintf(stderr, "  解码幅值CSV(bin直接转单列幅值,采样率/窗类型忽略): %s csv <输入.bin> <输出.csv> <采样率> <窗类型> <增益>\n", prog);
    fprintf(stderr, "  查询单频率: %s freq <输入.bin> <目标频率Hz> <采样率> <窗类型> <增益> [谐波数] [dbm_gain] [cal_constant] [offset]\n", prog);
    fprintf(stderr, "  生成FFT幅值CSV(频率,幅值,dbm): %s fft <输入.bin> <输出.csv> <采样率> <窗类型> <增益> <start> <step> <end> [dbm_gain] [cal_constant] [offset]\n", prog);
    fprintf(stderr, "窗类型: 0矩形 1平顶 2汉宁 3布莱克曼-哈里斯 4Nuttall\n");
}

int main(int argc, char** argv) {
    if (argc < 3) { usage(argv[0]); return 1; }

    const char* mode = argv[1];

    if (strcmp(mode, "csv") == 0) {
        if (argc != 7) { usage(argv[0]); return 1; }
        const char* in_path  = argv[2];
        const char* out_path = argv[3];
        /* 采样率/窗类型为兼容占位参数，直接解码模式不使用 */
        double gain = atof(argv[6]);

        int n = 0;
        double* v = read_voltage_bin(in_path, gain, &n);
        if (!v || n < 1) { fprintf(stderr, "读取失败或数据过少: %s\n", in_path); return 2; }

        FILE* fo = fopen(out_path, "w");
        if (!fo) { fprintf(stderr, "无法写出: %s\n", out_path); return 3; }
        /* 单列幅值 CSV，格式与 code_to_mvolt.decode_bin_to_csv 一致 */
        for (int i = 0; i < n; i++)
            fprintf(fo, "%.6f\n", v[i]);
        fclose(fo);

        printf("已生成幅值CSV: %s (共 %d 个采样点)\n", out_path, n);
        free(v);
        return 0;
    }

    if (strcmp(mode, "freq") == 0) {
        if (argc < 7 || argc > 11) { usage(argv[0]); return 1; }
        const char* in_path = argv[2];
        double target = atof(argv[3]);
        double fs   = atof(argv[4]);
        int    win  = atoi(argv[5]);
        double gain = atof(argv[6]);
        int harmonic_count = (argc >= 8) ? atoi(argv[7]) : 5;
        /* 可选 dbm 参数：dbm_gain / cal_constant / offset，默认对齐 FFT.py */
        double dbm_gain     = (argc >= 9)  ? atof(argv[8])  : 1.0;
        double cal_constant = (argc >= 10) ? atof(argv[9])  : 10.79;
        double offset       = (argc >= 11) ? atof(argv[10]) : 0.0;

        int n = 0;
        double* v = read_voltage_file(in_path, gain, &n);
        if (!v || n < 4) { fprintf(stderr, "读取失败或数据过少: %s\n", in_path); return 2; }

        double comp = 0.0;
        double* mag = compute_spectrum(v, n, win, &comp);

        double fundamental_freq = find_fundamental_freq(mag, n, fs);
        double fundamental_amp  = get_frequency_magnitude(mag, fundamental_freq, n, fs)
                                  * comp * 2.0 / n;
        double fundamental_rms  = calc_fundamental_rms(v, n);
        double target_volt      = get_frequency_magnitude(mag, target, n, fs)
                                  * comp * 2.0 / n;
        /* dbm 采用可传参数（对齐 FFT.py voltage_to_dbm_Fixture） */
        double target_dbm       = voltage_to_dbm_fixture(target_volt, dbm_gain, cal_constant, offset);
        double fundamental_dbm  = voltage_to_dbm_fixture(fundamental_amp, dbm_gain, cal_constant, offset);

        double thd = 0.0, thdn = 0.0;
        calc_thd(mag, n, fs, fundamental_freq, harmonic_count, &thd, &thdn);

        printf("基频频率: %.9f Hz\n", fundamental_freq);
        printf("基频RMS: %.9f V\n", fundamental_rms);
        printf("计算频率: %.9f Hz\n", target);
        printf("该频率电压幅值: %.9f V\n", target_volt);
        printf("该频率dbm: %.9f dBm\n", target_dbm);
        printf("基频幅值: %.9f V\n", fundamental_amp);
        printf("基频dbm: %.9f dBm\n", fundamental_dbm);
        printf("THD: %.6f dB\n", thd);
        printf("THD+N: %.6f dB\n", thdn);

        free(v); free(mag);
        return 0;
    }

    if (strcmp(mode, "fft") == 0) {
        if (argc < 11 || argc > 14) { usage(argv[0]); return 1; }
        const char* in_path  = argv[2];
        const char* out_path = argv[3];
        double fs   = atof(argv[4]);
        int    win  = atoi(argv[5]);
        double adc_gain = atof(argv[6]);
        double start = atof(argv[7]);
        double step  = atof(argv[8]);
        double end   = atof(argv[9]);
        /* 可选参数：dbm_gain / cal_constant / offset，默认对齐 FFT.py */
        double dbm_gain     = (argc >= 11) ? atof(argv[10]) : 1.0;
        double cal_constant = (argc >= 12) ? atof(argv[11]) : 10.79;
        double offset       = (argc >= 13) ? atof(argv[12]) : 0.0;

        int n = 0;
        double* v = read_voltage_file(in_path, adc_gain, &n);
        if (!v || n < 2) { fprintf(stderr, "读取失败或数据过少: %s\n", in_path); return 2; }

        double comp = 0.0;
        double* mag = compute_spectrum(v, n, win, &comp);

        FILE* fo = fopen(out_path, "w");
        if (!fo) { fprintf(stderr, "无法写出: %s\n", out_path); return 3; }
        fprintf(fo, "frequency_hz,magnitude_v,dbm\n");
        long long k = 0;
        double freq;
        for (freq = start; freq < end; freq = start + (double)(++k) * step) {
            /* 幅值经加窗FFT + 二次插值（get_frequency_magnitude）+ 补偿归一化 */
            double amp = get_frequency_magnitude(mag, freq, n, fs) * comp * 2.0 / n;
            double dbm = voltage_to_dbm_fixture(amp, dbm_gain, cal_constant, offset);
            fprintf(fo, "%.9f,%.9f,%.9f\n", freq, amp, dbm);
        }
        fclose(fo);

        printf("已生成FFT幅值CSV: %s (共 %lld 个频点, 范围 %.9f ~ %.9f Hz)\n",
               out_path, k, start, start + (double)(k - 1) * step);
        free(v); free(mag);
        return 0;
    }

    usage(argv[0]);
    return 1;
}
