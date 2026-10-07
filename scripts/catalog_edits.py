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

# 2026-10-07 QA: projects discovery added since, still named after taglines, with emoji or
# invisible characters, or after a generic repo name ("Android", "iOS")
RENAME.update({
    "android": ("Home Assistant", "Android companion app", "S"),
    "ios": ("Home Assistant", "iOS companion app", "S"),
    "rethink-app": ("Rethink", "DNS and firewall app for Android", "R"),
    "hickory-dns": ("Hickory DNS", "DNS server and resolver", "R"),
    "dnscontrol": ("DNSControl", "DNS as code", "R"),
    "findomain": ("Findomain", "Subdomain finder", "A"),
    "rpcs3": ("RPCS3", "PlayStation 3 emulator", "C"),
    "ruffle": ("Ruffle", "Flash Player emulator", "C"),
    "nginx-proxy": ("nginx-proxy", "Automatic reverse proxy for Docker", "R"),
    "bunkerweb": ("BunkerWeb", "Web application firewall", "R"),
    "easegress": ("Easegress", "Traffic orchestration gateway", "R"),
    "agentgateway": ("agentgateway", "AI agent and MCP proxy", "R"),
    "godoxy": ("GoDoxy", "Reverse proxy and container manager", "R"),
    "openbot": ("OpenBot", "Smartphone-powered robot platform", "M"),
    "arduino-pico": ("Arduino-Pico", "Arduino core for Raspberry Pi Pico", "M"),
    "nnn": ("nnn", "Terminal file manager", "P"),
    "sherpa-onnx": ("sherpa-onnx", "Offline speech recognition and TTS", "M"),
    "pivpn": ("PiVPN", "VPN installer for Raspberry Pi", "R"),
    "glslviewer": ("glslViewer", "GLSL shader sandbox", "M"),
    "raspotify": ("Raspotify", "Spotify Connect for Raspberry Pi", "M"),
    "xplr": ("xplr", "Terminal file explorer", "P"),
    "linkace": ("LinkAce", "Bookmark archive", "A"),
    "tianji": ("Tianji", "Website analytics and uptime monitor", "A"),
    "gokapi": ("Gokapi", "File sharing server", "A"),
    "voidauth": ("VoidAuth", "Single sign-on server", "A"),
    "alexandrie": ("Alexandrie", "Offline-first note-taking app", "A"),
    "donetick": ("Donetick", "Task and chore manager", "A"),
    "dockflare": ("DockFlare", "Cloudflare Tunnel manager for Docker", "R"),
    "local-deep-research": ("Local Deep Research", "AI research assistant", "A"),
    "dust3d": ("Dust3D", "3D modeling software", "M"),
    "ha-bambulab": ("ha-bambulab", "Bambu Lab Home Assistant integration", "S"),
    "uvtools": ("UVtools", "Resin printer file toolkit", "M"),
    "rackstack": ("Rackstack", "3D-printable mini rack", "M"),
    "lantern": ("Lantern", "Censorship circumvention VPN", "R"),
    "elasticsearch-dump": ("elasticsearch-dump", "Elasticsearch import and export tool", "N"),
    "zerobyte": ("Zerobyte", "Backup automation", "N"),
    "imessage-exporter": ("imessage-exporter", "iMessage export tool", "N"),
    "wal-g": ("WAL-G", "Database backup and restore", "N"),
    "docker-volume-backup": ("docker-volume-backup", "Docker volume backups", "N"),
    "docker-android": ("docker-android", "Emulated phones in containers", "C"),
    "retrobios": ("RetroBIOS", "Emulator BIOS packs", "C"),
    "provenance": ("Provenance", "iOS and tvOS emulator frontend", "C"),
    "sharpemu": ("SharpEmu", "PlayStation 5 emulator", "C"),
    "melonds": ("melonDS", "Nintendo DS emulator", "C"),
    "browserbox": ("BrowserBox", "Remote browser isolation", "R"),
    "vulcain": ("Vulcain", "REST API preload gateway", "R"),
    "piko": ("Piko", "Self-hosted ngrok alternative", "R"),
    "trickster": ("Trickster", "HTTP reverse proxy cache", "R"),
    "frpmgr": ("frpmgr", "Windows GUI for FRP", "R"),
    "wordops": ("WordOps", "WordPress server stack", "A"),
    "gladys": ("Gladys", "Home automation hub", "S"),
    "button-card": ("button-card", "Home Assistant dashboard card", "S"),
    "homeassistant-tapo-control": ("Tapo Control", "Home Assistant integration for Tapo cameras", "S"),
    "lovelace-xiaomi-vacuum-map-card": ("Xiaomi Vacuum Map Card", "Home Assistant dashboard card", "S"),
    "netboot-xyz": ("netboot.xyz", "Network boot menu", "P"),
    "ezbookkeeping": ("ezBookkeeping", "Personal finance app", "A"),
    "linux-router": ("linux-router", "Turn Linux into a router", "R"),
    "ha-xiaomi-home": ("Xiaomi Home", "Home Assistant integration", "S"),
    "oxidized": ("Oxidized", "Network device config backup", "N"),
    "rustic": ("rustic", "Encrypted deduplicated backups", "N"),
    "barman": ("Barman", "PostgreSQL backup and recovery", "N"),
    "dbatools": ("dbatools", "SQL Server automation", "A"),
    "slackdump": ("Slackdump", "Slack message exporter", "N"),
    "furnace": ("Furnace", "Chiptune tracker", "C"),
    "vectras-vm-android": ("Vectras VM", "Virtual machines on Android", "C"),
    "nethersx2-patch": ("NetherSX2", "PlayStation 2 emulator for Android", "C"),
    "keepass2android": ("Keepass2Android", "Password manager for Android", "A"),
    "nodewarden": ("Nodewarden", "Bitwarden server for Cloudflare Workers", "A"),
    "sniffnet": ("Sniffnet", "Network traffic monitor", "R"),
    "gping": ("gping", "Ping with a graph", "R"),
    "arkime": ("Arkime", "Packet capture and search", "R"),
    "openccu": ("OpenCCU", "HomeMatic smart home OS", "S"),
    "doggo": ("doggo", "DNS lookup tool", "R"),
    "bambuddy": ("Bambuddy", "Bambu Lab printer manager", "M"),
    "gobackup": ("GoBackup", "Database and file backup tool", "N"),
    "pv-migrate": ("pv-migrate", "Kubernetes volume migration", "N"),
    "avideo": ("AVideo", "Video streaming platform", "A"),
    "passforios": ("Pass for iOS", "Password store client", "A"),
    "http-shortcuts": ("HTTP Shortcuts", "Android automation app", "S"),
    "bizhawk": ("BizHawk", "Multi-system emulator", "C"),
    "bfe": ("BFE", "Layer 7 load balancer", "R"),
    "ocelot": ("Ocelot", ".NET API gateway", "R"),
    "modlishka": ("Modlishka", "Phishing simulation proxy", "A"),
    "krakend-ce": ("KrakenD", "API gateway (Community Edition)", "R"),
    "zrok": ("zrok", "Secure sharing tunnel", "R"),
    "deskhop": ("DeskHop", "Keyboard and mouse switcher", "M"),
    "tyk": ("Tyk", "API gateway", "R"),
    "lemuroid": ("Lemuroid", "Android emulator frontend", "C"),
    "xemu": ("xemu", "Original Xbox emulator", "C"),
    "86box": ("86Box", "x86 PC emulator", "C"),
})

# code libraries discovery took for products (the "router" topic also means web routing):
# not something anyone installs or updates as a device or a server. id → where its URL goes
REMOVE = {
    "path-to-regexp": "/category/routers/", "wouter": "/category/routers/", "routing": "/category/routers/",
    "chi": "/category/routers/", "single-spa": "/category/routers/", "ui-router": "/category/routers/",
    "lura": "/category/routers/", "uwebsockets": "/category/routers/", "uwebsockets-js": "/category/routers/",
    "twisted": "/category/routers/", "laravel-backup": "/category/nas/", "node-serialport": "/category/makers/",
}

# hardware that auto-categorisation filed as self-hosted software
CATEGORY = {"synology-ds220j": "N", "synology-ds425-plus": "N", "synology-ds1522-plus": "N",
            "synology-rs422-plus": "N", "ubiquiti-unas-pro": "N"}

# one naming style within a family: "DS923+", not "DiskStation DS923+" next to "DS220j"
MODEL = {f"synology-ds{m}": f"DS{m.replace('-plus', '+')}" for m in
         ("224-plus", "423-plus", "725-plus", "923-plus", "925-plus", "1825-plus")}

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
    for dev_id, model in MODEL.items():
        if dev_id in by_id:
            by_id[dev_id]["model"] = model
    for dev_id, cat in CATEGORY.items():
        if dev_id in by_id:
            by_id[dev_id]["category"] = cat
    for dup, (orig, repo) in DUPLICATES.items():
        if dup in by_id and orig in by_id and is_sources:
            o = by_id[orig]
            o["repo"] = repo
            if "github.com/" in (o.get("product_url") or ""):
                o["product_url"] = f"https://github.com/{repo}"
    doc[key] = [d for d in items if d["id"] not in DUPLICATES and d["id"] not in REMOVE]

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
    # every published Amazon device was an eero, so the Amazon brand page goes to the eero page
    red["/brands/amazon/"] = "/devices/eero/"
    # a brand page existed only because of its duplicate; with one device left it goes
    for brand in ("podman", "orcaslicer", "netalertx"):
        red[f"/brands/{brand}/"] = f"/devices/{brand}/"
    for dev_id, dest in REMOVE.items():
        red[f"/devices/{dev_id}/"] = dest
    red_path.write_text(json.dumps(dict(sorted(red.items())), indent=1) + "\n")


if __name__ == "__main__":
    main()
