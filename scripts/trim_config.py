#!/usr/bin/env python3
"""内核 .config 精简脚本 — 针对 AMD R5 4650GE + RTL8822CE + Realtek 网卡。
用法: python3 trim_config.py <输入> <输出>
只将 CONFIG_FOO=y/m 改为 "# CONFIG_FOO is not set"，不动非布尔值和保护列表。"""

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
    """匹配规则: exact=全等, ns=前缀+下划线族, prefix=纯前缀"""
    category: str
    pattern: str
    mode: str = "ns"

    def matches(self, key: str) -> bool:
        if self.mode == "exact":
            return key == self.pattern
        if self.mode == "ns":
            return key == self.pattern or key.startswith(self.pattern + "_")
        if self.mode == "prefix":
            return key.startswith(self.pattern)
        raise ValueError(f"未知匹配模式: {self.mode}")


def rules(category: str, mode: str, patterns: Iterable[str]) -> list[Rule]:
    return [Rule(category, p, mode) for p in patterns]


def uniq_rules(items: Iterable[Rule]) -> list[Rule]:
    seen: set[tuple[str, str, str]] = set()
    out: list[Rule] = []
    for r in items:
        sig = (r.category, r.pattern, r.mode)
        if sig not in seen:
            seen.add(sig)
            out.append(r)
    return out


# ============================================================
# 保护列表：启动/运行时必需 + 本机硬件
# ============================================================

KEEP_EXACT = {
    # x86 基础
    "64BIT", "X86", "X86_64", "SMP",
    "MODULES", "MODULE_UNLOAD",
    "BINFMT_ELF", "BINFMT_SCRIPT",
    "DEVTMPFS", "PROC_FS", "SYSFS", "TMPFS",
    "CGROUPS", "NAMESPACES", "SECCOMP", "BPF", "BPF_SYSCALL",

    # 固件/平台/PCI/ACPI
    "PCI", "PCI_MSI", "PCI_QUIRKS", "PCIEPORTBUS",
    "ACPI", "DMI", "EFI", "EFI_PARTITION", "EFIVAR_FS",
    "MICROCODE", "CPU_SUP_AMD", "X86_MCE", "X86_MCE_AMD",
    "AMD_NB", "AMD_IOMMU", "X86_AMD_PLATFORM_DEVICE",

    # 存储 + 根文件系统
    "BLOCK", "BLK_DEV", "BLK_DEV_SD",
    "SCSI", "SCSI_MOD", "SCSI_COMMON", "SCSI_DMA",
    "ATA", "SATA_HOST", "SATA_AHCI",
    "XFS_FS", "FS_IOMAP",

    # AMD Renoir/Vega 显卡 + 控制台
    "DRM", "DRM_KMS_HELPER", "DRM_DISPLAY_HELPER",
    "DRM_AMDGPU", "DRM_AMD_DC", "DRM_TTM",
    "FRAMEBUFFER_CONSOLE", "VGA_CONSOLE",

    # Realtek RTL8822CE Wi-Fi + Realtek 网卡
    "NET", "ETHERNET", "NETDEVICES", "PHYLIB", "PHYLINK",
    "R8169", "REALTEK_PHY",
    "WIRELESS", "WLAN", "CFG80211", "MAC80211", "RFKILL",
    "RTW88", "RTW88_CORE", "RTW88_PCI", "RTW88_8822C", "RTW88_8822CE",

    # HDA 音频: Realtek codec + HDMI/DP
    "SOUND", "SND", "SND_TIMER", "SND_PCM", "SND_JACK",
    "SND_HDA", "SND_HDA_CORE", "SND_HDA_INTEL",
    "SND_HDA_CODEC_REALTEK", "SND_HDA_CODEC_REALTEK_LIB",
    "SND_HDA_CODEC_HDMI",

    # USB / HID / 输入
    "USB_SUPPORT", "USB_COMMON", "USB", "USB_PCI",
    "USB_XHCI_HCD", "USB_XHCI_PCI",
    "USB_HID", "USB_STORAGE",
    "HID", "HID_GENERIC",
    "INPUT", "INPUT_EVDEV",
    "SERIO", "SERIO_I8042", "SERIO_LIBPS2",
    "KEYBOARD_ATKBD", "MOUSE_PS2",
    "I2C", "I2C_CHARDEV",
}

KEEP_NS = {
    # 保护子选项族（主键已在 KEEP_EXACT 中）
    "XFS",       # XFS_POSIX_ACL, XFS_ONLINE_SCRUB 等
    "USB_XHCI",  # USB_XHCI_DBGCAP 等（HCD/PCI 已在 KEEP_EXACT）
}


# ============================================================
# 禁用列表：AMD 桌面精简配置
# ============================================================

DISABLE_RULES = uniq_rules([
    # 调试/测试/追踪
    *rules("debug", "ns", [
        "GDB_SCRIPTS", "GCOV", "KASAN", "KMSAN", "KCSAN", "UBSAN", "KCOV",
        "KUNIT", "LKDTM", "FAULT_INJECTION", "NOTIFIER_ERROR_INJECTION", "X86_DECODER_SELFTEST",
        "PROVE_LOCKING", "LOCK_STAT", "LATENCYTOP", "PM_DEBUG", "WQ_WATCHDOG",
    ]),
    *rules("debug", "prefix", ["TEST_"]),
    *rules("trace", "ns", [
        "FTRACE", "FUNCTION_TRACER", "FUNCTION_GRAPH_TRACER", "HIST_TRIGGERS", "KPROBES",
        "KRETPROBES", "UPROBES", "TRACEPOINTS", "TRACING", "DYNAMIC_DEBUG",
        "SCHEDSTATS", "BLK_DEV_IO_TRACE", "FTRACE_SYSCALLS",
    ]),

    # 非目标 GPU（Intel/NVIDIA/VMware/QEMU/老旧显卡）
    *rules("gpu", "ns", [
        "DRM_I915", "DRM_XE", "DRM_NOUVEAU", "DRM_RADEON", "DRM_VMWGFX", "DRM_VBOXVIDEO",
        "DRM_QXL", "DRM_BOCHS", "DRM_CIRRUS_QEMU", "DRM_GMA500", "DRM_AST", "DRM_MGAG200",
        "DRM_UDL", "DRM_VIRTIO_GPU", "DRM_HYPERV", "DRM_XEN", "FB_NVIDIA", "FB_RIVA",
        "FB_RADEON", "FB_I740", "FB_SIS", "FB_VIA", "FB_VIRTUAL", "DRM_PANEL", "DRM_BRIDGE",
        "DRM_TINYDRM", "DRM_SSD130X",
    ]),
    *rules("gpu", "exact", [
        "DRM_AMDGPU_SI", "DRM_AMDGPU_CIK", "DRM_AMD_DC_SI", "DRM_AMD_ISP",
    ]),

    # 非目标 Wi-Fi（保留 RTW88_8822CE 在保护列表中）
    *rules("wifi", "prefix", [
        "ADM8211", "ATH", "AT76C50X", "B43", "BRCM", "CARL9170", "HOSTAP", "IPW2100",
        "IPW2200", "IWLEGACY", "IWLWIFI", "IWLDVM", "IWLMVM", "IWLMLD", "LIBIPW",
        "LIBERTAS", "MAC80211_HWSIM", "MT76", "MWIFIEX", "MWL8K", "ORINOCO", "P54",
        "PLFXLC", "PRISM54", "QTNFMAC", "RSI_91X", "RT2X00", "RT2400PCI", "RT2500PCI",
        "RT2500USB", "RT2800PCI", "RT2800USB", "RT61PCI", "RT73USB", "RTL8180", "RTL8187",
        "RTL8192", "RTL8723", "RTL8XXXU", "RTL_CARDS", "RTLWIFI", "RTW89", "VIRT_WIFI",
        "WFX", "WILC1000", "WL1251", "WL12XX", "WL18XX", "WLCORE", "ZD1211RW",
    ]),
    *rules("wifi-rtw88", "ns", [
        "RTW88_8703B", "RTW88_8723C", "RTW88_8723D", "RTW88_8723X", "RTW88_8723CS",
        "RTW88_8723DE", "RTW88_8723DS", "RTW88_8723DU", "RTW88_8812A", "RTW88_8812AU",
        "RTW88_8814A", "RTW88_8814AE", "RTW88_8814AU", "RTW88_8821A", "RTW88_8821AU",
        "RTW88_8821C", "RTW88_8821CE", "RTW88_8821CS", "RTW88_8821CU", "RTW88_8822B",
        "RTW88_8822BE", "RTW88_8822BS", "RTW88_8822BU", "RTW88_8822CS", "RTW88_8822CU",
        "RTW88_88XXA", "RTW88_USB", "RTW88_SDIO", "RTW88_DEBUG", "RTW88_DEBUGFS",
    ]),

    # 媒体采集/TV/DVB/摄像头
    *rules("media", "ns", [
        "MEDIA_SUPPORT", "MEDIA_CONTROLLER", "MEDIA_CAMERA_SUPPORT", "MEDIA_ANALOG_TV_SUPPORT",
        "MEDIA_DIGITAL_TV_SUPPORT", "MEDIA_RADIO_SUPPORT", "MEDIA_TEST_SUPPORT", "MEDIA_TUNER",
        "DVB", "RC_CORE", "LIRC", "RADIO", "V4L2_LOOPBACK", "VIDEO_DEV", "VIDEOBUF2",
        "VIDEO_V4L2", "VIDEO_TUNER", "VIDEO_TVEEPROM",
    ]),
    *rules("media", "prefix", [
        "DVB_", "IR_", "MEDIA_", "MEDIA_TUNER_", "RADIO_", "RC_", "VIDEO_", "VIDEOBUF2",
        "VIDEO_AD", "VIDEO_AMD_ISP", "VIDEO_APTINA", "VIDEO_AU0828", "VIDEO_BT848", "VIDEO_CCS",
        "VIDEO_CX", "VIDEO_DW", "VIDEO_EM28XX", "VIDEO_ET", "VIDEO_GC", "VIDEO_GO7007",
        "VIDEO_HDPVR", "VIDEO_HI", "VIDEO_IMX", "VIDEO_INTEL_IPU", "VIDEO_IVTV", "VIDEO_MT9",
        "VIDEO_OV", "VIDEO_PVRUSB2", "VIDEO_RDACM", "VIDEO_S5", "VIDEO_SAA", "VIDEO_SOLO6X10",
        "VIDEO_STK1160", "VIDEO_TW", "VIDEO_USBTV", "VIDEO_VICODEC", "VIDEO_VIM", "VIDEO_VISL",
        "VIDEO_VIVID", "VIDEO_ZORAN",
    ]),

    # 非目标文件系统（保持 Btrfs/EROFS/F2FS 不动）
    *rules("fs-old", "ns", [
        "ADFS_FS", "AFFS_FS", "BEFS_FS", "BFS_FS", "CRAMFS", "EFS_FS",
        "GFS2_FS", "HFS_FS", "HFSPLUS_FS", "HPFS_FS", "JFFS2_FS",
        "JFS_FS", "MINIX_FS", "OCFS2_FS", "OMFS_FS", "QNX4FS_FS", "QNX6FS_FS",
        "REISERFS_FS", "ROMFS_FS", "SQUASHFS", "UBIFS_FS", "UFS_FS", "VXFS_FS",
    ]),
    *rules("fs-net", "ns", [
        "9P_FS", "AFS_FS", "CEPH_FS", "CIFS", "CODA_FS", "NET_9P", "NFS_COMMON",
        "NFS_FS", "NFSD", "ORANGEFS_FS", "SMB_SERVER", "SMBDIRECT", "SMBFS",
    ]),
    *rules("fs-net", "prefix", ["9P_", "NFS_"]),

    # 废旧总线/协议/小众网络
    *rules("legacy", "ns", [
        "6LOWPAN", "ATM", "AX25", "BATMAN_ADV", "CAN", "FDDI", "FIREWIRE", "GPIB",
        "HIPPI", "HSR", "IEEE1394", "IEEE802154", "ISDN", "L2TP", "LAPB", "MTD",
        "NET_DSA", "NFC", "OPENVSWITCH", "PARIDE", "PCCARD", "PCMCIA", "QRTR", "TIPC",
        "WIMAX", "X25",
    ]),

    # 虚拟化（桌面无需 KVM/virtio/xen/hyperv）
    *rules("virt", "ns", [
        "ACRN_GUEST", "BHYVE_GUEST", "HYPERV", "INTEL_TDX_GUEST", "JAILHOUSE_GUEST",
        "KVM", "TDX_GUEST_DRIVER", "VBOXGUEST", "VDPA",
        "VHOST", "VIRTIO", "VMWARE_BALLOON", "VMWARE_VMCI", "VMXNET3", "XEN",
    ]),
    *rules("virt", "exact", ["HYPERVISOR_GUEST"]),

    # 企业级/服务器网卡和 RDMA
    *rules("nic", "prefix", [
        "3C", "AQUANTIA", "ATL1", "ATLX", "BE2NET", "BNA", "BNX", "CHELSIO", "CXGB",
        "E1000", "FM10K", "I40E", "ICE", "IGB", "IGC", "INFINIBAND", "IXGB", "MLX",
        "NET_VENDOR_BROADCOM", "NET_VENDOR_CHELSIO", "NET_VENDOR_EMULEX", "NET_VENDOR_INTEL",
        "NET_VENDOR_MELLANOX", "NET_VENDOR_QLOGIC", "NET_VENDOR_SOLARFLARE", "QED", "QLA",
        "QLCNIC", "RDMA", "SFC",
    ]),
    *rules("nic", "ns", ["AMD8111_ETH", "AMD_PHY", "AMD_QDMA", "AMD_XGBE"]),

    # 笔记本/平板平台驱动（桌面不需要）
    *rules("laptop", "prefix", [
        "ACER_", "APPLE_", "ASUS_", "CHROMEOS", "CROS_", "CROS_EC", "DELL_",
        "LENOVO_", "MSI_", "PANASONIC_", "SAMSUNG_", "SONY_", "SURFACE", "THINKPAD_",
        "TOSHIBA_",
    ]),
    *rules("laptop", "ns", [
        "AMD_AE4DMA", "AMD_HSMP", "AMD_ISP_PLATFORM", "AMD_PMC", "AMD_PMF", "AMD_PTDMA",
        "AMD_SFH_HID", "AMDTEE", "HP_ACCEL", "HP_BIOSCFG", "HP_ILO", "HP_WATCHDOG", "HP_WMI",
        "SURFACE3_WMI",
    ]),

    # 触摸屏/数位板/手柄
    *rules("input-xtra", "prefix", [
        "GAMEPORT", "HID_SENSOR_", "HID_WACOM", "INPUT_TABLET", "INPUT_TOUCHSCREEN",
        "JOYSTICK_", "TABLET_USB_", "TOUCHSCREEN_", "WACOM",
    ]),

    # 多余 HDA codec（保留 Realtek + HDMI）
    *rules("audio-xtra", "ns", [
        "SND_HDA_CODEC_ANALOG", "SND_HDA_CODEC_CA0110", "SND_HDA_CODEC_CA0132",
        "SND_HDA_CODEC_CIRRUS", "SND_HDA_CODEC_CMEDIA", "SND_HDA_CODEC_CONEXANT",
        "SND_HDA_CODEC_SENARYTECH", "SND_HDA_CODEC_SI3054", "SND_HDA_CODEC_SIGMATEL",
        "SND_HDA_CODEC_VIA", "SND_HDA_SCODEC",
    ]),

    # 嵌入式传感器/MFD/regulator/电池（发行版 config 默认开启）
    *rules("embedded", "ns", ["IIO", "MFD", "REGULATOR", "POWER_SUPPLY", "PPS", "PTP_1588_CLOCK"]),
    *rules("embedded", "prefix", [
        "BATTERY_", "CHARGER_", "IIO_", "MFD_", "REGULATOR_", "SENSORS_AD", "SENSORS_IIO_",
        "SENSORS_INA", "SENSORS_LM", "SENSORS_MAX", "SENSORS_TPS",
    ]),
])

# 禁止对关键族使用 prefix 模式（太危险）
BANNED_PREFIX = {
    "ACPI_", "AMD_", "ATA_", "DRM_", "HID_", "I2C_", "INPUT_", "INTEL_",
    "NET_", "PCI_", "PHY_", "SATA_", "SCSI_", "SND_", "USB_",
}
for _r in DISABLE_RULES:
    if _r.mode == "prefix" and _r.pattern in BANNED_PREFIX:
        raise RuntimeError(f"危险 prefix 规则: {_r.pattern}")


# ============================================================
# 核心逻辑
# ============================================================

def parse_config(text: str) -> dict[str, str]:
    vals: dict[str, str] = {}
    for line in text.splitlines():
        if m := CONFIG_SET_RE.match(line):
            vals[m.group(1)] = m.group(2)
        elif m := CONFIG_NOT_SET_RE.match(line):
            vals[m.group(1)] = "n"
    return vals


def is_protected(key: str) -> bool:
    return key in KEEP_EXACT or any(key == p or key.startswith(p + "_") for p in KEEP_NS)


def first_rule(key: str) -> Rule | None:
    for r in DISABLE_RULES:
        if r.matches(key):
            return r
    return None


def trim_config(text: str) -> tuple[str, list[tuple[str, str]]]:
    out: list[str] = []
    disabled: list[tuple[str, str]] = []
    for line in text.splitlines():
        m = CONFIG_SET_RE.match(line)
        if not m:
            out.append(line)
            continue
        key, val = m.group(1), m.group(2)
        rule = None if val not in ACTIVE_VALUES or is_protected(key) else first_rule(key)
        if rule is None:
            out.append(line)
        else:
            out.append(f"# CONFIG_{key} is not set")
            disabled.append((key, rule.category))
    return "\n".join(out) + "\n", disabled


def validate_protected(before: dict[str, str], after: dict[str, str]) -> list[str]:
    errs: list[str] = []
    for key, val in sorted(before.items()):
        if val in ACTIVE_VALUES and is_protected(key) and after.get(key) not in ACTIVE_VALUES:
            errs.append(f"CONFIG_{key}: {val} -> {after.get(key)!r}")
    return errs


def counts(vals: dict[str, str]) -> tuple[int, int]:
    return sum(v == "y" for v in vals.values()), sum(v == "m" for v in vals.values())


def main() -> int:
    if len(sys.argv) != 3:
        print(f"用法: python3 {Path(sys.argv[0]).name} <输入> <输出>", file=sys.stderr)
        return 1

    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    if not src.exists():
        print(f"错误: 文件不存在: {src}", file=sys.stderr)
        return 2

    src_text = src.read_text(encoding="utf-8", errors="ignore")
    before = parse_config(src_text)
    dst_text, disabled = trim_config(src_text)
    after = parse_config(dst_text)

    errs = validate_protected(before, after)
    if errs:
        print("错误: 受保护项被误关闭:", file=sys.stderr)
        for e in errs:
            print(f"  {e}", file=sys.stderr)
        return 3

    dst.write_text(dst_text, encoding="utf-8")

    by, bm = counts(before)
    ay, am = counts(after)
    bt, at = by + bm, ay + am
    print(f"裁剪前: =y {by}  =m {bm}  共 {bt}")
    print(f"裁剪后: =y {ay}  =m {am}  共 {at}")
    print(f"减少: {bt - at} 项 → {dst}")

    if disabled:
        print("分类:")
        for cat, n in sorted(Counter(c for _, c in disabled).items()):
            print(f"  {cat}: {n}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
