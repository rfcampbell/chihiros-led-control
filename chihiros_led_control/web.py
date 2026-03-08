"""Flask web UI for controlling Chihiros WRGB II Pro via Bluetooth."""

import argparse
import asyncio
import logging
import os
import threading
from datetime import datetime

from flask import Flask, jsonify, request

logger = logging.getLogger(__name__)

DEFAULT_ADDRESS = "C0EF8802-A773-42FA-2015-EBA6EAFB0A2D"

# Global state
_loop: asyncio.AbstractEventLoop | None = None
_device = None
_device_address: str = ""
_channel_values = {"red": 0, "green": 0, "blue": 0, "white": 0}

app = Flask(__name__)


# ── async helpers ────────────────────────────────────────────────────────────

def _start_loop(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()


def _ensure_loop() -> asyncio.AbstractEventLoop:
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        t = threading.Thread(target=_start_loop, args=(_loop,), daemon=True)
        t.start()
    return _loop


def run_async(coro):
    loop = _ensure_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=30)


async def _get_device():
    global _device
    if _device is None:
        from .device import get_device_from_address
        _device = await get_device_from_address(_device_address)
    return _device


def get_device():
    return run_async(_get_device())


# ── routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return HTML_PAGE


@app.route("/api/status")
def status():
    try:
        dev = get_device()
        return jsonify({"connected": True, "name": dev.name, "address": dev.address})
    except Exception as e:
        return jsonify({"connected": False, "error": str(e)})


@app.route("/api/power", methods=["POST"])
def power():
    data = request.json or {}
    action = data.get("action", "on")
    try:
        dev = get_device()
        if action == "on":
            run_async(dev.turn_on())
            for k in _channel_values:
                _channel_values[k] = 100
        else:
            run_async(dev.turn_off())
            for k in _channel_values:
                _channel_values[k] = 0
        return jsonify({"ok": True, "channels": _channel_values})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/color", methods=["POST"])
def set_color():
    data = request.json or {}
    color = data.get("color")
    brightness = int(data.get("brightness", 0))
    if color not in _channel_values:
        return jsonify({"ok": False, "error": "invalid color"}), 400
    try:
        dev = get_device()
        color_id = dev.colors[color]
        run_async(dev.set_color_brightness(brightness, color_id))
        _channel_values[color] = brightness
        return jsonify({"ok": True, "channels": _channel_values})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/master", methods=["POST"])
def set_master():
    data = request.json or {}
    master = int(data.get("brightness", 100))
    ratios = data.get("ratios", {})
    try:
        dev = get_device()
        for color_name, ratio in ratios.items():
            if color_name in dev.colors:
                val = max(0, min(100, round(ratio * master / 100)))
                color_id = dev.colors[color_name]
                run_async(dev.set_color_brightness(val, color_id))
                _channel_values[color_name] = val
        return jsonify({"ok": True, "channels": _channel_values})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/schedule", methods=["POST"])
def add_schedule():
    data = request.json or {}
    try:
        dev = get_device()
        sunrise = datetime.strptime(data["sunrise"], "%H:%M")
        sunset = datetime.strptime(data["sunset"], "%H:%M")
        r = int(data.get("red", 100))
        g = int(data.get("green", 100))
        b = int(data.get("blue", 100))
        ramp = int(data.get("ramp_up", 0))
        weekday_strs = data.get("weekdays", ["everyday"])

        from .weekday_encoding import WeekdaySelect
        weekdays = [WeekdaySelect(w) for w in weekday_strs]

        run_async(dev.add_rgb_setting(sunrise, sunset, (r, g, b), ramp, weekdays))
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/reset-schedules", methods=["POST"])
def reset_schedules():
    try:
        dev = get_device()
        run_async(dev.reset_settings())
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/auto-mode", methods=["POST"])
def auto_mode():
    try:
        dev = get_device()
        run_async(dev.enable_auto_mode())
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ── HTML ─────────────────────────────────────────────────────────────────────

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Chihiros WRGB II Pro</title>
<style>
  :root {
    --bg: #1a1a2e; --surface: #16213e; --card: #0f3460;
    --text: #e0e0e0; --accent: #53a8b6; --red: #e74c3c;
    --green: #2ecc71; --blue: #3498db; --white-c: #ecf0f1;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg); color: var(--text); min-height: 100vh;
    display: flex; justify-content: center; padding: 20px;
  }
  .container { max-width: 480px; width: 100%; }
  h1 { text-align: center; font-size: 1.5rem; margin-bottom: 8px; color: var(--accent); }
  .status {
    text-align: center; font-size: .85rem; margin-bottom: 20px;
    padding: 6px 12px; border-radius: 20px; display: inline-block;
    width: 100%;
  }
  .status.connected { background: rgba(46,204,113,.15); color: var(--green); }
  .status.disconnected { background: rgba(231,76,60,.15); color: var(--red); }
  .card {
    background: var(--surface); border-radius: 12px; padding: 20px;
    margin-bottom: 16px; border: 1px solid rgba(255,255,255,.05);
  }
  .card h2 { font-size: 1rem; margin-bottom: 14px; color: var(--accent); }
  .power-btns { display: flex; gap: 12px; }
  .power-btns button {
    flex: 1; padding: 12px; border: none; border-radius: 8px;
    font-size: 1rem; font-weight: 600; cursor: pointer; transition: .2s;
  }
  .btn-on { background: var(--green); color: #fff; }
  .btn-on:hover { background: #27ae60; }
  .btn-off { background: var(--red); color: #fff; }
  .btn-off:hover { background: #c0392b; }
  .slider-group { margin-bottom: 14px; }
  .slider-label {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 4px; font-size: .9rem;
  }
  .slider-label .dot {
    width: 10px; height: 10px; border-radius: 50%; display: inline-block;
    margin-right: 6px; vertical-align: middle;
  }
  input[type=range] {
    -webkit-appearance: none; width: 100%; height: 8px;
    border-radius: 4px; outline: none; background: #2c3e50;
  }
  input[type=range]::-webkit-slider-thumb {
    -webkit-appearance: none; width: 22px; height: 22px;
    border-radius: 50%; cursor: pointer; border: 2px solid #fff;
  }
  .slider-red input::-webkit-slider-thumb { background: var(--red); }
  .slider-green input::-webkit-slider-thumb { background: var(--green); }
  .slider-blue input::-webkit-slider-thumb { background: var(--blue); }
  .slider-white input::-webkit-slider-thumb { background: var(--white-c); }
  .slider-master input::-webkit-slider-thumb { background: var(--accent); }
  .slider-red input { background: linear-gradient(90deg, #2c3e50 0%, var(--red) 100%); }
  .slider-green input { background: linear-gradient(90deg, #2c3e50 0%, var(--green) 100%); }
  .slider-blue input { background: linear-gradient(90deg, #2c3e50 0%, var(--blue) 100%); }
  .slider-white input { background: linear-gradient(90deg, #2c3e50 0%, var(--white-c) 100%); }
  .slider-master input { background: linear-gradient(90deg, #2c3e50 0%, var(--accent) 100%); }
  .schedule-form label { display: block; font-size: .85rem; margin-bottom: 4px; margin-top: 10px; }
  .schedule-form input[type=time],
  .schedule-form input[type=number] {
    width: 100%; padding: 8px; border-radius: 6px; border: 1px solid #2c3e50;
    background: var(--bg); color: var(--text); font-size: .9rem;
  }
  .row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .row4 { display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 8px; }
  .weekdays { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
  .weekdays label {
    display: flex; align-items: center; gap: 4px; font-size: .8rem;
    background: var(--bg); padding: 4px 8px; border-radius: 6px; cursor: pointer;
    margin: 0;
  }
  .weekdays input { accent-color: var(--accent); }
  .btn {
    display: inline-block; padding: 10px 18px; border: none; border-radius: 8px;
    font-size: .9rem; font-weight: 600; cursor: pointer; transition: .2s;
    background: var(--card); color: var(--text); margin-top: 12px; margin-right: 8px;
  }
  .btn:hover { background: var(--accent); color: #fff; }
  .btn-primary { background: var(--accent); color: #fff; }
  .btn-primary:hover { background: #3d8a96; }
  .btn-danger { background: var(--red); color: #fff; }
  .btn-danger:hover { background: #c0392b; }
  .toast {
    position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%);
    padding: 10px 20px; border-radius: 8px; font-size: .85rem;
    opacity: 0; transition: opacity .3s; pointer-events: none; z-index: 99;
  }
  .toast.show { opacity: 1; }
  .toast.ok { background: rgba(46,204,113,.9); color: #fff; }
  .toast.err { background: rgba(231,76,60,.9); color: #fff; }
</style>
</head>
<body>
<div class="container">
  <h1>🐟 Chihiros WRGB II Pro</h1>
  <div class="status disconnected" id="status">Checking connection…</div>

  <div class="card">
    <h2>Power</h2>
    <div class="power-btns">
      <button class="btn-on" onclick="power('on')">💡 On</button>
      <button class="btn-off" onclick="power('off')">🌙 Off</button>
    </div>
  </div>

  <div class="card">
    <h2>Brightness</h2>
    <div class="slider-group slider-master">
      <div class="slider-label"><span>☀️ Master</span><span id="master-val">100</span></div>
      <input type="range" min="0" max="100" value="100" id="master" oninput="masterChange(this.value)">
    </div>
    <div class="slider-group slider-red">
      <div class="slider-label"><span><span class="dot" style="background:var(--red)"></span>Red</span><span id="red-val">0</span></div>
      <input type="range" min="0" max="100" value="0" id="red" oninput="colorChange('red',this.value)">
    </div>
    <div class="slider-group slider-green">
      <div class="slider-label"><span><span class="dot" style="background:var(--green)"></span>Green</span><span id="green-val">0</span></div>
      <input type="range" min="0" max="100" value="0" id="green" oninput="colorChange('green',this.value)">
    </div>
    <div class="slider-group slider-blue">
      <div class="slider-label"><span><span class="dot" style="background:var(--blue)"></span>Blue</span><span id="blue-val">0</span></div>
      <input type="range" min="0" max="100" value="0" id="blue" oninput="colorChange('blue',this.value)">
    </div>
    <div class="slider-group slider-white">
      <div class="slider-label"><span><span class="dot" style="background:var(--white-c)"></span>White</span><span id="white-val">0</span></div>
      <input type="range" min="0" max="100" value="0" id="white" oninput="colorChange('white',this.value)">
    </div>
  </div>

  <div class="card">
    <h2>Schedules</h2>
    <div class="schedule-form">
      <div class="row2">
        <div><label>Sunrise</label><input type="time" id="sunrise" value="08:00"></div>
        <div><label>Sunset</label><input type="time" id="sunset" value="18:00"></div>
      </div>
      <label>Brightness (R, G, B)</label>
      <div class="row4">
        <input type="number" id="sched-r" min="0" max="100" value="100" placeholder="R">
        <input type="number" id="sched-g" min="0" max="100" value="100" placeholder="G">
        <input type="number" id="sched-b" min="0" max="100" value="100" placeholder="B">
        <input type="number" id="sched-ramp" min="0" max="150" value="0" placeholder="Ramp">
      </div>
      <label>Ramp-up minutes (last field above) &amp; Weekdays</label>
      <div class="weekdays">
        <label><input type="checkbox" value="everyday" checked> Every day</label>
        <label><input type="checkbox" value="monday"> Mon</label>
        <label><input type="checkbox" value="tuesday"> Tue</label>
        <label><input type="checkbox" value="wednesday"> Wed</label>
        <label><input type="checkbox" value="thursday"> Thu</label>
        <label><input type="checkbox" value="friday"> Fri</label>
        <label><input type="checkbox" value="saturday"> Sat</label>
        <label><input type="checkbox" value="sunday"> Sun</label>
      </div>
      <button class="btn btn-primary" onclick="addSchedule()">Add Schedule</button>
      <button class="btn btn-danger" onclick="resetSchedules()">Reset All</button>
      <button class="btn" onclick="enableAuto()">Enable Auto Mode</button>
    </div>
  </div>
</div>
<div class="toast" id="toast"></div>
<script>
let debounceTimers = {};
let ratios = {red: 0, green: 0, blue: 0, white: 0};

function toast(msg, ok) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast show ' + (ok ? 'ok' : 'err');
  setTimeout(() => t.className = 'toast', 2000);
}

async function api(url, body) {
  try {
    const r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
    const d = await r.json();
    if (!d.ok) { toast(d.error || 'Error', false); return null; }
    return d;
  } catch(e) { toast(e.message, false); return null; }
}

async function checkStatus() {
  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    const el = document.getElementById('status');
    if (d.connected) { el.textContent = '● Connected — ' + d.name; el.className = 'status connected'; }
    else { el.textContent = '○ Disconnected'; el.className = 'status disconnected'; }
  } catch(e) {}
}

async function power(action) {
  const d = await api('/api/power', {action});
  if (d && d.channels) updateSliders(d.channels);
  toast(action === 'on' ? 'Turned on' : 'Turned off', true);
}

function updateSliders(ch) {
  for (const c of ['red','green','blue','white']) {
    document.getElementById(c).value = ch[c];
    document.getElementById(c+'-val').textContent = ch[c];
    ratios[c] = ch[c];
  }
}

function colorChange(color, val) {
  val = parseInt(val);
  document.getElementById(color+'-val').textContent = val;
  ratios[color] = val;
  clearTimeout(debounceTimers[color]);
  debounceTimers[color] = setTimeout(() => {
    api('/api/color', {color, brightness: val});
  }, 200);
}

function masterChange(val) {
  val = parseInt(val);
  document.getElementById('master-val').textContent = val;
  clearTimeout(debounceTimers._master);
  debounceTimers._master = setTimeout(() => {
    api('/api/master', {brightness: val, ratios}).then(d => {
      if (d && d.channels) {
        for (const c of ['red','green','blue','white']) {
          document.getElementById(c).value = d.channels[c];
          document.getElementById(c+'-val').textContent = d.channels[c];
        }
      }
    });
  }, 200);
}

async function addSchedule() {
  const weekdays = [];
  document.querySelectorAll('.weekdays input:checked').forEach(cb => weekdays.push(cb.value));
  const d = await api('/api/schedule', {
    sunrise: document.getElementById('sunrise').value,
    sunset: document.getElementById('sunset').value,
    red: parseInt(document.getElementById('sched-r').value),
    green: parseInt(document.getElementById('sched-g').value),
    blue: parseInt(document.getElementById('sched-b').value),
    ramp_up: parseInt(document.getElementById('sched-ramp').value),
    weekdays: weekdays.length ? weekdays : ['everyday']
  });
  if (d) toast('Schedule added', true);
}

async function resetSchedules() {
  const d = await api('/api/reset-schedules', {});
  if (d) toast('Schedules reset', true);
}

async function enableAuto() {
  const d = await api('/api/auto-mode', {});
  if (d) toast('Auto mode enabled', true);
}

checkStatus();
setInterval(checkStatus, 15000);
</script>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description="Chihiros WRGB II Pro Web UI")
    parser.add_argument("--address", default=None, help="BLE device address")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=5000, help="Port to bind to")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    global _device_address
    _device_address = args.address or os.environ.get("CHIHIROS_ADDRESS", DEFAULT_ADDRESS)

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)
    logger.info("Starting Chihiros Web UI for device %s", _device_address)
    logger.info("Open http://%s:%d in your browser", args.host, args.port)

    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
