# MT5 via Wine — Direct Connection Setup (No MetaApi)

Goal for this pass: get the LIVE account (420568040) connected read-only
so we can print account balance/equity. No order placement yet. Free —
no MetaApi hourly charges.

Trade-off vs MetaApi (for reference): more moving parts, needs a
one-time GUI login, and the terminal must stay running for the
connection to work — but zero ongoing cost.

---

## Step 1 — Install Wine

```bash
sudo apt update
sudo apt install -y wget gnupg2 software-properties-common
sudo dpkg --add-architecture i386
wget -nc https://dl.winehq.org/wine-builds/winehq.key
sudo apt-key add winehq.key
sudo apt-add-repository 'deb https://dl.winehq.org/wine-builds/debian/ bookworm main'
sudo apt update
sudo apt install -y --install-recommends winehq-stable
```
(If `bookworm` doesn't match your Debian version, check with `cat /etc/os-release`
and swap it for your actual codename — using the wrong one will fail silently
or pull broken packages.)

Verify:
```bash
wine --version
```

## Step 2 — Install MT5 under Wine (official MetaQuotes script)

```bash
wget https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5ubuntu.zip
# If that specific URL 404s, get the current one from:
# https://www.metatrader5.com/en/terminal/help/start_advanced/install_linux
unzip mt5ubuntu.zip -d mt5setup
cd mt5setup
chmod +x mt5linux.sh   # or whatever the extracted installer script is named
./mt5linux.sh
```
Agree to install Mono/Gecko if prompted — MT5's Wine build needs them.

This installs a Windows MT5 terminal into a Wine prefix at `~/.wine` (or
wherever the script places it — it will tell you at the end, typically
`~/.wine/drive_c/Program Files/MetaTrader 5/terminal64.exe`).

## Step 3 — One-time GUI login (the annoying part on a headless LXC)

The terminal must be logged in via its actual GUI once before any API
connection will work — this is a hard MT5 requirement, no way around it.
Since metatrade has no desktop environment, we need a virtual display +
VNC to see it briefly:

```bash
sudo apt install -y xvfb x11vnc
Xvfb :1 -screen 0 1280x800x24 &
export DISPLAY=:1
x11vnc -display :1 -nopw -listen 0.0.0.0 -xkb -forever &
```

Then launch the terminal:
```bash
wine "C:\Program Files\MetaTrader 5\terminal64.exe" &
```

From your own machine, connect a VNC client (e.g. TigerVNC, RealVNC, or
even a browser-based noVNC if you set that up instead) to:
```
192.168.0.147:5900
```
You should see the MT5 terminal GUI. Log in there with:
- Login: 420568040
- Password: (your investor password — read-only, same safety reasoning as before)
- Server: XMGlobal-MT5 17

Once logged in and you see live prices/account balance in the GUI, this
one-time step is done. **Leave the terminal process running** — closing
it breaks the API connection. (We'll turn this into a proper systemd
service once this manual test works.)

**Security note:** `x11vnc -nopw` has no password — fine briefly on your
LAN for this one-time setup, but kill it right after:
```bash
pkill x11vnc
```
Don't leave an unauthenticated VNC port open long-term.

## Step 4 — Install Windows Python + the MetaTrader5 package, inside Wine

```bash
cd ~/Downloads
wget https://www.python.org/ftp/python/3.10.0/python-3.10.0-amd64.exe
wine python-3.10.0-amd64.exe
```
Follow the installer prompts (it'll pop up in the same VNC session —
reopen the VNC viewer if you closed it). Check "Add to PATH".

Then, still inside Wine:
```bash
wine python -m pip install MetaTrader5
```

## Step 5 — Bridge Linux Python to the Wine Python (mt5linux)

```bash
# Windows side (inside Wine), install mt5linux's server component:
wine python -m pip install mt5linux

# Linux side (your normal venv), install the client:
pip install --break-system-packages mt5linux
```

Start the bridge server (Windows/Wine side, needs MT5 terminal already
running and logged in from Step 3):
```bash
wine python -m mt5linux "C:\Program Files\Python310\python.exe"
```
This starts an RPyC server, default port 18812, that the Linux side
connects to.

## Step 6 — Connectivity test (Linux side, read-only)

Use the included `mt5_wine_connectivity_test.py` — connects via the
bridge and prints balance/equity only. No order placement.

```bash
python3 mt5_wine_connectivity_test.py
```

---

## Known rough edges (from community reports, worth expecting)
- `IPC timeout` errors usually mean the terminal isn't actually logged
  in yet, or the Wine process died — check it's still running with
  `wine tasklist` or just glance at the VNC session.
- If AutoTrading shows disabled in the terminal's toolbar (a button,
  not an API flag), some calls will fail — for read-only balance checks
  this shouldn't matter, but keep it in mind for later when we add
  order placement.
- Wine MT5 setups are reportedly less stable over long uptimes than
  native Windows or MetaApi's cloud terminals — expect occasional
  restarts needed. Turning this into a systemd service (later step)
  helps it auto-recover.

## Once read-only balance check works
This proves the whole chain (Wine → MT5 terminal → Python bridge →
your script) is viable, for zero recurring cost. Order-placement code
would be a separate, later step — and same as the MetaApi plan, should
be tested against a demo login before ever running against 420568040
with the real trading password.
