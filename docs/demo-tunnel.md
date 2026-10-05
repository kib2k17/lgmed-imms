# Starting and stopping the demo tunnel

**Purpose:** putting LGMED-iMMS on a public link so someone outside the office
can open it, and taking it back down afterwards.
**Applies to:** the development machine this system runs on.
**Tool:** Cloudflare Tunnel (`cloudflared`), driven by `run-cloudflare.ps1`.

This is the short operational guide. The reasoning behind it — why the settings
in `venv\lgmed.env` are needed, what a visitor can and cannot reach — is in the
README under *Sharing a demo over a Cloudflare tunnel*.

---

## Before the first time only

Install the tunnel program once per machine. Nothing else is needed: no
account, no sign-up, no token.

```powershell
winget install Cloudflare.cloudflared
```

---

## To start the tunnel

1. Open **PowerShell** in the project folder
   (`Documents\DILG SYSTEMS\lgmedimms`).

2. Run one of these:

   ```powershell
   .\run-cloudflare.ps1 -Serve     # if the system is NOT already running
   .\run-cloudflare.ps1            # if it is already running on port 8000
   ```

3. Wait for the box it prints, and copy the link inside it:

   ```
   +------------------------------------------------------------+
   |  Your quick Tunnel has been created! Visit it at            |
   |  https://<some-random-name>.trycloudflare.com               |
   +------------------------------------------------------------+
   ```

4. Send that link. It opens the public site straight away — there is no warning
   page to click through.

**Leave the PowerShell window open.** The tunnel lives in that window. Closing
it, or shutting or sleeping the machine, takes the link down.

---

## To stop the tunnel

**Press Ctrl+C in the PowerShell window running it.** That is the whole
procedure. The link stops working within a second or two.

Closing that window does the same thing.

### If that window is gone

When the tunnel was started some other way — from a script, or in a window that
has since been closed — there is no Ctrl+C to press. Stop it by process
instead:

```powershell
Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
```

To see first whether one is running at all, and which port it is serving:

```powershell
Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" |
    Select-Object ProcessId, CommandLine
```

### The system itself keeps running

Stopping the tunnel only removes the public link. The server carries on, and is
still reachable on this machine and on the office network. To stop that too,
press Ctrl+C in **its** window, or stop it by port:

```powershell
(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue).OwningProcess |
    Sort-Object -Unique | ForEach-Object { Stop-Process -Id $_ -Force }
```

---

## The link is different every time

Each start produces a **new random address**. Stopping the tunnel retires the
old one permanently — it does not come back, and anyone still holding it sees an
error.

So:

- Send the link from the run that is currently up, never one from yesterday.
- If someone reports the link is dead, the tunnel was stopped or the machine
  slept. Start it again and send the new link.
- If the same address has to keep working for weeks, a free Cloudflare account
  and a *named* tunnel is the fix. See the README.

---

## Do not leave it running overnight

The tunnel publishes a development server that shows full error details, and the
demonstration accounts share a password that is written down in `acounts.txt`.
Anyone holding the link can reach the sign-in page.

Stop the tunnel when the demo ends.


Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force