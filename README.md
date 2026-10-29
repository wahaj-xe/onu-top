# Huawei ONT Top (btop-style Live Monitor)

A lightweight, terminal-based live health and performance monitor for Huawei GPON and EPON Optical Network Terminals (ONTs / routers), featuring a modern `btop`-inspired visual dashboard.

```text
╭─¹cpu─HUAWEI HG8145X6-10 (192.168.18.1)─── 10:17:53 ── Telnet: Connected ─╮
│  CPU ················   2%   Processor Load          HiSilicon Dual-Core │
│  MEM ■■■■■■■■■■······  63%   161M / 256M (Free: 95M)         256 MB DDR3 │
│  FLS ■■■■■■■■········  48%   128 MB Onboard Flash           Dual-Bank OS │
╰──────────────────────────────────────────────────────────────────────────╯
╭─²pon──Optical Health & GPON Signal───────── ONT ID: 44 (O5 Operational) ─╮
│  Rx Optical Power: -15.69 dBm  [ EXCELLENT ]        Range: -8 to -27 dBm │
│  Tx Optical Power:  +1.97 dBm           Module Temp: 39.0 °C             │
│  Bit Error Rate (BER): 0.0e-00  [ CLEAN ]         BIP Errors: 0   FEC: 0 │
╰──────────────────────────────────────────────────────────────────────────╯
╭─³net──WAN & Internet Throughput───────────────────────── Wi-Fi 6 AX3000 ─╮
│  ▼ download (Rx):    2.4 Mbps  [ ▂▄▅▆▇█████]   Total Rx:  83.16 GiB     │
│  ▲ upload   (Tx):  120.0 Kbps  [   ▂▃▄▅▆▇██]   Total Tx:  38.85 GiB     │
╰──────────────────────────────────────────────────────────────────────────╯
╭─⁴ping──Network Latency & Health Checks───────────────────────────────────╮
│  Target Route             Status    Latency    Loss    Hop Type          │
│  PC → ONU Gateway     [  OK  ]     4 ms     0%   LAN / Wi-Fi Hop         │
│  ONU → Cloudflare DNS [  OK  ]    31 ms     0%   Cloudflare Anycast      │
│  ONU → Google DNS     [  OK  ]    47 ms     0%   Google Primary DNS      │
╰──────────────────────────────────────────────────────────────────────────╯
 [Ctrl+C] quit   [3s] refresh   host:192.168.18.1   ont:Connected
```

---

## Features

- **No External Dependencies:** Built with 100% Python standard library (`socket`, `select`, `subprocess`, `getpass`). No `pip install` required.
- **Interactive Authentication Prompt:** Prompts directly for ONT Gateway IP, Telnet username, and masked password on launch.
- **Automatic Model & Hardware Auto-Detection:** Dynamically queries the ONT over Telnet upon connection to identify the exact device model (OptiXstar, EchoLife, etc.), CPU vendor & core count, system RAM capacity, and Wi-Fi/uplink capabilities.
- **Real-Time CPU & RAM Utilization:** Synchronized with the router's internal `display sysinfo` interface, exactly matching the official Huawei Web GUI (including automatic Linux kernel buffer/cache deduction).
- **Optical Power & GPON Health:** Live tracking of Rx optical power, Tx optical power, laser module temperature, and signal rating (`[ EXCELLENT ]`, `[ GOOD ]`, `[ WARNING ]`, `[ CRITICAL ]`).
- **Bit Error Rate (BER) & Error Counters:** Real-time auditing of Bit Interleaved Parity (BIP) errors, Forward Error Correction (FEC), and delimiter frame drops.
- **WAN Live Throughput & Sparklines:** Real-time download/upload speed meters with 12-sample ASCII sparkline graphs and 32-bit counter rollover compensation.
- **Multi-Hop Latency Audit:** Concurrent sub-second ICMP ping probes testing LAN Gateway, Cloudflare Anycast (`1.1.1.1`), and Google Primary DNS (`8.8.8.8`).

---

## Supported Hardware

Tested and verified on Huawei ONTs running Dopra Linux / V5 firmware:
- **OptiXstar Series:** HG8145X6-10, HG8145X6, EG8145X6, HN8145X6
- **EchoLife Series:** HG8245H, HG8245Q, HG8245Q2, HG8245W5, EG8145V5, HG8010H

---

## Prerequisites

Before running `onu-top`, ensure your setup meets the following requirements:

### 1. Python Environment
- **Python 3.8 or higher** (Python 3.9+ recommended).
- **Automated Python Setup:** The one-line installers (Windows PowerShell & macOS Terminal) will check for Python automatically; if missing, they prompt you with a single confirmation to automatically download and install Python for you.
- **Zero External Dependencies:** Built 100% using Python's standard library (`socket`, `select`, `subprocess`, `getpass`). No `pip install` required.
- **Cross-Platform:** Runs natively on **Windows**, **macOS (Apple Silicon M1/M2/M3/M4 & Intel)**, and **Linux**.

### 2. Router / ONT Telnet Access
- **Telnet Enabled on ONT:** Ensure LAN Telnet access is enabled on your Huawei ONT:
  1. Log into your router's Web GUI (e.g. `http://192.168.18.1` or `http://192.168.100.1`).
  2. Navigate to **Security** (or **Maintenance** / **Management**) &rarr; **Device Access Control** (or **Service Access Control**).
  3. Check/Enable **Telnet** on the **LAN** interface and click **Apply**.
- **Credentials:**
  - **Gateway IP:** Usually `192.168.18.1` (or `192.168.1.1` / `192.168.100.1`).
  - **Username:** Typically `root` (or `admin` / operator default).
  - **Password:** Your ONT Telnet administrative password (e.g., `adminHW1`, `adminHW`, or custom).

### 3. Network Connectivity
- Your computer must be connected to the ONT via Wi-Fi or Ethernet LAN.

---

## Installation & Quick Start

### Windows (PowerShell)

Open PowerShell or Windows Terminal and run:

```powershell
irm https://raw.githubusercontent.com/wahaj-xe/onu-top/main/install.ps1 | iex
```

### macOS / Apple Silicon & Intel (Terminal)

Open Terminal and run:

```bash
curl -fsSL https://raw.githubusercontent.com/wahaj-xe/onu-top/main/install.sh | bash
```

---

### What the Automated Installer Does:
1. **Checks Prerequisites**: Checks if Python 3.8+ is installed. If missing, it prompts you to install Python automatically (via `winget` / official python.org installer on Windows, or Homebrew / official universal pkg on macOS).
2. **Installs the Tool**: Deploys `huawei_ont_top.py` to your local user binary directory (`%LOCALAPPDATA%\Programs\onu-top` on Windows, `~/.local/bin` on macOS/Linux).
3. **Configures PATH**: Adds the command to your shell `PATH` (Windows user PATH / `~/.zshrc` on macOS).
4. **Global Command**: You can now run `onu-top` anytime from any terminal by typing:
   ```bash
   onu-top
   ```

---

### Manual Clone (Any OS)

```bash
git clone https://github.com/wahaj-xe/onu-top.git
cd onu-top
python huawei_ont_top.py
```

### Usage

#### 1. Interactive Launch (Recommended)
Simply run the script. It will interactively prompt for the Gateway IP, Username, and Password:
```bash
python huawei_ont_top.py
```

```text
╔══════════════════════════════════════════════════════════════╗
║        Huawei ONT Live Health & Performance Monitor          ║
╚══════════════════════════════════════════════════════════════╝

Enter Huawei ONT Gateway IP: 192.168.18.1
Enter Telnet Username: root
Enter Telnet Password for root@192.168.18.1: 
```

#### 2. Command Line Arguments
```bash
# Pass connection parameters directly
python huawei_ont_top.py --host 192.168.18.1 --user root -p adminHW1

# Custom refresh interval (e.g. 2 seconds)
python huawei_ont_top.py --interval 2.0
```

---

## CLI Options

| Argument | Description | Default |
| :--- | :--- | :--- |
| `--host HOST` | ONT Gateway IP address | Prompted |
| `--port PORT` | Telnet port | `23` |
| `--user USER` | Telnet administrative user | Prompted |
| `-p`, `--password` | Telnet password (masked prompt if omitted) | Prompted |
| `--interval SEC` | Refresh cycle interval in seconds | `3.0` |

---

## Security & Privacy
- **Zero Telemetry:** No external internet telemetry, API calls, or third-party cloud connections. All data resides strictly between your terminal and local ONT.
- **Secure Password Prompting:** Passwords are never echoed to the terminal or written to disk.

---

## License
MIT License. See [LICENSE](LICENSE) for details.
