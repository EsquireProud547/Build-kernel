# Build-kernel

基于 [CachyOS PKGBUILD](https://github.com/CachyOS/linux-cachyos) 的 GitHub Actions 内核构建工作流。
针对 AMD Ryzen 5 PRO 4650GE 桌面平台，自动构建精简版 Arch Linux 内核包，
共支持 8 个 CachyOS 内核变体。

## 技术栈

| 组件 | 说明 |
|------|------|
| CI 平台 | GitHub Actions (`workflow_dispatch` 手动触发) |
| 构建容器 | `archlinux:latest` |
| 编译器 | Clang/LLVM (LTO 模式可选 thin/full/thin-dist/none) |
| 包管理 | makepkg + PKGBUILD（上游 [linux-cachyos](https://github.com/CachyOS/linux-cachyos)） |
| 配置精简 | Python 3 (`scripts/trim_config.py`) |

## 项目结构

```
.
├── .github/workflows/build-cachyos.yml   # 主构建工作流
├── scripts/trim_config.py                # 内核 .config 精简脚本
├── Agent.md
├── .gitignore
└── LICENSE
```

## 远程仓库

```
git@github.com:EsquireProud547/Build-kernel.git  (分支: main)
```

## 工作流逻辑

1. 用户通过 `workflow_dispatch` 选择：内核变体、LTO 模式、CPU 优化目标、BBR3 开关、是否精简配置
2. CI 在 Arch Linux 容器中安装依赖 → 克隆上游 PKGBUILD → sed 覆写 `KBUILD_BUILD_*`
3. 将 `trim_config.py` 注入 PKGBUILD `prepare()` 末尾（锚点: `### Save configuration for later reuse`）
4. 以非 root 用户执行 `makepkg`，通过环境变量传递构建参数
5. 收集 `.pkg.tar.zst` 和 `.config` 文件，上传为 Artifact（保留 7 天）

## 哲学

- **中文注释** — 所有代码注释、commit message 使用中文
- **简单可控** — 不覆写 PKGBUILD 原生逻辑，只做最小必要改动，保持项目易于理解和维护
