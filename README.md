# cyclonedds-iox2

[![Platform](https://img.shields.io/badge/platform-Linux%20x64%20%7C%20arm64-lightgrey)](#快速开始)

**Eclipse CycloneDDS + iceoryx2 零拷贝共享内存传输集成。**

通过 CycloneDDS 的 [PSMX](https://cyclonedds.io/docs/cyclonedds/latest/shared_memory/shared_memory.html) 插件接口接入 [iceoryx2](https://github.com/eclipse-iceoryx/iceoryx2)，为同机节点提供共享内存传输；固定长度类型结合 loan API 可进一步减少复制。跨机流量仍可使用标准 RTPS/UDP。

## 快速开始

### 依赖（Ubuntu/Debian）

```bash
sudo apt-get install -y build-essential cmake ninja-build pkg-config libacl1-dev git
# Rust（用于编译 iceoryx2 FFI 层）
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
```

### 构建

```bash
git clone --recurse-submodules https://github.com/<your-org>/cyclonedds-iox2.git
cd cyclonedds-iox2
./tools/build.sh
```

构建产物安装至 `install/`（前缀 `/usr/local`），按顺序完成：
1. **iceoryx2** — 编译 Rust FFI 静态库
2. **cyclonedds** — 启用 `ENABLE_ICEORYX2=On`，链接 iceoryx2-c
3. **cyclonedds-cxx**（可选）— 构建 C++ 绑定

#### 构建选项

| 参数 | 说明 |
|---|---|
| `--build-cxx` | 同时编译 cyclonedds-cxx（C++ 绑定）；同时将 iceoryx2 的 `BUILD_CXX` 设为 `ON` |

```bash
# 仅构建 iceoryx2 + cyclonedds（默认）
./tools/build.sh

# 同时构建 cyclonedds-cxx
./tools/build.sh --build-cxx
```

### 打包为 .deb

```bash
./tools/make_deb.sh v1.0.0 /usr/local
# 生成 dist/cyclonedds-iox2_1.0.0_amd64.deb
```

## 使用

将构建产物加入 CMake 搜索路径：

```cmake
cmake -B build -DCMAKE_PREFIX_PATH=/path/to/cyclonedds-iox2/install/usr/local
```

在 CycloneDDS XML 配置中启用 iceoryx2 PSMX 插件：

```xml
<CycloneDDS>
  <Domain>
    <General>
      <Interfaces>
        <NetworkInterface autodetermine="true"/>
        <PubSubMessageExchange type="iox2" priority="1000000"/>
      </Interfaces>
    </General>
  </Domain>
</CycloneDDS>
```

通过 `CYCLONEDDS_URI=/path/to/config.xml` 加载配置。同机端点在类型和 QoS 满足插件条件时可走共享内存；要避免发布端的应用缓冲区复制，应使用 writer loan，并正确归还 reader loan。加载插件不等于所有消息都会零拷贝。

## C / C++ / Rust 共享内存测试与性能对比

可复现的三语言测试、两两互操作、UDP / iox2-copy / iox2-loan 对照，以及实测结果和问题分析见 [测试说明](benchmarks/README.md) 和 [性能分析报告](docs/iox2-performance.md)。

Rust 使用官方 [cyclonedds-rust](https://github.com/eclipse-cyclonedds/cyclonedds-rust)，固定依赖提交；当前高层 API 的 PSMX 接收回调尚未实现，因此共享内存性能用例使用该仓库的 `eclipse-cyclonedds-sys` 直接操作 DDS，另提供高层 API 的独立能力探测。

突发负载还需要为 iceoryx2 的接收缓冲和借用样本设置足够容量。项目提供 [iceoryx2 配置](config/iceoryx2.toml)，从仓库根目录运行时加载；DDS 的 history depth 当前不会自动映射到这些设置。请勿把示例配置不加评估地用于不同队列深度或不同工作目录的生产服务。

## 工作原理

```
应用层 DDS API（C / C++）
        │
Eclipse CycloneDDS
        │  PSMX 插件接口
    psmx_iox2              ← 本仓库核心（psmx_iox2_impl.c）
        │
   iceoryx2 FFI
        │
  共享内存 IPC             ← 同机零拷贝
        ╎
  RTPS / UDP              ← 跨机回退
```

## 子模块

| 子模块 | 上游仓库 |
|---|---|
| `cyclonedds` | [eclipse-cyclonedds/cyclonedds](https://github.com/eclipse-cyclonedds/cyclonedds) |
| `cyclonedds-cxx` | [eclipse-cyclonedds/cyclonedds-cxx](https://github.com/eclipse-cyclonedds/cyclonedds-cxx) |
| `iceoryx2` | [eclipse-iceoryx/iceoryx2](https://github.com/eclipse-iceoryx/iceoryx2) |
