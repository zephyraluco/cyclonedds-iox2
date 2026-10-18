# 三语言共享内存测试

这组用例基于同一个 CycloneDDS SDK，在两个独立进程间对比 UDP、iox2 普通写入和 iox2 writer loan。包含 C、CycloneDDS-cxx，以及官方 [cyclonedds-rust](https://github.com/eclipse-cyclonedds/cyclonedds-rust) 的 Rust 用例。

实测数据、图表和问题分析见 [性能分析报告](../docs/iox2-performance.md)。

## 依赖和构建

测试面向 Linux。需要 C/C++ 编译器、CMake ≥3.22、Rust、Python 3、ACL 开发文件及 libclang 开发文件。Python 驱动只使用标准库；Matplotlib 仅用于可选绘图。

```bash
sudo apt-get update
sudo apt-get install -y build-essential cmake ninja-build pkg-config libacl1-dev libclang-dev git
# 激活已安装的 Rust 工具链，再从仓库根目录运行：
./tools/build.sh --build-cxx
export CYCLONEDDS_HOME="$PWD/install/usr/local"
bash tools/build_benchmarks.sh
```

也可以使用已经安装、启用 `ENABLE_ICEORYX2=ON` 的 CycloneDDS + CycloneDDS-cxx SDK，把 `CYCLONEDDS_HOME` 设为它们共同的安装前缀。**不要启用 Rust 的 `vendored` feature**：它会另行构建 CycloneDDS，不能假定会包含本项目验证过的插件。更换 SDK 前缀时请使用新的 `BENCH_BUILD_DIR`，避免 CMake 缓存引用旧库。

构建产物：

| 文件 | 用途 |
|---|---|
| `build/benchmarks/bench_c` | C DDS API，用 C IDL 描述符 |
| `build/benchmarks/bench_cpp` | CycloneDDS-cxx 的 typed API 和 loan 扩展 |
| `build/benchmarks/rust/release/shm-bench-rust` | 官方 `eclipse-cyclonedds-sys`，Rust 直接管理 DDS 实体、QoS、收发和 loan |
| `build/benchmarks/rust/release/high_level_probe` | 官方 `eclipse-cyclonedds` 高层 API 的独立能力探测 |
| `libbench_types.so` | `idlc` 生成的类型描述符，不含 C 收发逻辑 |
| `libbench_ffi.so` | C 端点及 C/C++ 参数、统计辅助；Rust 性能程序不链接它 |

Rust Git 依赖固定到 `ef0dd5cc1477b29449aba1f717d9496db5953b2a`，并提交 Cargo.lock。它既不是另一个独立 Rust DDS 实现，也不是绕过官方库的自定义 Rust/C 收发封装。

报告的测量 SDK 还启用了上游测试和示例，具体参数见 [sdk-build-options.json](../docs/benchmark-results/2026-10-18/sdk-build-options.json)。常规构建和该 SDK 都通过功能检查；复核性能数字时，请记录自己的 SDK 配置，并在同一个 SDK 内比较三种模式。

## 功能检查

```bash
python3 benchmarks/run.py --samples 64 --warmup 32 --repeats 1 --interop \
  --output benchmarks/results/smoke
python3 benchmarks/check_guards.py --output benchmarks/results/negative-guards
python3 benchmarks/probe_rust_api.py --output benchmarks/results/rust-high-level
```

第一条执行 **72 组**测试：54 组同语言组合（3 语言 × 3 模式 × 3 长度 × 2 窗口），以及 18 组 64 B、窗口 1 的跨语言组合（6 个有向语言对 × 3 模式）。每组创建全新的进程对并校验所有序号和完整 payload。

第二条是 3 组负向检查：明明加载 UDP 配置，却要求程序必须有共享内存能力。三种语言都必须拒绝启动，防止错误配置被报告为共享内存成功。

第三条**单独**报告高层 Rust API 的结果。当前固定提交下，UDP 预期成功；显式加载 iox2 时，会命中未实现的 `from_psmx` 并超时，报告 `unsupported_upstream_psmx_callback`。这个结果不是性能通过，也不会出现在共享内存性能数字中。其他无法解释的失败仍会让命令非零退出。

输出目录已包含 `raw.jsonl` 时，主驱动拒绝覆盖。重跑请换一个目录。任一进程失败、超时、序号错误、payload 损坏、共享内存能力不符，或插件报告收发错误，都会停止运行并保留日志，不输出成功的汇总结果。

## 性能测量

```bash
python3 benchmarks/run.py --samples 2048 --warmup 256 --repeats 5 --interop \
  --output benchmarks/results/performance
```

默认消息大小为 64 B、4096 B、65536 B；默认窗口为 1 和 16。上面的参数产生 270 组性能试验，加 18 组互操作检查，总计 **288 组**。试验顺序按固定 seed `20261018` 随机打散；不并行运行试验组，以免自己制造竞争。

`--languages c cpp rust`、`--modes udp iox2-copy iox2-loan`、`--sizes`、`--windows` 可选择子集。`--prefix` 覆盖 SDK 前缀，`--build` 覆盖可执行文件目录，`--timeout` 限定驱动等待时间。不要在同一输出目录或同一机器上并行跑两次性能测量。

### 协议和计量口径

1. 所有模式保持固定长度 `@final`、无 key 类型，`RELIABLE`、`VOLATILE`、`KEEP_LAST(64)` 一致。
2. 两个进程分别确认收发双方匹配后，由 Python 通过管道发出启动屏障。单方发现完成不代表对端已收到自己的 writer 元数据。
3. 预热全部完成后，客户端输出 `READY`。驱动读取 loopback 和 cgroup CPU 计数，随后发出测量起始信号。
4. 客户端每批发送 `window` 条请求，服务端逐条检查并回送相同序号。每次发送均填充 payload 为 `0xa5`，每次有效接收均完整检查 payload。
5. 窗口 1 报告串行 ping-pong 的完整 RTT，**不除以 2**。窗口 16 的 RTT 含批次内排队，不能当成孤立消息延迟。
6. 有效速率为 `samples × sample_size / elapsed / 2^20`，按一个方向计数；完整工作负载还要回送同样的数据。它是本协议的有效应用速率，不是链路带宽或无回送的单向吞吐极限。
7. 完成握手确认最后一个回复被收到；服务端等客户端断开后销毁 writer，避免短生命周期 publisher 提前回收样本。

`p50`、`p99` 使用经验分位数；汇总是各独立试验数值的中位数，同时保留最小值和最大值。没有根据性能阈值挑选、丢弃或“通过”试验。

### 确认真的使用共享内存

- UDP 配置没有加载 PSMX；两端必须报告共享内存不可用。
- iox2 模式两端必须报告共享内存可用；loan 模式实际调用 writer loan；reader 在有效期内检查数据并归还 loan。
- 每组记录 `loopback_tx_bytes`。开始采样在预热之后，结束在客户端退出之后，因此含完成握手、清理和期间的发现流量，也可能混入宿主机其他 loopback 流量。该计数用于辅助核查，不作为精确抓包结论。
- 查看 64 KiB 长消息时，UDP 大量 loopback 数据与 iox2 仅少量控制流量形成可验证对照。插件可以仍用 UDP 做发现，**不能声称启用共享内存后网络流量为零**。
- `metadata.json` 保存 SDK 和 Rust 提交、工具链、CPU 配额、亲和集合，以及配置、源码、二进制和库文件 SHA-256。

### 运行配置

驱动始终把子进程工作目录设为仓库根目录，加载 `config/iceoryx2.toml`。配置把接收队列设为 64、借用额度设为 128，并关闭 safe overflow。这些值与当前 DDS history 和窗口配套，不能直接推断为任意负载的最佳生产设置。

XML 为本机对照固定选择 loopback。实际多机服务应选择真实接口、评估 QoS，并为隔离的共享内存域设置适当的 instance name。仅复制 XML、不复制/显式加载 iceoryx2 TOML，可能重新触发默认队列覆盖或借用不足。

## 数据、绘图与 CI

每个试验留下 client/server stdout、stderr；`raw.jsonl` 保存每次试验，`summary.json` 保存分组统计，`metadata.json` 保存环境信息。失败时额外留下 `failure.txt`。cgroup CPU 计数是整个容器范围，不能当成进程独占 CPU 消耗。

可选图表：

```bash
python3 -m pip install 'matplotlib==3.11.2'
python3 benchmarks/report.py --results benchmarks/results/performance \
  --output benchmarks/results/report --plot
```

图表误差棒是独立试验的最小/最大值，**不是统计置信区间**。不加 `--plot` 只生成 Markdown 表格，不依赖 Matplotlib。

CI 新增了 C++ SDK 和三语言基准的构建、72 组 smoke、负向检查与 Rust 高层探测，并上传诊断产物。CI 中的 smoke 用于检查功能，不用于与共享 runner 的性能数字做排名。
