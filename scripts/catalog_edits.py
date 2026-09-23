#!/usr/bin/env python3
"""
One-off catalogue cleanup, 2026-09-23. Safe to run twice.

Auto-discovery named projects after their GitHub taglines ("Light, fluffy, and always free"),
filed some in the wrong category, and added four projects twice after their repos moved.
This renames and refiles them in sources.json (and devices.json, so the pages are right
before the next hourly run), folds each duplicate into the original, and records the
duplicate's old URL in redirects.json so links to it keep working.

    python3 scripts/catalog_edits.py && python3 scripts/build_pages.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# id: (brand, model, category)
RENAME = {
    "glance": ("Glance", "Feed dashboard", "A"),
    "qwenpaw": ("QwenPaw", "Personal AI assistant", "A"),
    "langfuse": ("Langfuse", "LLM observability", "A"),
    "onyx": ("Onyx", "AI platform", "A"),
    "meetily": ("Meetily", "AI meeting assistant", "A"),
    "archivebox": ("ArchiveBox", "Web archiver", "A"),
    "pentagi": ("PentAGI", "AI penetration testing agents", "A"),
    "pangolin": ("Pangolin", "Tunneled reverse proxy", "R"),
    "xiaozhi-esp32": ("Xiaozhi", "ESP32 AI voice assistant firmware", "M"),
    "xiaozhi-esp32-server": ("Xiaozhi", "Voice assistant server", "A"),
    "py-xiaozhi": ("Xiaozhi", "Python voice assistant client", "A"),
    "crosspoint-reader": ("CrossPoint", "E-reader firmware", "M"),
    "esp32-bit-pirate": ("ESP32 Bit Pirate", "Hardware hacking tool", "M"),
    "esp32-div": ("ESP32-DIV", "Wireless security toolkit firmware", "M"),
    "esp-homekit-devices": ("RavenSystem", "HomeKit firmware for ESP devices", "S"),
    "velxio": ("Velxio", "Arduino and ESP32 emulator", "M"),
    "opendtu": ("OpenDTU", "Solar inverter gateway firmware", "S"),
    "puter": ("Puter", "Web desktop OS", "A"),
    "tdengine": ("TDengine", "Time-series database", "A"),
    "apisix": ("Apache", "APISIX API gateway", "R"),
    "salt": ("Salt Project", "Salt configuration management", "A"),
    "mongoose": ("Cesanta", "Mongoose embedded web server", "M"),
    "rt-thread": ("RT-Thread", "IoT real-time OS", "M"),
    "microk8s": ("Canonical", "MicroK8s", "A"),
    "wasm3": ("Wasm3", "WebAssembly interpreter", "M"),
    "jerryscript": ("JerryScript", "Lightweight JavaScript engine", "M"),
    "serial-studio": ("Serial Studio", "Telemetry dashboard", "M"),
    "dns-blocklists": ("HaGeZi", "DNS blocklists", "R"),
    "gost": ("GOST", "Simple tunnel", "R"),
    "amass": ("OWASP", "Amass attack surface mapper", "A"),
    "gobuster": ("Gobuster", "Directory and DNS brute-forcer", "A"),
    "portmaster": ("Safing", "Portmaster application firewall", "R"),
    "docker-pi-hole": ("Pi-hole", "Docker image", "R"),
    "smartdns": ("SmartDNS", "Local DNS server", "R"),
    "networkmanager": ("NETworkManager", "Network troubleshooting tool", "R"),
    "reconftw": ("reconFTW", "Automated recon scanner", "A"),
    "dive": ("Dive", "Docker image explorer", "A"),
    "windows": ("Dockur", "Windows in Docker", "A"),
    "harness": ("Harness", "Developer platform", "A"),
    "1panel": ("1Panel", "Linux server panel", "A"),
    "colima": ("Colima", "Container runtime for macOS", "A"),
    "faas": ("OpenFaaS", "Functions as a service", "A"),
    "floci": ("Floci", "Local cloud emulator", "A"),
    "kong": ("Kong", "API gateway", "R"),
    "nginx": ("NGINX", "Web server", "R"),
    "smsforwarder": ("SmsForwarder", "Android SMS forwarder", "P"),
    "jetlinks-community": ("JetLinks", "IoT platform", "S"),
    "plotjuggler": ("PlotJuggler", "Time-series plotting tool", "M"),
    "mqttx": ("EMQX", "MQTTX client", "S"),
    "fuxa": ("FUXA", "SCADA and HMI dashboard", "S"),
    "dgiot": ("DGIOT", "Industrial IoT platform", "S"),
    "tiez-clipboard": ("TieZ", "Clipboard manager", "P"),
    "trystero": ("Trystero", "Peer-to-peer web app toolkit", "A"),
    "openmower": ("OpenMower", "Robotic mower firmware", "M"),
    "aily-blockly": ("Aily", "Blockly AI IDE for Arduino", "M"),
    "safeline": ("Chaitin", "SafeLine web application firewall", "R"),
    "server": ("Screego", "Screen sharing server", "A"),
    "tinyauth": ("Tinyauth", "Authentication server", "A"),
    "btcpayserver": ("BTCPay Server", "Bitcoin payment processor", "A"),
    "sparkyfitness": ("SparkyFitness", "Family fitness tracker", "A"),
    "bitmagnet": ("Bitmagnet", "BitTorrent indexer", "A"),
    "13ft": ("13ft", "12ft.io alternative", "A"),
    "olivetin": ("OliveTin", "Web buttons for shell commands", "A"),
    "movie-data-capture": ("Movie Data Capture", "Local movie organizer", "A"),
    "sun-panel": ("Sun Panel", "Server and NAS dashboard", "A"),
    "oxicloud": ("OxiCloud", "Cloud storage server", "N"),
    "ani-rss": ("ANi-RSS", "Anime RSS downloader", "A"),
    "arc": ("Arc", "Redpill loader for Synology DSM", "N"),
    "lanraragi": ("LANraragi", "Manga archive reader", "A"),
    "arozos": ("ArozOS", "Web desktop NAS OS", "N"),
    "bili-sync": ("bili-sync", "Bilibili downloader", "A"),
    "songloft": ("Songloft", "Music server", "A"),
    "tock": ("Tock", "Embedded OS for microcontrollers", "M"),
    "hass-xiaomi-miot": ("Xiaomi Miot Auto", "Home Assistant integration", "S"),
    "wasm-micro-runtime": ("WAMR", "WebAssembly micro runtime", "M"),
    "node-serialport": ("SerialPort", "Node.js serial port library", "M"),
    "freeswitch": ("FreeSWITCH", "Telephony server", "A"),
    "livekit": ("LiveKit", "Real-time video and audio server", "A"),
    "nginx-http-flv-module": ("nginx-http-flv-module", "NGINX live streaming module", "A"),
    "tubesync": ("TubeSync", "YouTube channel sync", "A"),
    "universalmediaserver": ("Universal Media Server", "DLNA media server", "A"),
    "nsmusics": ("NSMusicS", "Music server", "A"),
    # software that sat under NAS & storage
    "authelia": ("Authelia", "Authentication gateway", "A"),
    "apprise": ("Apprise", "Notification gateway", "A"),
    "beszel": ("Beszel", "Server monitoring hub", "A"),
    # one brand, one spelling: eero is what people search for
    "eero-pro-6e": ("eero", "Pro 6E", "R"),
    "eero-max-7": ("eero", "Max 7", "R"),
    "eero-6-plus": ("eero", "6+", "R"),
    "eero-7": ("eero", "7", "R"),
    "eero-pro-7": ("eero", "Pro 7", "R"),
}

# duplicate id → (original id, the repo the original should now follow)
# Each project moved on GitHub and discovery added the new repo as a new device.
DUPLICATES = {
    "firmware": ("bruce-firmware", "BruceDevices/firmware"),
    "podman-container-tools-podman": ("podman", "podman-container-tools/podman"),
    "netalertx-netalertx": ("netalertx", "netalertx/NetAlertX"),
    "orcaslicer-orcaslicer": ("orcaslicer", "OrcaSlicer/OrcaSlicer"),
}


def apply(doc, key, is_sources):
    items = doc[key]
    by_id = {d["id"]: d for d in items}
    for dev_id, (brand, model, cat) in RENAME.items():
        d = by_id.get(dev_id)
        if d:
            d["brand"], d["model"], d["category"] = brand, model, cat
    for dup, (orig, repo) in DUPLICATES.items():
        if dup in by_id and orig in by_id and is_sources:
            o = by_id[orig]
            o["repo"] = repo
            if "github.com/" in (o.get("product_url") or ""):
                o["product_url"] = f"https://github.com/{repo}"
    doc[key] = [d for d in items if d["id"] not in DUPLICATES]
    return len(items) - len(doc[key])


def main():
    for name, is_sources in (("sources.json", True), ("devices.json", False)):
        path = ROOT / name
        doc = json.loads(path.read_text())
        removed = apply(doc, "devices", is_sources)
        path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
        print(f"{name}: renamed/refiled up to {len(RENAME)}, folded {removed} duplicate(s)")

    red_path = ROOT / "redirects.json"
    red = json.loads(red_path.read_text()) if red_path.exists() else {}
    for dup, (orig, _) in DUPLICATES.items():
        red[f"/devices/{dup}/"] = f"/devices/{orig}/"
    # every published Amazon device was an eero, so the Amazon brand page goes with them
    red["/brands/amazon/"] = "/brands/eero/"
    # a brand page existed only because of its duplicate; with one device left it goes
    for brand in ("podman", "orcaslicer", "netalertx"):
        red[f"/brands/{brand}/"] = f"/devices/{brand}/"
    red_path.write_text(json.dumps(dict(sorted(red.items())), indent=1) + "\n")


if __name__ == "__main__":
    main()
