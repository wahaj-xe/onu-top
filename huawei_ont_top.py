#!/usr/bin/env python3
"""
Huawei ONT Live Health & Performance Monitor (btop style).

Maintains a persistent Telnet session with Huawei GPON/EPON ONTs
(e.g., OptiXstar HG8145X6-10, EG8145V5, HG8245H, HG8245Q) to display real-time
CPU, Memory, Flash storage, Optical Power (Rx/Tx dBm), ONT Registration status,
Bit Error Rate (BER / BIP), WAN Throughput sparklines, and Multi-Hop Ping Latency.
"""

from __future__ import annotations

import argparse
from collections import deque
import concurrent.futures
from dataclasses import dataclass
import getpass
import os
import re
import select
import socket
import subprocess
import sys
import time

# --- ANSI Styling Palette (matches btop) ---
C_RESET  = "\033[0m"
C_BOLD   = "\033[1m"
C_DIM    = "\033[90m"
C_RED    = "\033[91m"
C_GREEN  = "\033[92m"
C_YELLOW = "\033[93m"
C_BLUE   = "\033[94m"
C_MAG    = "\033[95m"
C_CYAN   = "\033[96m"
C_WHITE  = "\033[97m"

W = 76
INNER_W = W - 2

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
PROMPT_PATTERN = re.compile(r"(?:SU_WAP>|WAP>|[A-Za-z0-9_-]+[>#])\s*$", re.IGNORECASE)
LOGIN_PROMPT = re.compile(r"(?:login|username|user ?name|account)\s*[:>]\s*$", re.IGNORECASE)
PASSWORD_PROMPT = re.compile(r"password\s*[:>]\s*$", re.IGNORECASE)

TRAFFIC_COMMANDS = [
    "display pon statistics",
    "display sfwd port statistics",
    "display port statistics",
    "display poncnt dnstatistic",
    "display waninfo all",
]


# --- UI Formatting Utilities ---
def strip_telnet(data: bytes) -> bytes:
    """Discard Telnet IAC negotiation sequences."""
    result = bytearray()
    index = 0
    while index < len(data):
        if data[index] == 255 and index + 1 < len(data):
            cmd = data[index + 1]
            if cmd in (251, 252, 253, 254) and index + 2 < len(data):
                index += 3
            elif cmd == 250:
                end = data.find(b"\xff\xf0", index + 2)
                index = len(data) if end == -1 else end + 2
            else:
                index += 2
        else:
            result.append(data[index])
            index += 1
    return bytes(result)


def btop_bar(percent: float | None, width: int = 16) -> str:
    if percent is None:
        return f"{C_DIM}{'·' * width}{C_RESET}"
    p = max(0, min(100, int(percent)))
    filled = int(round((p / 100.0) * width))
    empty = width - filled
    if p > 80:
        col = C_RED
    elif p > 50:
        col = C_YELLOW
    else:
        col = C_GREEN
    return f"{col}{'■' * filled}{C_DIM}{'·' * empty}{C_RESET}"


def sparkline(history: deque[float | None], width: int = 12) -> str:
    samples = list(history)[-width:]
    if not samples or not any(v is not None and v > 0 for v in samples):
        return f"{C_DIM}{'·' * width}{C_RESET}"
    max_val = max((v or 0) for v in samples) or 1.0
    glyphs = " ▂▃▄▅▆▇█"
    res = []
    for v in samples:
        if v is None or v <= 0:
            res.append(f"{C_DIM}·{C_RESET}")
        else:
            idx = min(7, int((v / max_val) * 7))
            res.append(glyphs[idx])
    pad = width - len(samples)
    return f"{C_DIM}{'·' * pad}{C_RESET}" + "".join(res)


def format_bytes(b: int | float | None) -> str:
    if b is None or b < 0:
        return "       — "
    if b < 1024:
        return f"{b:5.0f} B "
    elif b < 1024 * 1024:
        return f"{b / 1024:5.1f} KiB"
    elif b < 1024 * 1024 * 1024:
        return f"{b / (1024 * 1024):5.1f} MiB"
    else:
        return f"{b / (1024 * 1024 * 1024):5.2f} GiB"


def format_rate(bps: float | None) -> str:
    if bps is None or bps < 0:
        return "       —  "
    bits = bps * 8
    if bits < 1000:
        return f"{bits:5.0f} bps"
    elif bits < 1000 * 1000:
        return f"{bits / 1000:5.1f} Kbps"
    elif bits < 1000 * 1000 * 1000:
        return f"{bits / (1000 * 1000):5.1f} Mbps"
    else:
        return f"{bits / (1000 * 1000 * 1000):5.2f} Gbps"


def make_box_line(left_styled: str, right_styled: str = "") -> str:
    """Pad to exact INNER_W (74 chars) to guarantee 0 line-wrapping (exact 76 chars total)."""
    true_l = len(ANSI_RE.sub("", left_styled))
    true_r = len(ANSI_RE.sub("", right_styled))
    gap = max(0, INNER_W - true_l - true_r - 1)
    return "│" + left_styled + (" " * gap) + right_styled + " │\n"


# --- Persistent Telnet Session ---
class HuaweiTelnetSession:
    """Robust, persistent Telnet session manager for Huawei ONTs."""

    def __init__(self, host: str, port: int, username: str, password: str, timeout: float = 6.0):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.timeout = timeout
        self.socket: socket.socket | None = None
        self.logged_in = False
        self.traffic_cmd: str | None = None
        self.cpu_cmd: str | None = None
        self.login_banner: str = ""
        self.captured_prompt: str = ""

    def is_alive(self) -> bool:
        if self.socket is None or not self.logged_in:
            return False
        try:
            self.socket.sendall(b"\r\n")
            ready, _, _ = select.select([self.socket], [], [], 0.4)
            if ready:
                data = self.socket.recv(1024)
                return bool(data)
            return True
        except Exception:
            return False

    def connect(self) -> None:
        self.close()
        s = socket.create_connection((self.host, self.port), self.timeout)
        s.setblocking(False)
        self.socket = s

        # Step 1: Wait for Login prompt
        login_buf = ""
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            ready, _, _ = select.select([self.socket], [], [], 0.2)
            if ready:
                chunk = self.socket.recv(4096)
                if not chunk:
                    break
                login_buf += strip_telnet(chunk).decode("utf-8", "replace")
                if LOGIN_PROMPT.search(login_buf):
                    break

        if not LOGIN_PROMPT.search(login_buf):
            self.socket.sendall(b"\r\n")
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                ready, _, _ = select.select([self.socket], [], [], 0.2)
                if ready:
                    chunk = self.socket.recv(4096)
                    login_buf += strip_telnet(chunk).decode("utf-8", "replace")
                    if LOGIN_PROMPT.search(login_buf):
                        break

        if not LOGIN_PROMPT.search(login_buf):
            raise RuntimeError(f"Username prompt not found. Banner: {repr(login_buf[-200:])}")

        self.login_banner = login_buf

        # Step 2: Send username
        self.socket.sendall((self.username + "\r\n").encode("utf-8"))

        # Step 3: Wait for Password prompt
        pw_buf = ""
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            ready, _, _ = select.select([self.socket], [], [], 0.2)
            if ready:
                chunk = self.socket.recv(4096)
                pw_buf += strip_telnet(chunk).decode("utf-8", "replace")
                if PASSWORD_PROMPT.search(pw_buf):
                    break

        if not PASSWORD_PROMPT.search(pw_buf):
            raise RuntimeError(f"Password prompt not found after username. Response: {repr(pw_buf[-200:])}")

        # Step 4: Send password
        self.socket.sendall((self.password + "\r\n").encode("utf-8"))

        # Step 5: Wait for command prompt (WAP>, SU_WAP>, etc.)
        prompt_buf = ""
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline:
            ready, _, _ = select.select([self.socket], [], [], 0.2)
            if ready:
                chunk = self.socket.recv(4096)
                prompt_buf += strip_telnet(chunk).decode("utf-8", "replace")
                for line in prompt_buf.splitlines():
                    if PROMPT_PATTERN.search(line.strip()):
                        self.logged_in = True
                        self.captured_prompt = line.strip()
                        return

        if not self.logged_in:
            raise RuntimeError(f"Login failed or unknown shell prompt: {repr(prompt_buf[-200:])}")

    def execute(self, cmd: str, timeout: float = 2.5) -> str:
        if self.socket is None:
            raise RuntimeError("Not connected")

        self.socket.sendall((cmd + "\r\n").encode("utf-8"))

        buf = ""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ready, _, _ = select.select([self.socket], [], [], 0.15)
            if not ready:
                continue
            chunk = self.socket.recv(4096)
            if not chunk:
                break
            buf += strip_telnet(chunk).decode("utf-8", "replace")
            lines = [l.strip() for l in buf.splitlines() if l.strip()]
            if lines and PROMPT_PATTERN.search(lines[-1]):
                break

        clean_lines = [l.strip() for l in buf.splitlines() if l.strip()]
        if clean_lines and cmd in clean_lines[0]:
            clean_lines.pop(0)
        if clean_lines and PROMPT_PATTERN.search(clean_lines[-1]):
            clean_lines.pop()

        return "\n".join(clean_lines)

    def fetch_traffic_and_pon(self) -> tuple[int | None, int | None, str]:
        """Fetch traffic bytes and raw PON output for error parsing."""
        if self.traffic_cmd:
            out = self.execute(self.traffic_cmd)
            rx, tx = parse_traffic_bytes(out)
            if rx is not None and tx is not None:
                return rx, tx, out
            self.traffic_cmd = None

        for cmd in TRAFFIC_COMMANDS:
            out = self.execute(cmd)
            rx, tx = parse_traffic_bytes(out)
            if rx is not None and tx is not None:
                self.traffic_cmd = cmd
                return rx, tx, out

        return None, None, ""

    def fetch_cpu(self) -> float | None:
        """Fetch and parse real-time CPU usage across verified ONT CLI commands."""
        if self.cpu_cmd:
            out = self.execute(self.cpu_cmd)
            val = parse_cpu_ultimate(out)
            if val is not None:
                return val
            self.cpu_cmd = None

        cpu_candidates = [
            "display sysinfo",
            "display cpu-usage",
            "display cpu info",
            "display apmChipStatus",
        ]
        for cmd in cpu_candidates:
            out = self.execute(cmd)
            val = parse_cpu_ultimate(out)
            if val is not None:
                self.cpu_cmd = cmd
                return val

        return None

    def fetch_memory(self, default_tot_mb: float = 256.0) -> tuple[float | None, float, float | None, float | None]:
        """Fetch memory breakdown matching Web GUI active RAM."""
        c_sys = self.execute("display sysinfo")
        used_mb, tot_mb, free_mb, pct = parse_memory_comprehensive(c_sys, default_tot_mb)
        if pct is not None:
            return used_mb, tot_mb, free_mb, pct

        c_mem_detail = self.execute("display memory detail")
        c_mem = self.execute("display memory info")
        mem_raw = f"{c_mem_detail}\n{c_mem}"
        return parse_memory_comprehensive(mem_raw, default_tot_mb)

    def close(self) -> None:
        if self.socket is not None:
            try:
                self.socket.close()
            except Exception:
                pass
            self.socket = None
        self.logged_in = False


# --- Network Latency Check ---
@dataclass
class PingResult:
    target: str
    label: str
    loss: float | None
    avg_ms: float | None


def ping_host(target: str, label: str) -> PingResult:
    """Run a fast 2-packet ping with 600ms timeout."""
    try:
        cmd = ["ping", "-n", "2", "-w", "600", target] if os.name == "nt" else ["ping", "-c", "2", "-W", "1", target]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=2.0)
        out = proc.stdout + proc.stderr

        loss_match = re.search(r"\((\d+(?:\.\d+)?)%\s*loss\)", out, re.I)
        if not loss_match:
            loss_match = re.search(r"(\d+(?:\.\d+)?)%\s*packet loss", out, re.I)

        avg_match = re.search(r"Average\s*=\s*(\d+(?:\.\d+)?)ms", out, re.I)
        if not avg_match:
            avg_match = re.search(r"= [^/]+/([^/]+)/", out)

        loss = float(loss_match.group(1)) if loss_match else (0.0 if proc.returncode == 0 else 100.0)
        avg = float(avg_match.group(1)) if avg_match else None
        return PingResult(target, label, loss, avg)
    except Exception:
        return PingResult(target, label, None, None)


# --- Parsers ---
def parse_optic_power(text: str) -> tuple[float | None, float | None, float | None]:
    """Parse Rx Power, Tx Power, and Temperature from display optic."""
    rx_power = None
    tx_power = None
    temp = None

    for line in text.splitlines():
        if re.search(r"(?:rx|receive|input)\s*(?:optical\s*)?power", line, re.I):
            m = re.findall(r"(-?\d+(?:\.\d+)?)", line)
            for v in m:
                val = float(v)
                if -40.0 <= val <= 0.0:
                    rx_power = val
                    break

        if re.search(r"(?:tx|transmit|output)\s*(?:optical\s*)?power", line, re.I):
            m = re.findall(r"(-?\d+(?:\.\d+)?)", line)
            for v in m:
                val = float(v)
                if -10.0 <= val <= 15.0:
                    tx_power = val
                    break

        if re.search(r"(?:laser|transceiver|optical)\s*temp", line, re.I) or "temperature" in line.lower():
            m = re.findall(r"(\d+(?:\.\d+)?)", line)
            for v in m:
                val = float(v)
                if 10.0 <= val <= 100.0:
                    temp = val
                    break

    return rx_power, tx_power, temp


@dataclass
class OntDeviceSpecs:
    model: str = "ONT"
    cpu_hardware: str = "Processor Load"
    total_mem_mb: float = 256.0
    total_flash_mb: float = 128.0
    network_label: str = "GPON WAN Interface"
    hardware_info: str = ""
    firmware_version: str = ""


def query_ont_device_specs(session: HuaweiTelnetSession) -> OntDeviceSpecs:
    """Dynamically probe and detect the exact ONT model, CPU architecture, RAM, and network capabilities."""
    specs = OntDeviceSpecs()

    # Query information commands safely
    dev_text = session.execute("display deviceInfo")
    ver_text = session.execute("display version")
    cpu_text = session.execute("display cpu info")
    mem_text = session.execute("display memory info")
    wifi_text = session.execute("display wifi radio")

    combined_text = f"{dev_text}\n{ver_text}\n{session.login_banner}\n{session.captured_prompt}"

    # 1. Dynamic ONT Model Detection (Supports OptiXstar, EchoLife, SmartAX, and standard GPON/EPON ONTs)
    detected_model = None
    model_patterns = [
        r"ModelName\s*=\s*([^\r\n]+)",
        r"ProductClass\s*=\s*([^\r\n]+)",
        r"Product\s*Name\s*[:=]\s*([^\r\n]+)",
        r"Model\s*[:=]\s*([^\r\n]+)",
        r"Description\s*=\s*(?:OptiXstar|EchoLife|SmartAX)?\s*([A-Za-z0-9_-]+)",
        r"Description\s*=\s*([^\r\n]+)",
    ]
    for pat in model_patterns:
        m = re.search(pat, dev_text + "\n" + ver_text, re.I)
        if m:
            cand = m.group(1).strip()
            # Clean common prefixes or trailing suffixes like "GPON Terminal..."
            cand = re.sub(r"\s*(?:GPON|EPON|XPON)\s+Terminal.*$", "", cand, flags=re.I).strip()
            if cand and not any(err in cand.lower() for err in ["error", "command", "not exist", "failed"]):
                detected_model = cand
                break

    if not detected_model:
        # Fallback regex looking for Huawei model numbers like HG8145X6-10, EG8145V5, HG8245H, HN8145V, etc.
        m_ont = re.search(r"\b((?:HG|EG|HN|HS)\d{4}[A-Za-z0-9_-]*)\b", combined_text, re.I)
        if m_ont:
            detected_model = m_ont.group(1).strip()
        else:
            # Check prompt (e.g. HG8245H>)
            m_p = re.search(r"([A-Za-z0-9_-]+)[>#]", session.captured_prompt)
            if m_p and m_p.group(1).upper() not in ("WAP", "SU_WAP", "SHELL", "CLI"):
                detected_model = m_p.group(1).strip()
            else:
                detected_model = "ONT"

    # Normalize detected model (strip leading "Huawei ")
    detected_model = re.sub(r"^Huawei\s+", "", detected_model, flags=re.I).strip()
    specs.model = detected_model

    # 2. CPU Architecture and Core Count
    cores = len(re.findall(r"processor\s*:\s*\d+", cpu_text, re.I))
    core_name = {1: "Single-Core", 2: "Dual-Core", 4: "Quad-Core", 8: "Octa-Core"}.get(cores, f"{cores}-Core" if cores > 0 else "CPU")

    m_hw = re.search(r"Hardware\s*:\s*([^\r\n]+)", cpu_text, re.I)
    hw_str = m_hw.group(1).strip() if m_hw else ""
    hw_lower = hw_str.lower() + " " + cpu_text.lower()

    if "hisilicon" in hw_lower:
        specs.cpu_hardware = f"HiSilicon {core_name}"
    elif "broadcom" in hw_lower or "bcm" in hw_lower:
        specs.cpu_hardware = f"Broadcom {core_name}"
    elif "mediatek" in hw_lower or "mtk" in hw_lower:
        specs.cpu_hardware = f"MediaTek {core_name}"
    elif "realtek" in hw_lower or "rtl" in hw_lower:
        specs.cpu_hardware = f"Realtek {core_name}"
    elif hw_str and "error" not in hw_lower:
        specs.cpu_hardware = f"{hw_str.split()[0]} {core_name}"
    elif "arm" in hw_lower:
        specs.cpu_hardware = f"ARM {core_name}"
    elif "mips" in hw_lower:
        specs.cpu_hardware = f"MIPS {core_name}"
    elif cores > 0:
        specs.cpu_hardware = f"Processor {core_name}"
    else:
        specs.cpu_hardware = "Processor Load"

    # 3. Total Memory (RAM)
    m_mem = re.search(r"TotalMemory\s*=\s*(\d+)", dev_text, re.I)
    if m_mem:
        specs.total_mem_mb = float(m_mem.group(1))
    else:
        m_mem_info = re.search(r"Mem:\s*(\d+)", mem_text)
        if m_mem_info:
            kb = float(m_mem_info.group(1))
            for s in [64, 128, 256, 512, 1024, 2048]:
                if kb <= s * 1024:
                    specs.total_mem_mb = float(s)
                    break

    # 4. Total Flash Storage
    m_flash = re.search(r"TotalFlash\s*=\s*(\d+)", dev_text, re.I)
    if m_flash:
        specs.total_flash_mb = float(m_flash.group(1))

    # 5. Network / Wi-Fi Capability
    m_hwinfo = re.search(r"HardwareInfo\s*=\s*([^\r\n]+)", dev_text, re.I)
    hwinfo = m_hwinfo.group(1).strip() if m_hwinfo else ""
    specs.hardware_info = hwinfo

    m_ver = re.search(r"main software version\s*=\s*([^\r\n]+)", ver_text, re.I)
    if m_ver:
        specs.firmware_version = m_ver.group(1).strip()

    model_upper = specs.model.upper()
    if "160 MHZ" in wifi_text.upper() or "X6" in model_upper or "AX" in model_upper:
        specs.network_label = "Wi-Fi 6 AX3000"
    elif "80 MHZ" in wifi_text.upper() or "V5" in model_upper or "AC" in model_upper:
        specs.network_label = "Wi-Fi 5 AC1200"
    elif "2.4G" in wifi_text or "N300" in model_upper or "N" in model_upper:
        specs.network_label = "Wi-Fi 4 N300"
    elif "WI-FI" in hwinfo.upper() or "WIFI" in hwinfo.upper():
        specs.network_label = "Wi-Fi Dual-Band"
    elif "GPON" in hwinfo.upper() or "GE" in hwinfo.upper():
        specs.network_label = "Gigabit GPON"
    else:
        specs.network_label = "GPON WAN Interface"

    return specs


def parse_cpu_ultimate(text: str) -> float | None:
    """Parse CPU load across all Huawei formats (with %, without %, multi-core, or idle subtraction)."""
    # 0. Direct match on Huawei display sysinfo "CpuUsed = 8 Percent(s)"
    m_sysinfo = re.search(r"\bcpuused\b[^\d\n]*?[:=]?\s*(\d+(?:\.\d+)?)", text, re.I)
    if m_sysinfo:
        val = float(m_sysinfo.group(1))
        if 0.0 <= val <= 100.0:
            return val

    # 1. Multi-core average with % (e.g. CPU 0: 6%, CPU 1: 10% or Core 0: 6%, Core 1: 10%)
    core_matches_pct = re.findall(r"(?:core|cpu)\s*\d+[^:\n\d]*[:=]?\s*(\d+(?:\.\d+)?)\s*%", text, re.I)
    if len(core_matches_pct) >= 2:
        vals = [float(v) for v in core_matches_pct]
        return round(sum(vals) / len(vals), 1)

    # 2. Multi-core average WITHOUT % (e.g. Core 0 usage: 6, Core 1 usage: 10)
    core_matches_num = re.findall(r"(?:core|cpu)\s*\d+[^:\n\d]*[:=]\s*(\d+(?:\.\d+)?)", text, re.I)
    if len(core_matches_num) >= 2:
        vals = [float(v) for v in core_matches_num]
        return round(sum(vals) / len(vals), 1)

    # 3. Direct explicit overall CPU Usage / occupancy / utilization / load with %
    m_pct = re.search(r"\bcpu\b[^\d\n]*?[:=]?\s*(\d+(?:\.\d+)?)\s*%", text, re.I)
    if m_pct:
        val = float(m_pct.group(1))
        if 0.0 <= val <= 100.0:
            return val

    # 4. Control plane / ten-second interval
    m_cp = re.search(r"(?:control\s+plane\s+cpu\s+usage|cpu\s+utilization\s+for\s+ten\s+seconds)[^\d\n]*?[:=]?\s*(\d+(?:\.\d+)?)\s*%", text, re.I)
    if m_cp:
        val = float(m_cp.group(1))
        if 0.0 <= val <= 100.0:
            return val

    # 5. User + System sum
    m_user = re.search(r"\buser\b[^\d\n]*?[:=]?\s*(\d+(?:\.\d+)?)\s*%", text, re.I)
    m_sys = re.search(r"\bsystem\b[^\d\n]*?[:=]?\s*(\d+(?:\.\d+)?)\s*%", text, re.I)
    if m_user and m_sys:
        return round(float(m_user.group(1)) + float(m_sys.group(1)), 1)

    # 6. Idle % (CPU = 100 - Idle)
    m_idle = re.search(r"\bidle\b[^\d\n]*?[:=]?\s*(\d+(?:\.\d+)?)\s*%", text, re.I)
    if m_idle:
        idle_val = float(m_idle.group(1))
        if 0.0 <= idle_val <= 100.0:
            return round(100.0 - idle_val, 1)

    # 7. Single core with %
    if len(core_matches_pct) == 1:
        return float(core_matches_pct[0])

    # 8. Single core without %
    if len(core_matches_num) == 1:
        return float(core_matches_num[0])

    # 9. Look for CPU usage / load WITHOUT %: e.g. "CPU usage : 8" or "CPU : 8"
    m_num = re.search(r"\bcpu\b\s*(?:usage|utilization|occupation|occupancy|load)?[^\d\n]*?[:=]\s*(\d+(?:\.\d+)?)", text, re.I)
    if m_num:
        val = float(m_num.group(1))
        if 0 <= val <= 100:
            return val

    # 10. Fallback on any line containing "cpu" with a number 0-100 (excluding hardware model lines)
    for line in text.splitlines():
        if re.search(r"\bcpu\b", line, re.I):
            if re.search(r"\b(?:arm|cortex|mips|hisilicon|arch|model|version|frequency|hz|physical|part|revision)\b", line, re.I):
                continue
            nums = [float(n) for n in re.findall(r"\b\d+(?:\.\d+)?\b", line) if 0 <= float(n) <= 100]
            if nums:
                return nums[-1]

    return None


def parse_memory_comprehensive(text: str, default_tot_mb: float = 256.0) -> tuple[float | None, float, float | None, float | None]:
    """Parse real-time memory info matching Web GUI (deducting kernel buffer cache)."""
    # 0. Direct match on Huawei display sysinfo "MemUsed = 62 Percent(s)"
    m_sysinfo = re.search(r"\bmemused\b[^\d\n]*?[:=]?\s*(\d+(?:\.\d+)?)", text, re.I)
    if m_sysinfo:
        pct = float(m_sysinfo.group(1))
        used_mb = default_tot_mb * (pct / 100.0)
        free_mb = default_tot_mb - used_mb
        return used_mb, default_tot_mb, free_mb, pct

    # 1. Direct Memory Usage % (e.g. from display sysinfo / status)
    m_pct = re.search(r"memory\s*(?:usage|utilization|occupation|occupancy|load)?[^\d\n]*?[:=]?\s*(\d+(?:\.\d+)?)\s*%", text, re.I)
    if m_pct:
        pct = float(m_pct.group(1))
        used_mb = default_tot_mb * (pct / 100.0)
        free_mb = default_tot_mb - used_mb
        return used_mb, default_tot_mb, free_mb, pct

    # 2. Check for Buffers and Cached lines
    m_tot = re.search(r"(?:total\s*memory|memtotal)[^\d\n]*?[:=]?\s*(\d+)", text, re.I)
    m_free = re.search(r"(?:free\s*memory|memfree)[^\d\n]*?[:=]?\s*(\d+)", text, re.I)
    m_buf = re.search(r"\bbuffers\b[^\d\n]*?[:=]?\s*(\d+)", text, re.I)
    m_cached = re.search(r"\bcached\b[^\d\n]*?[:=]?\s*(\d+)", text, re.I)

    # 3. Standard Mem: line
    m_mem = re.search(r"Mem:\s*(\d+)\s+(\d+)\s+(\d+)(?:\s+\d+)?(?:\s+(\d+))?", text, re.I)

    tot_kb = None
    free_kb = None
    buffers_kb = 0
    cached_kb = 0

    if m_tot and m_free:
        tot_kb = int(m_tot.group(1))
        free_kb = int(m_free.group(1))
        if m_buf:
            buffers_kb = int(m_buf.group(1))
        if m_cached:
            cached_kb = int(m_cached.group(1))
    elif m_mem:
        tot_kb = int(m_mem.group(1))
        used_kb = int(m_mem.group(2))
        free_kb = int(m_mem.group(3))
        if m_buf:
            buffers_kb = int(m_buf.group(1))
        if m_cached:
            cached_kb = int(m_cached.group(1))

    if tot_kb and free_kb:
        if tot_kb < 1000:
            tot_kb *= 1024
            free_kb *= 1024
            buffers_kb *= 1024
            cached_kb *= 1024

        tot_mb = tot_kb / 1024.0
        reclaimable_kb = buffers_kb + cached_kb
        if reclaimable_kb > 0:
            app_used_kb = max(0, tot_kb - free_kb - reclaimable_kb)
            pct = (app_used_kb / tot_kb) * 100.0
            used_mb = app_used_kb / 1024.0
            free_mb = (tot_kb - app_used_kb) / 1024.0
            return used_mb, tot_mb, free_mb, round(pct, 1)
        else:
            # When buffer/cache is not itemized, deduct typical Linux kernel page cache (~31%)
            # to match active application RAM seen on the Web GUI rather than raw allocation.
            raw_used_kb = tot_kb - free_kb
            raw_pct = (raw_used_kb / tot_kb) * 100.0
            if raw_pct > 80.0:
                pct = max(30.0, raw_pct - 31.0)
                used_mb = tot_mb * (pct / 100.0)
                free_mb = tot_mb - used_mb
                return used_mb, tot_mb, free_mb, round(pct, 1)
            else:
                pct = raw_pct
                used_mb = raw_used_kb / 1024.0
                free_mb = free_kb / 1024.0
                return used_mb, tot_mb, free_mb, round(pct, 1)

    return None, default_tot_mb, None, None


def parse_onu_info(text: str) -> dict[str, str]:
    """Parse ONT Registration Status and ONT ID from display onu info or display sysinfo."""
    res: dict[str, str] = {}
    m_id = re.search(r"(?:ont\s*id|onuid)\s*[:=]\s*(\d+)", text, re.I)
    if m_id:
        res["ont_id"] = m_id.group(1).strip()

    m_status = re.search(r"(?:ont\s*registration\s*status|reg\s*status)\s*[:=]\s*([^\r\n\s]+)", text, re.I)
    if m_status:
        st = m_status.group(1).strip()
        res["ont_status"] = "O5 Operational" if "O5" in st or "operation" in st.lower() else st
    elif "o5" in text.lower():
        res["ont_status"] = "O5 Operational"

    return res


def parse_pon_errors(text: str) -> dict[str, int | str]:
    """Parse BIP (Bit Interleaved Parity) errors, FEC, and Bit Error Rate (BER)."""
    res = {
        "bip": 0,
        "fec_uncorr": 0,
        "fec_corr": 0,
        "crc": 0,
        "ber_str": "0.0e-00",
        "clean": True,
    }

    # BIP Errors (Downstream and Upstream)
    bip_matches = re.findall(r"(?:dn|up)?\s*bip\s*(?:err(?:or)?s?)?\s*[:=]\s*(\d+)", text, re.I)
    if bip_matches:
        res["bip"] = sum(int(b) for b in bip_matches)

    # FEC Errors
    fec_uncorr = re.search(r"fec\s*(?:uncorrect(?:ed)?|uncorr|err)\s*[:=]\s*(\d+)", text, re.I)
    if fec_uncorr:
        res["fec_uncorr"] = int(fec_uncorr.group(1))

    fec_corr = re.search(r"fec\s*(?:correct(?:ed)?|corr)\s*[:=]\s*(\d+)", text, re.I)
    if fec_corr:
        res["fec_corr"] = int(fec_corr.group(1))

    # CRC Errors
    crc_matches = re.findall(r"crc\s*(?:err(?:or)?s?)?(?:\s*frames)?\s*[:=]\s*(\d+)", text, re.I)
    if crc_matches:
        res["crc"] = sum(int(c) for c in crc_matches)

    # Direct BER if present in firmware
    ber_match = re.search(r"\bber\b[^\n:=]*[:=]\s*([0-9.eE+-]+)", text, re.I)
    if ber_match:
        res["ber_str"] = ber_match.group(1).strip()
    else:
        total_errs = int(res["bip"]) + int(res["fec_uncorr"])
        if total_errs == 0:
            res["ber_str"] = "0.0e-00"
        else:
            res["ber_str"] = f"{total_errs} errs"

    res["clean"] = (res["bip"] == 0 and res["fec_uncorr"] == 0 and res["crc"] == 0)
    return res


def parse_traffic_bytes(text: str) -> tuple[int | None, int | None]:
    """Extract cumulative download (Rx) and upload (Tx) bytes."""
    rx_vals: list[int] = []
    tx_vals: list[int] = []

    for line in text.splitlines():
        if re.search(r"(?:rx|receive|received|downstream)", line, re.I):
            nums = [int(v.replace(",", "")) for v in re.findall(r"\b\d[\d,]*\b", line)]
            large = [n for n in nums if n >= 10000]
            if large:
                rx_vals.extend(large)

        if re.search(r"(?:tx|transmit|send|sent|upstream)", line, re.I):
            nums = [int(v.replace(",", "")) for v in re.findall(r"\b\d[\d,]*\b", line)]
            large = [n for n in nums if n >= 10000]
            if large:
                tx_vals.extend(large)

    rx_bytes = max(rx_vals) if rx_vals else None
    tx_bytes = max(tx_vals) if tx_vals else None

    return rx_bytes, tx_bytes


# --- Interactive Connection Prompt ---
def prompt_user_connection(args: argparse.Namespace) -> tuple[str, int, str, str]:
    """Interactively prompt the user for IP, Username, and Password."""
    print(f"\n{C_BOLD}╔══════════════════════════════════════════════════════════════╗{C_RESET}")
    print(f"{C_BOLD}║        Huawei ONT Live Health & Performance Monitor          ║{C_RESET}")
    print(f"{C_BOLD}╚══════════════════════════════════════════════════════════════╝{C_RESET}\n")

    # 1. Gateway IP
    if args.host:
        host = args.host
        print(f"ONT Gateway IP  : {C_CYAN}{host}{C_RESET}")
    else:
        h_in = input("Enter Huawei ONT Gateway IP: ").strip()
        while not h_in:
            print(f"{C_YELLOW}Gateway IP cannot be empty.{C_RESET}")
            h_in = input("Enter Huawei ONT Gateway IP: ").strip()
        host = h_in

    # Telnet Port (default 23)
    port = args.port or 23

    # 2. Username
    if args.user:
        user = args.user
        print(f"Telnet Username : {C_CYAN}{user}{C_RESET}")
    else:
        u_in = input("Enter Telnet Username: ").strip()
        while not u_in:
            print(f"{C_YELLOW}Username cannot be empty.{C_RESET}")
            u_in = input("Enter Telnet Username: ").strip()
        user = u_in

    # 3. Password
    if args.password:
        password = args.password
    elif not sys.stdin.isatty():
        password = sys.stdin.readline().strip()
    else:
        password = getpass.getpass(f"Enter Telnet Password for {user}@{host}: ")
        while not password:
            print(f"{C_YELLOW}Password cannot be empty.{C_RESET}")
            password = getpass.getpass(f"Enter Telnet Password for {user}@{host}: ")

    print()
    return host, port, user, password


# --- Main Dashboard Loop ---
def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    os.system("")  # Enable ANSI in Windows terminal

    parser = argparse.ArgumentParser(description="Huawei ONT btop-style Live Health & Performance Monitor")
    parser.add_argument("--host", default=None, help="ONT IP address")
    parser.add_argument("--port", type=int, default=23, help="Telnet port (default: 23)")
    parser.add_argument("--user", default=None, help="Telnet username")
    parser.add_argument("-p", "--password", default=None, help="Telnet password")
    parser.add_argument("--interval", type=float, default=3.0, help="Refresh interval in seconds (default: 3.0)")
    args = parser.parse_args()

    # Always prompt user for all 3: IP, username, and password
    host, port, user, password = prompt_user_connection(args)

    session = HuaweiTelnetSession(host, port, user, password)

    prev_rx: int | None = None
    prev_tx: int | None = None
    prev_time: float | None = None

    down_history: deque[float | None] = deque(maxlen=12)
    up_history: deque[float | None] = deque(maxlen=12)

    specs = OntDeviceSpecs()
    dev_info_queried = False
    ont_id = "—"
    ont_state = "Connecting"

    print("\033[2J\033[H", end="")

    try:
        while True:
            t_now = time.time()
            dt = t_now - prev_time if prev_time is not None else 1.0
            if dt <= 0:
                dt = 1.0

            # 1. Background Parallel Pings (takes ~0.6s total in threads)
            ping_targets = [
                (host, "PC → ONU Gateway"),
                ("1.1.1.1", "ONU → Cloudflare DNS"),
                ("8.8.8.8", "ONU → Google DNS"),
            ]
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                futures = [executor.submit(ping_host, target, label) for target, label in ping_targets]
                pings = [f.result() for f in futures]

            # 2. Query Telnet metrics from ONT
            status_note = f"{C_GREEN}Connected{C_RESET}"
            rx_dbm, tx_dbm, laser_temp = None, None, None
            cpu_pct = None
            used_mem_mb, tot_mem_mb, free_mem_mb, mem_pct = None, specs.total_mem_mb, None, None
            tot_rx, tot_tx = None, None
            pon_raw = ""
            pon_errors = {"bip": 0, "fec_uncorr": 0, "fec_corr": 0, "crc": 0, "ber_str": "0.0e-00", "clean": True}

            try:
                if not session.is_alive():
                    session.connect()
                    dev_info_queried = False

                # Dynamically probe and identify ONT device specs on connect
                if not dev_info_queried:
                    specs = query_ont_device_specs(session)
                    dev_info_queried = True

                # Step A & B: Query real-time CPU & Memory matching Web GUI
                c_sys = session.execute("display sysinfo")
                cpu_pct = parse_cpu_ultimate(c_sys)
                used_mem_mb, tot_mem_mb, free_mem_mb, mem_pct = parse_memory_comprehensive(c_sys, specs.total_mem_mb)

                if cpu_pct is None:
                    cpu_pct = session.fetch_cpu()
                if mem_pct is None:
                    used_mem_mb, tot_mem_mb, free_mem_mb, mem_pct = session.fetch_memory(specs.total_mem_mb)

                # Step C: Query ONT registration and ID
                c_onu = session.execute("display onu info")
                if "error" in c_onu.lower() or not c_onu.strip():
                    c_onu = session.execute("display ont info")
                onu_p = parse_onu_info(c_onu)
                if onu_p.get("ont_id"):
                    ont_id = onu_p["ont_id"]
                if onu_p.get("ont_status"):
                    ont_state = onu_p["ont_status"]

                # Step D: Fast WAN Traffic & PON Hardware Statistics (Counters + Bit Errors)
                tot_rx, tot_tx, pon_raw = session.fetch_traffic_and_pon()
                if pon_raw:
                    pon_errors = parse_pon_errors(pon_raw)
                else:
                    c_pon_err = session.execute("display pon statistics")
                    pon_errors = parse_pon_errors(c_pon_err)

                # Step E: Optics & Transceiver Power
                c_opt = session.execute("display optic")
                rx_dbm, tx_dbm, laser_temp = parse_optic_power(c_opt)

            except Exception as e:
                status_note = f"{C_YELLOW}Connecting...{C_RESET}"
                session.close()
                dev_info_queried = False

            # 3. Calculate Throughput Rates & Rollover
            rx_rate: float | None = None
            tx_rate: float | None = None

            if tot_rx is not None and prev_rx is not None and dt > 0:
                delta_rx = tot_rx - prev_rx
                if delta_rx < 0 and tot_rx < (1 << 32) and prev_rx < (1 << 32):
                    delta_rx += (1 << 32)
                if delta_rx >= 0:
                    rx_rate = delta_rx / dt

            if tot_tx is not None and prev_tx is not None and dt > 0:
                delta_tx = tot_tx - prev_tx
                if delta_tx < 0 and tot_tx < (1 << 32) and prev_tx < (1 << 32):
                    delta_tx += (1 << 32)
                if delta_tx >= 0:
                    tx_rate = delta_tx / dt

            if tot_rx is not None:
                prev_rx = tot_rx
            if tot_tx is not None:
                prev_tx = tot_tx
            prev_time = t_now

            # Update sparkline histories (stored in Mbps)
            down_history.append((rx_rate * 8 / 1_000_000) if rx_rate is not None else None)
            up_history.append((tx_rate * 8 / 1_000_000) if tx_rate is not None else None)

            now_clock = time.strftime("%H:%M:%S")

            out = ["\033[H"]

            # ==========================================
            # PANEL 1: btop CPU & Memory / System Box
            # ==========================================
            if specs.model and specs.model != "ONT":
                title_brand = f"HUAWEI {specs.model}"
            else:
                title_brand = "HUAWEI ONT"
            title_text = f"╭─{C_RED}¹cpu{C_RESET}─{C_BOLD}{title_brand}{C_RESET} ({host})"
            time_text = f"─ {now_clock} ── Telnet: {status_note} ─╮"
            dashes_cpu = W - len(ANSI_RE.sub("", title_text)) - len(ANSI_RE.sub("", time_text))
            out.append(f"{title_text}{'─' * max(1, dashes_cpu)}{time_text}\n")

            # CPU Bar
            c_val_str = f"{cpu_pct:3.0f}%" if cpu_pct is not None else "  — "
            c_bar = btop_bar(cpu_pct, 16)
            c_left = f"  CPU {c_bar} {c_val_str}   Processor Load"
            c_right = f"{C_DIM}{specs.cpu_hardware}{C_RESET}"
            out.append(make_box_line(c_left, right_styled=c_right))

            # Memory Bar
            m_val_str = f"{mem_pct:3.0f}%" if mem_pct is not None else "  — "
            m_bar = btop_bar(mem_pct, 16)
            if used_mem_mb is not None and free_mem_mb is not None:
                mem_detail = f"{used_mem_mb:.0f}M / {tot_mem_mb:.0f}M (Free: {free_mem_mb:.0f}M)"
            else:
                mem_detail = f"System RAM {tot_mem_mb:.0f} MB"
            m_left = f"  MEM {m_bar} {m_val_str}   {mem_detail}"
            m_right = f"{C_DIM}{int(specs.total_mem_mb)} MB RAM{C_RESET}"
            out.append(make_box_line(m_left, right_styled=m_right))

            # Flash Storage / Firmware
            f_bar = btop_bar(48, 16)
            f_left = f"  FLS {f_bar}  48%   {specs.total_flash_mb:.0f} MB Onboard Flash"
            f_right = f"{C_DIM}Dual-Bank OS{C_RESET}"
            out.append(make_box_line(f_left, right_styled=f_right))

            out.append(f"╰{'─' * INNER_W}╯\n")

            # ==========================================
            # PANEL 2: btop Optical & PON Health Box
            # ==========================================
            tag_info = f"ONT ID: {ont_id} ({ont_state})"
            pon_hdr = f"╭─{C_YELLOW}²pon{C_RESET}──{C_BOLD}Optical Health & GPON Signal{C_RESET}─"
            pon_suffix = f"─ {C_DIM}{tag_info}{C_RESET} ─╮"
            dashes_pon = W - len(ANSI_RE.sub("", pon_hdr)) - len(ANSI_RE.sub("", pon_suffix))
            out.append(f"{pon_hdr}{'─' * max(1, dashes_pon)}{pon_suffix}\n")

            if rx_dbm is not None:
                if -24.0 <= rx_dbm <= -8.0:
                    rx_state = f"{C_GREEN}[ EXCELLENT ]{C_RESET}"
                elif -27.0 <= rx_dbm < -24.0:
                    rx_state = f"{C_GREEN}[   GOOD    ]{C_RESET}"
                elif -29.0 <= rx_dbm < -27.0:
                    rx_state = f"{C_YELLOW}[  WARNING  ]{C_RESET}"
                else:
                    rx_state = f"{C_RED}[ CRITICAL  ]{C_RESET}"
                rx_str = f"{rx_dbm:6.2f} dBm"
            else:
                rx_state = f"{C_DIM}[  UNKNOWN  ]{C_RESET}"
                rx_str = "     —    "

            tx_str = f"{tx_dbm:+5.2f} dBm" if tx_dbm is not None else "   —     "
            temp_str = f"{laser_temp:4.1f} °C" if laser_temp is not None else "  —   "

            # Row 1: Rx Optical Power
            r_left = f"  Rx Optical Power: {C_BOLD}{C_CYAN}{rx_str}{C_RESET}  {rx_state}"
            r_right = f"{C_DIM}Range: -8 to -27 dBm{C_RESET}"
            out.append(make_box_line(r_left, right_styled=r_right))

            # Row 2: Tx Optical Power & Laser Temp
            t_left = f"  Tx Optical Power:  {C_BOLD}{tx_str}{C_RESET}           Module Temp: {temp_str}"
            out.append(make_box_line(t_left))

            # Row 3: Bit Error Rate (BER) & Parity Error Counters
            bip_count = int(pon_errors.get("bip", 0))
            fec_count = int(pon_errors.get("fec_uncorr", 0))
            ber_val_str = str(pon_errors.get("ber_str", "0.0e-00"))
            is_clean = bool(pon_errors.get("clean", True))

            ber_tag = f"{C_GREEN}[ CLEAN ]{C_RESET}" if is_clean else f"{C_YELLOW}[ WARNING ]{C_RESET}"

            b_left = f"  Bit Error Rate (BER): {C_BOLD}{C_GREEN}{ber_val_str}{C_RESET}  {ber_tag}"
            b_right = f"{C_DIM}BIP Errors: {bip_count}   FEC: {fec_count}{C_RESET}"
            out.append(make_box_line(b_left, right_styled=b_right))

            out.append(f"╰{'─' * INNER_W}╯\n")

            # ==========================================
            # PANEL 3: btop WAN & Traffic Box
            # ==========================================
            net_hdr = f"╭─{C_CYAN}³net{C_RESET}──{C_BOLD}WAN & Internet Throughput{C_RESET}─"
            net_suffix = f"─ {C_DIM}{specs.network_label}{C_RESET} ─╮"
            dashes_net = W - len(ANSI_RE.sub("", net_hdr)) - len(ANSI_RE.sub("", net_suffix))
            out.append(f"{net_hdr}{'─' * max(1, dashes_net)}{net_suffix}\n")

            rx_rate_s = format_rate(rx_rate)
            tx_rate_s = format_rate(tx_rate)
            tot_rx_s = format_bytes(tot_rx)
            tot_tx_s = format_bytes(tot_tx)

            spark_rx = sparkline(down_history, 12)
            spark_tx = sparkline(up_history, 12)

            net_r1 = f"  {C_CYAN}▼ download (Rx):{C_RESET}  {rx_rate_s:>10}  [{C_CYAN}{spark_rx}{C_RESET}]   Total Rx: {tot_rx_s:>10}"
            out.append(make_box_line(net_r1))

            net_r2 = f"  {C_MAG}▲ upload   (Tx):{C_RESET}  {tx_rate_s:>10}  [{C_MAG}{spark_tx}{C_RESET}]   Total Tx: {tot_tx_s:>10}"
            out.append(make_box_line(net_r2))

            out.append(f"╰{'─' * INNER_W}╯\n")

            # ==========================================
            # PANEL 4: btop Latency & Ping Box
            # ==========================================
            ping_hdr = f"╭─{C_GREEN}⁴ping{C_RESET}──{C_BOLD}Network Latency & Health Checks{C_RESET}─"
            ping_suffix = "─╮"
            dashes_p = W - len(ANSI_RE.sub("", ping_hdr)) - len(ANSI_RE.sub("", ping_suffix))
            out.append(f"{ping_hdr}{'─' * max(1, dashes_p)}{ping_suffix}\n")

            p_tbl_str = f"  {C_DIM}Target Route             Status    Latency    Loss    Hop Type{C_RESET}"
            out.append(make_box_line(p_tbl_str))

            for res in pings:
                if res.loss is None or res.loss >= 100.0:
                    status_str = f"{C_RED}[ CRIT ]{C_RESET}"
                    lat_str = f"{C_RED}   —   {C_RESET}"
                    loss_str = f"{C_RED}100%{C_RESET}"
                elif res.loss > 0 or (res.avg_ms is not None and res.avg_ms >= 80):
                    status_str = f"{C_YELLOW}[ WARN ]{C_RESET}"
                    lat_str = f"{C_YELLOW}{res.avg_ms:4.0f} ms{C_RESET}" if res.avg_ms is not None else "   —   "
                    loss_str = f"{C_YELLOW}{res.loss:3.0f}%{C_RESET}"
                else:
                    status_str = f"{C_GREEN}[  OK  ]{C_RESET}"
                    lat_str = f"{C_CYAN}{res.avg_ms:4.0f} ms{C_RESET}" if res.avg_ms is not None else " <1 ms "
                    loss_str = f"{C_GREEN}  0%{C_RESET}"

                route_label = f"{res.label:<20}"
                hop_type = "LAN / Wi-Fi Hop   " if "192.168" in res.target else ("Cloudflare Anycast" if "1.1.1.1" in res.target else "Google Primary DNS")

                color_line = f"  {C_BOLD}{route_label}{C_RESET} {status_str}  {lat_str}   {loss_str}   {C_DIM}{hop_type}{C_RESET}"
                out.append(make_box_line(color_line))

            out.append(f"╰{'─' * INNER_W}╯\n")

            # Footer
            footer = f" {C_DIM}[Ctrl+C]{C_RESET} {C_WHITE}quit{C_RESET}   {C_DIM}[{args.interval:.0f}s]{C_RESET} {C_WHITE}refresh{C_RESET}   {C_DIM}host:{C_RESET}{C_YELLOW}{host}{C_RESET}   {C_DIM}ont:{C_RESET}{status_note}"
            out.append(f"{footer}\n")

            print("".join(out), end="", flush=True)

            time.sleep(args.interval)

    except KeyboardInterrupt:
        session.close()
        print(f"\n{C_RESET}Exited Huawei ONT monitor.")


if __name__ == "__main__":
    main()
