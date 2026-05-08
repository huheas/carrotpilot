/**
 * bench_serial_rate.cc
 * 
 * 对比两种串口读取方案的 gyro 输出频率：
 *   方案A（原始）: 每次 polling_loop 调用 updateData()，只有读到新数据才发消息
 *   方案B（新方案）: 后台线程持续读串口，polling_loop 每次都用最新缓存值发消息
 *
 * 编译：
 *   g++ -O2 -std=c++17 -o bench_serial_rate bench_serial_rate.cc sensors/serial.c \
 *       sensors/wit_c_sdk.c -I. -I../.. -lpthread
 *
 * 用法：
 *   ./bench_serial_rate /dev/ttyUSB0 115200 [测试秒数=5]
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <time.h>
#include <stdint.h>
#include <pthread.h>
#include <atomic>
#include <vector>
#include <mutex>
#include <algorithm>
#include <chrono>

#include "sensors/serial.h"
#include "sensors/wit_c_sdk.h"
#include "sensors/REG.h"

// ─────────────────────────────────────────────
// 工具函数
// ─────────────────────────────────────────────
static uint64_t now_us() {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000ULL + ts.tv_nsec / 1000ULL;
}

static void sleep_us(uint64_t us) {
    struct timespec ts;
    ts.tv_sec = us / 1000000;
    ts.tv_nsec = (us % 1000000) * 1000;
    nanosleep(&ts, nullptr);
}

// WT SDK 回调（两个方案共用）
static int g_serial_fd_shared = -1;

static void sdk_serial_write(uint8_t *data, uint32_t len) {
    if (g_serial_fd_shared >= 0)
        write(g_serial_fd_shared, data, len);
}
static void sdk_delay_ms(uint16_t ms) {
    usleep(ms * 1000);
}
static void sdk_reg_update(uint32_t reg, uint32_t reg_num) {
    // 寄存器更新时记录时间戳（新方案线程安全通知用）
}

// ─────────────────────────────────────────────
// 方案 A：原始方式
//   每次 poll 时调用 read()，没数据就跳过
// ─────────────────────────────────────────────
struct SchemeA_Result {
    double freq_hz;
    double max_gap_ms;
    double avg_gap_ms;
    int total_published;
    int total_skipped;
    std::vector<double> gaps_ms;
};

SchemeA_Result run_scheme_a(int fd, int duration_sec) {
    SchemeA_Result res = {};
    const int POLL_HZ = 104;
    const uint64_t POLL_INTERVAL_US = 1000000ULL / POLL_HZ;

    uint64_t t_start = now_us();
    uint64_t t_end = t_start + (uint64_t)duration_sec * 1000000ULL;
    uint64_t last_pub_us = 0;

    printf("[方案A] 开始测试 %d 秒 @ %dHz轮询...\n", duration_sec, POLL_HZ);

    while (now_us() < t_end) {
        uint64_t loop_start = now_us();

        // 原始方式：每次读串口，没数据就跳过
        unsigned char buf[256];
        int len = read(fd, buf, sizeof(buf));

        if (len > 0) {
            for (int i = 0; i < len; i++) {
                WitSerialDataIn(buf[i]);
            }
            // 有新数据 → 模拟 publish
            uint64_t now = now_us();
            if (last_pub_us > 0) {
                double gap = (now - last_pub_us) / 1000.0;
                res.gaps_ms.push_back(gap);
            }
            last_pub_us = now;
            res.total_published++;
        } else {
            res.total_skipped++;
        }

        // 保持 104Hz 节拍
        uint64_t elapsed = now_us() - loop_start;
        if (elapsed < POLL_INTERVAL_US) {
            sleep_us(POLL_INTERVAL_US - elapsed);
        }
    }

    double total_sec = (now_us() - t_start) / 1e6;
    res.freq_hz = res.total_published / total_sec;

    if (!res.gaps_ms.empty()) {
        double sum = 0;
        for (double g : res.gaps_ms) sum += g;
        res.avg_gap_ms = sum / res.gaps_ms.size();
        res.max_gap_ms = *std::max_element(res.gaps_ms.begin(), res.gaps_ms.end());
    }

    return res;
}

// ─────────────────────────────────────────────
// 方案 B：新方案
//   后台线程持续读串口，polling_loop 每次都发（即使数据未更新）
// ─────────────────────────────────────────────
struct BgReader {
    int fd;
    std::atomic<bool> running{true};
    std::atomic<uint64_t> last_data_us{0};
    std::atomic<int> byte_count{0};
    pthread_t tid;

    static void* thread_fn(void* arg) {
        BgReader* self = (BgReader*)arg;
        unsigned char buf[256];
        while (self->running.load()) {
            int len = read(self->fd, buf, sizeof(buf));
            if (len > 0) {
                for (int i = 0; i < len; i++)
                    WitSerialDataIn(buf[i]);
                self->last_data_us.store(now_us());
                self->byte_count.fetch_add(len);
            } else {
                usleep(500); // 没数据短暂yield，避免空转
            }
        }
        return nullptr;
    }

    void start() {
        pthread_create(&tid, nullptr, thread_fn, this);
    }

    void stop() {
        running.store(false);
        pthread_join(tid, nullptr);
    }
};

struct SchemeB_Result {
    double freq_hz;
    double max_gap_ms;
    double avg_gap_ms;
    int total_published;
    std::vector<double> gaps_ms;
};

SchemeB_Result run_scheme_b(int fd, int duration_sec) {
    SchemeB_Result res = {};
    const int POLL_HZ = 104;
    const uint64_t POLL_INTERVAL_US = 1000000ULL / POLL_HZ;

    printf("[方案B] 启动后台读取线程...\n");

    BgReader bg;
    bg.fd = fd;
    bg.start();

    // 等待后台线程收到首帧数据
    uint64_t wait_start = now_us();
    while (bg.last_data_us.load() == 0 && (now_us() - wait_start) < 2000000ULL) {
        usleep(10000);
    }
    if (bg.last_data_us.load() == 0) {
        printf("[方案B] 警告：2秒内未收到传感器数据！\n");
    } else {
        printf("[方案B] 收到首帧数据，开始 %d 秒测试...\n", duration_sec);
    }

    uint64_t t_start = now_us();
    uint64_t t_end = t_start + (uint64_t)duration_sec * 1000000ULL;
    uint64_t last_pub_us = 0;

    while (now_us() < t_end) {
        uint64_t loop_start = now_us();

        // 新方案：只要后台线程有效就发送（不管有没有新数据）
        if (bg.last_data_us.load() > 0) {
            uint64_t now = now_us();
            if (last_pub_us > 0) {
                double gap = (now - last_pub_us) / 1000.0;
                res.gaps_ms.push_back(gap);
            }
            last_pub_us = now;
            res.total_published++;
        }

        uint64_t elapsed = now_us() - loop_start;
        if (elapsed < POLL_INTERVAL_US) {
            sleep_us(POLL_INTERVAL_US - elapsed);
        }
    }

    bg.stop();

    double total_sec = (now_us() - t_start) / 1e6;
    res.freq_hz = res.total_published / total_sec;

    if (!res.gaps_ms.empty()) {
        double sum = 0;
        for (double g : res.gaps_ms) sum += g;
        res.avg_gap_ms = sum / res.gaps_ms.size();
        res.max_gap_ms = *std::max_element(res.gaps_ms.begin(), res.gaps_ms.end());
    }

    return res;
}

// ─────────────────────────────────────────────
// 分析间隔分布（直方图）
// ─────────────────────────────────────────────
void print_gap_histogram(const std::vector<double>& gaps) {
    int lt5=0, lt10=0, lt15=0, lt20=0, lt50=0, lt100=0, lt200=0, ge200=0;
    for (double g : gaps) {
        if      (g < 5)   lt5++;
        else if (g < 10)  lt10++;
        else if (g < 15)  lt15++;
        else if (g < 20)  lt20++;
        else if (g < 50)  lt50++;
        else if (g < 100) lt100++;
        else if (g < 200) lt200++;
        else              ge200++;
    }
    int total = (int)gaps.size();
    printf("  间隔分布（共%d次发送间隔）:\n", total);
    printf("    <5ms  : %5d (%5.1f%%)\n", lt5,   100.0*lt5/total);
    printf("    5-10ms: %5d (%5.1f%%)\n", lt10,  100.0*lt10/total);
    printf("   10-15ms: %5d (%5.1f%%)\n", lt15,  100.0*lt15/total);
    printf("   15-20ms: %5d (%5.1f%%)\n", lt20,  100.0*lt20/total);
    printf("   20-50ms: %5d (%5.1f%%)\n", lt50,  100.0*lt50/total);
    printf("  50-100ms: %5d (%5.1f%%)\n", lt100, 100.0*lt100/total);
    printf(" 100-200ms: %5d (%5.1f%%)\n", lt200, 100.0*lt200/total);
    printf("   >=200ms: %5d (%5.1f%%)\n", ge200, 100.0*ge200/total);
}

// ─────────────────────────────────────────────
// main
// ─────────────────────────────────────────────
int main(int argc, char* argv[]) {
    const char* device = "/dev/ttyUSB0";
    int baud = 115200;
    int duration = 5;

    if (argc >= 2) device   = argv[1];
    if (argc >= 3) baud     = atoi(argv[2]);
    if (argc >= 4) duration = atoi(argv[3]);

    printf("================================================\n");
    printf("  JY901B 串口读取方案性能对比测试\n");
    printf("  设备: %s  波特率: %d  测试时长: %ds\n", device, baud, duration);
    printf("================================================\n\n");

    // 初始化 WT SDK（两个方案共用同一SDK实例）
    WitInit(WIT_PROTOCOL_NORMAL, 0x50);
    WitSerialWriteRegister(sdk_serial_write);
    WitDelayMsRegister(sdk_delay_ms);
    WitRegisterCallBack(sdk_reg_update);

    // ── 方案 A ──────────────────────────────
    {
        int fd = serial_open(device, baud);
        if (fd < 0) {
            fprintf(stderr, "无法打开串口 %s\n", device);
            return 1;
        }
        g_serial_fd_shared = fd;
        // 清空缓冲区
        tcflush(fd, TCIFLUSH);
        sleep(1); // 等传感器稳定

        SchemeA_Result ra = run_scheme_a(fd, duration);

        printf("\n【方案A 结果 - 原始方式（有数据才发）】\n");
        printf("  发布次数:  %d\n", ra.total_published);
        printf("  跳过次数:  %d\n", ra.total_skipped);
        printf("  实际频率:  %.1f Hz\n", ra.freq_hz);
        printf("  平均间隔:  %.1f ms\n", ra.avg_gap_ms);
        printf("  最大间隔:  %.1f ms\n", ra.max_gap_ms);
        if (!ra.gaps_ms.empty()) print_gap_histogram(ra.gaps_ms);

        close(fd);
        g_serial_fd_shared = -1;
    }

    printf("\n--- 方案切换，等待 2 秒 ---\n\n");
    sleep(2);

    // ── 方案 B ──────────────────────────────
    {
        int fd = serial_open(device, baud);
        if (fd < 0) {
            fprintf(stderr, "无法打开串口 %s\n", device);
            return 1;
        }
        g_serial_fd_shared = fd;
        tcflush(fd, TCIFLUSH);
        sleep(1);

        SchemeB_Result rb = run_scheme_b(fd, duration);

        printf("\n【方案B 结果 - 新方案（后台线程+持续发布）】\n");
        printf("  发布次数:  %d\n", rb.total_published);
        printf("  实际频率:  %.1f Hz\n", rb.freq_hz);
        printf("  平均间隔:  %.1f ms\n", rb.avg_gap_ms);
        printf("  最大间隔:  %.1f ms\n", rb.max_gap_ms);
        if (!rb.gaps_ms.empty()) print_gap_histogram(rb.gaps_ms);

        close(fd);
        g_serial_fd_shared = -1;
    }

    printf("\n================================================\n");
    printf("  对比结论（期望值: ~104Hz, max_gap < 20ms）\n");
    printf("================================================\n");

    return 0;
}
