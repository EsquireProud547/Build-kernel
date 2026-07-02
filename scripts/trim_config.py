#!/usr/bin/env python3
"""内核 .config 精简脚本。

目标硬件：AMD R5 4650GE + AMDGPU + RTL8822CE + Realtek 有线网卡。
用法：python3 trim_config.py <输入配置> <输出配置>
说明：仅将 CONFIG_FOO=y/m 改为未启用，不修改非布尔值。
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

CONFIG_SET_RE = re.compile(r"^CONFIG_([A-Za-z0-9_]+)=(.*)$")
CONFIG_NOT_SET_RE = re.compile(r"^# CONFIG_([A-Za-z0-9_]+) is not set$")
ACTIVE_VALUES = {"y", "m"}


@dataclass(frozen=True, slots=True)
class Rule:
    """禁用规则。"""

    category: str
    pattern: str
    mode: str = "ns"

    def matches(self, key: str) -> bool:
        """判断配置名是否命中规则。"""
        if self.mode == "exact":
            return key == self.pattern
        if self.mode == "ns":
            return key == self.pattern or key.startswith(self.pattern + "_")
        if self.mode == "prefix":
            return key.startswith(self.pattern)
        raise ValueError(f"未知匹配模式: {self.mode}")


def rules(category: str, mode: str, patterns: Iterable[str]) -> list[Rule]:
    """批量生成规则。"""
    return [Rule(category, pattern, mode) for pattern in patterns]


def uniq_rules(items: Iterable[Rule]) -> list[Rule]:
    """去重并保持顺序。"""
    seen: set[tuple[str, str, str]] = set()
    result: list[Rule] = []

    for rule in items:
        sig = (rule.category, rule.pattern, rule.mode)
        if sig in seen:
            continue
        seen.add(sig)
        result.append(rule)

    return result


# 保护列表：仅在禁用规则明确命中的情况下才需要加入保护。
# 当前所有禁用规则均为精确/定向匹配，不会误伤核心子系统配置，因此保护列表留空。
KEEP_EXACT: set[str] = set()
KEEP_NS: set[str] = set()


# 禁用列表：只关闭确定不需要且风险较低的功能。
DISABLE_RULES = uniq_rules([
    # 调试和测试
    *rules("debug", "ns", [
        "KASAN", "KMSAN", "KCSAN", "UBSAN", "KCOV",
        "KUNIT", "LKDTM", "FAULT_INJECTION",
        "PROVE_LOCKING", "LOCK_STAT", "LATENCYTOP",
    ]),
    *rules("debug", "prefix", ["TEST_"]),

    # 非目标物理 GPU
    *rules("gpu", "ns", [
        "DRM_I915", "DRM_XE", "DRM_NOUVEAU", "DRM_RADEON",
        "DRM_GMA500", "DRM_AST", "DRM_MGAG200",
        "FB_NVIDIA", "FB_RIVA", "FB_RADEON", "FB_I740", "FB_SIS", "FB_VIA",
    ]),
    *rules("gpu", "exact", [
        "DRM_AMDGPU_SI", "DRM_AMDGPU_CIK", "DRM_AMD_DC_SI", "DRM_AMD_ISP",
    ]),

    # 非目标 Wi-Fi
    *rules("wifi", "prefix", [
        "ATH", "B43", "BRCM", "IWLWIFI", "IWLDVM", "IWLMVM", "IWLMLD",
        "MT76", "RT2X00", "RTL8180", "RTL8187", "RTL8192", "RTL8723",
        "RTL8XXXU", "RTLWIFI", "RTW89",
    ]),

    # 电视、广播、遥控相关媒体功能
    *rules("media", "ns", [
        "MEDIA_ANALOG_TV_SUPPORT", "MEDIA_DIGITAL_TV_SUPPORT",
        "MEDIA_RADIO_SUPPORT", "MEDIA_TEST_SUPPORT", "MEDIA_TUNER",
        "DVB", "RC_CORE", "LIRC", "RADIO", "V4L2_LOOPBACK",
        "VIDEO_TUNER", "VIDEO_TVEEPROM",
    ]),
    *rules("media", "prefix", [
        "DVB_", "IR_", "MEDIA_TUNER_", "RADIO_", "RC_",
    ]),

    # 老旧文件系统
    *rules("fs-old", "ns", [
        "ADFS_FS", "AFFS_FS", "BEFS_FS", "BFS_FS", "CRAMFS", "EFS_FS",
        "GFS2_FS", "HPFS_FS", "JFFS2_FS", "JFS_FS", "MINIX_FS",
        "OCFS2_FS", "OMFS_FS", "QNX4FS_FS", "QNX6FS_FS",
        "REISERFS_FS", "ROMFS_FS", "UBIFS_FS", "UFS_FS", "VXFS_FS",
    ]),

    # 旧总线和小众协议
    *rules("legacy", "ns", [
        "6LOWPAN", "ATM", "AX25", "BATMAN_ADV", "CAN", "FDDI", "FIREWIRE", "GPIB",
        "HIPPI", "HSR", "IEEE1394", "IEEE802154", "ISDN", "LAPB", "MTD",
        "NET_DSA", "NFC", "PARIDE", "PCCARD", "PCMCIA", "QRTR", "TIPC",
        "WIMAX", "X25",
    ]),

    # 企业级网卡、RDMA 及 Intel 桌面/工作站网卡
    # 目标平台使用 Realtek RTL8168/RTL8822CE，以下 Intel 网卡均无用
    *rules("nic", "prefix", [
        "3C", "BE2NET", "BNA", "BNX", "CHELSIO", "CXGB", "FM10K",
        "I40E", "ICE", "INFINIBAND", "IXGB", "MLX",
        "NET_VENDOR_CHELSIO", "NET_VENDOR_EMULEX", "NET_VENDOR_MELLANOX",
        "NET_VENDOR_QLOGIC", "NET_VENDOR_SOLARFLARE", "QED", "QLA", "QLCNIC", "RDMA", "SFC",
        "E1000", "IGB", "IGC", "IAVF", "IGBVF",  # Intel 桌面/工作站网卡
    ]),
    *rules("nic", "ns", ["AMD8111_ETH", "AMD_PHY", "AMD_QDMA", "AMD_XGBE"]),

    # 非目标品牌平台驱动
    *rules("laptop", "prefix", [
        "ACER_", "APPLE_", "ASUS_", "CHROMEOS", "CROS_", "CROS_EC", "DELL_",
        "MSI_", "PANASONIC_", "SAMSUNG_", "SONY_", "SURFACE", "TOSHIBA_",
    ]),
    # 注意：AMD_HSMP / AMD_AE4DMA / AMD_PTDMA 已从此处移出，
    # 它们是 Ryzen PRO 4650GE 平台可用的硬件特性，不应禁用。
    *rules("laptop", "ns", [
        "AMD_ISP_PLATFORM",
        "HP_ACCEL", "HP_BIOSCFG", "HP_ILO", "HP_WATCHDOG", "HP_WMI", "SURFACE3_WMI",
    ]),

    # 多余 HDA codec
    *rules("audio-xtra", "ns", [
        "SND_HDA_CODEC_ANALOG", "SND_HDA_CODEC_CA0110", "SND_HDA_CODEC_CA0132",
        "SND_HDA_CODEC_CIRRUS", "SND_HDA_CODEC_CMEDIA", "SND_HDA_CODEC_CONEXANT",
        "SND_HDA_CODEC_SENARYTECH", "SND_HDA_CODEC_SI3054",
        "SND_HDA_CODEC_SIGMATEL", "SND_HDA_CODEC_VIA", "SND_HDA_SCODEC",
    ]),

    # Intel 平台相关驱动与特性
    # 目标平台为 AMD Ryzen PRO 4650GE，无 Intel 硬件，以下均为 Intel 专属选项
    *rules("intel-pm", "exact", [
        "X86_INTEL_PSTATE",   # Intel P-state 驱动，AMD 使用 amd-pstate / acpi-cpufreq
        "INTEL_IDLE",         # Intel idle 驱动
    ]),
    *rules("intel-sec", "exact", [
        "X86_SGX",                          # Intel Software Guard Extensions
        "X86_SGX_KVM",                      # Intel SGX 虚拟化支持
        "INTEL_TDX_HOST",                   # Intel Trust Domain Extensions
        "X86_USER_SHADOW_STACK",            # CET/Shadow Stack，Zen2 无硬件支持
        "X86_INTEL_MEMORY_PROTECTION_KEYS", # Intel MPK/PKU，Zen2 不支持
        "X86_VMX_FEATURE_NAMES",            # Intel VMX 特性名称字符串表
    ]),
    *rules("intel-platform", "exact", [
        "X86_INTEL_LPSS",            # Intel Low Power Subsystem
        "IOSF_MBI",                  # Intel OnChip System Fabric
        "INTEL_IPS",                 # Intel 图形省电驱动
        "INTEL_PUNIT_IPC",           # Intel PUnit IPC
        "INTEL_VSEC",                # Intel Vendor Specific Extended Capabilities
        "INTEL_TH",                  # Intel Trace Hub
        "INTEL_VBTN",                # Intel 虚拟按钮
        "INTEL_VLPM",                # Intel 虚拟低功耗管理
        "BYTCRC_PMIC_OPREGION",      # Intel Atom/Cherry Trail PMIC
        "CHTCRC_PMIC_OPREGION",
        "XPOWER_PMIC_OPREGION",
        "BXT_WC_PMIC_OPREGION",
        "CHT_WC_PMIC_OPREGION",
        "CHT_DC_TI_PMIC_OPREGION",
        "TPS68470_PMIC_OPREGION",
    ]),
    *rules("intel-platform", "ns", [
        "INTEL_MEI",      # Intel Management Engine Interface
        "INTEL_SCU",      # Intel System Controller Unit
        "INTEL_HID",      # Intel HID 设备驱动
        "INTEL_PMT",      # Intel Platform Monitoring Technology
        "INTEL_IOMMU",    # Intel VT-d，与 AMD-Vi 独立
    ]),
    *rules("intel-dptf", "ns", [
        "ACPI_DPTF",       # Intel Dynamic Platform Thermal Framework
        "DPTF_POWER",
        "DPTF_PCH_FIVR",
    ]),
    *rules("intel-pmu", "ns", [
        "PERF_EVENTS_INTEL_UNCORE",  # Intel uncore 性能事件
        "PERF_EVENTS_INTEL_RAPL",    # Intel RAPL 性能事件
        "PERF_EVENTS_INTEL_CSTATE",  # Intel C-state 性能事件（Intel 专属）
    ]),
])


# 禁止危险前缀规则。
BANNED_PREFIX = {
    "ACPI_", "AMD_", "ATA_", "DRM_", "HID_", "I2C_", "INPUT_", "INTEL_",
    "NET_", "PCI_", "PHY_", "SATA_", "SCSI_", "SND_", "USB_",
}

for _rule in DISABLE_RULES:
    if _rule.mode == "prefix" and _rule.pattern in BANNED_PREFIX:
        raise RuntimeError(f"危险 prefix 规则: {_rule.pattern}")


def parse_config(text: str) -> dict[str, str]:
    """解析 .config。"""
    values: dict[str, str] = {}

    for line in text.splitlines():
        if match := CONFIG_SET_RE.match(line):
            values[match.group(1)] = match.group(2)
        elif match := CONFIG_NOT_SET_RE.match(line):
            values[match.group(1)] = "n"

    return values


def is_protected(key: str) -> bool:
    """判断配置是否受保护。"""
    return key in KEEP_EXACT or any(key == prefix or key.startswith(prefix + "_") for prefix in KEEP_NS)


def first_rule(key: str) -> Rule | None:
    """返回首个命中规则。"""
    for rule in DISABLE_RULES:
        if rule.matches(key):
            return rule
    return None


def trim_config(text: str) -> tuple[str, list[tuple[str, str]]]:
    """执行精简。"""
    output: list[str] = []
    disabled: list[tuple[str, str]] = []

    for line in text.splitlines():
        match = CONFIG_SET_RE.match(line)
        if not match:
            output.append(line)
            continue

        key, value = match.group(1), match.group(2)
        rule = None if value not in ACTIVE_VALUES or is_protected(key) else first_rule(key)

        if rule is None:
            output.append(line)
            continue

        output.append(f"# CONFIG_{key} is not set")
        disabled.append((key, rule.category))

    return "\n".join(output) + "\n", disabled


def validate_protected(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """确认保护项未被关闭。"""
    errors: list[str] = []

    for key, value in sorted(before.items()):
        if value in ACTIVE_VALUES and is_protected(key) and after.get(key) not in ACTIVE_VALUES:
            errors.append(f"CONFIG_{key}: {value} -> {after.get(key)!r}")

    return errors


def counts(values: dict[str, str]) -> tuple[int, int]:
    """统计 y 和 m。"""
    return sum(value == "y" for value in values.values()), sum(value == "m" for value in values.values())


def main() -> int:
    """命令行入口。"""
    if len(sys.argv) != 3:
        print(f"用法: python3 {Path(sys.argv[0]).name} <输入配置> <输出配置>", file=sys.stderr)
        return 1

    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    if not src.exists():
        print(f"错误: 文件不存在: {src}", file=sys.stderr)
        return 2

    src_text = src.read_text(encoding="utf-8", errors="ignore")
    before = parse_config(src_text)
    dst_text, disabled = trim_config(src_text)
    after = parse_config(dst_text)

    errors = validate_protected(before, after)
    if errors:
        print("错误: 保护项被关闭:", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 3

    dst.write_text(dst_text, encoding="utf-8")

    before_y, before_m = counts(before)
    after_y, after_m = counts(after)
    before_total = before_y + before_m
    after_total = after_y + after_m

    print(f"裁剪前: =y {before_y}  =m {before_m}  共 {before_total}")
    print(f"裁剪后: =y {after_y}  =m {after_m}  共 {after_total}")
    print(f"减少: {before_total - after_total} 项 → {dst}")

    if disabled:
        print("分类:")
        for category, count in sorted(Counter(category for _, category in disabled).items()):
            print(f"  {category}: {count}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
