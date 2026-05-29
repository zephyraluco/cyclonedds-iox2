# cyclonedds-iox2

[![Platform](https://img.shields.io/badge/platform-Linux%20x64%20%7C%20arm64-lightgrey)](#快速开始)

**Eclipse CycloneDDS + iceoryx2 零拷贝共享内存传输集成。**

通过 CycloneDDS 的 [PSMX](https://cyclonedds.io/docs/cyclonedds/latest/shared_memory/shared_memory.html) 插件接口接入 [iceoryx2](https://github.com/eclipse-iceoryx/iceoryx2)，同机节点间数据收发**绕过网络栈、零拷贝传输**，跨机流量仍走标准 RTPS/UDP，对应用层 DDS API 完全透明。

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
    <PSMX>
      <Instances>
        <Instance><Library>psmx_iox2</Library></Instance>
      </Instances>
    </PSMX>
  </Domain>
</CycloneDDS>
```

同机 Publisher/Subscriber 自动走共享内存路径，无需修改任何应用代码。

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
