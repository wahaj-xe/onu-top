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

- **No External Dependencies:** Built with 100% Python standard library (`socket`, `select`, `subprocess`, `ctypes`). No `pip install` required.
- **Interactive First-Launch Prompt:** Interactively prompts for Gateway IP, Telnet port, username, and password if not specified via flags or saved credentials.
- **Real-Time CPU & RAM Utilization:** Synchronized with the router's internal `display sysinfo` interface, exactly matching the official Huawei Web GUI (including automatic Linux kernel buffer/cache deduction).
- **Optical Power & GPON Health:** Live tracking of Rx optical power, Tx optical power, laser module temperature, and signal rating (`[ EXCELLENT ]`, `[ GOOD ]`, `[ WARNING ]`, `[ CRITICAL ]`).
- **Bit Error Rate (BER) & Error Counters:** Real-time auditing of Bit Interleaved Parity (BIP) errors, Forward Error Correction (FEC), and delimiter frame drops.
- **WAN Live Throughput & Sparklines:** Real-time download/upload speed meters with 12-sample ASCII sparkline graphs and 32-bit counter rollover compensation.
- **Multi-Hop Latency Audit:** Concurrent sub-second ICMP ping probes testing LAN Gateway, Cloudflare Anycast (`1.1.1.1`), and Google Primary DNS (`8.8.8.8`).
- **Encrypted Local Credentials:** Supports optional encryption using Windows DPAPI (`CryptProtectData`) to avoid hardcoding plaintext passwords.

---

## Supported Hardware

Tested and verified on Huawei ONTs running Dopra Linux / V5 firmware:
- **OptiXstar Series:** HG8145X6-10, HG8145X6, EG8145X6, HN8145X6
- **EchoLife Series:** HG8245H, HG8245Q, HG8245Q2, HG8245W5, EG8145V5, HG8010H

---

## Getting Started

### Prerequisites
1. Python 3.9 or higher.
2. Ensure Telnet access is enabled on your Huawei ONT (typically under **Security** / **Maintenance** / **Device Access Control** in the Web GUI).

### Installation
Clone the repository:
```bash
git clone https://github.com/wahaj-xe/huawei-ont-top.git
cd huawei-ont-top
```

### Usage

#### 1. Interactive Launch (Recommended)
Simply run the script. It will interactively guide you through connection settings:
```bash
python huawei_ont_top.py
```

```text
╔══════════════════════════════════════════════════════════════╗
║        Huawei ONT Live Health & Performance Monitor          ║
╚══════════════════════════════════════════════════════════════╝

Enter Huawei ONT Gateway IP [192.168.18.1]: 
Enter Telnet Port [23]: 
Enter Telnet Username [root]: 
Enter Password for root@192.168.18.1: 
Save credentials securely on this machine with Windows DPAPI? [Y/n]: y
```

#### 2. Command Line Arguments
```bash
# Custom host and username with explicit password
python huawei_ont_top.py --host 192.168.18.1 --user root -p adminHW1

# Custom refresh interval (e.g. 2 seconds)
python huawei_ont_top.py --interval 2.0

# Force interactive prompt (ignores saved credentials)
python huawei_ont_top.py --prompt

# Remove saved encrypted credentials
python huawei_ont_top.py --forget-credentials
```

---

## CLI Options

| Argument | Description | Default |
| :--- | :--- | :--- |
| `--host HOST` | ONT Gateway IP address | `192.168.18.1` |
| `--port PORT` | Telnet port | `23` |
| `--user USER` | Telnet administrative user | `root` |
| `-p`, `--password` | Telnet password (prompted securely if omitted) | Prompt |
| `--interval SEC` | Refresh cycle interval in seconds | `3.0` |
| `--prompt` | Force interactive connection dialog | False |
| `--save-credentials` | Encrypt credentials with Windows DPAPI | False |
| `--forget-credentials` | Remove saved credentials from local secure store | False |
| `--no-saved-credentials`| Skip reading local encrypted store for current launch | False |

---

## Security & Privacy
- **Zero Telemetry:** No external internet telemetry, API calls, or third-party cloud connections. All data resides strictly between your terminal and local ONT.
- **DPAPI Encryption:** When credentials are saved, they are protected with Windows Data Protection API (DPAPI), bound exclusively to your local Windows user session.

---

## License
MIT License. See [LICENSE](LICENSE) for details.
