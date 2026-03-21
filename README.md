# AMOFT GUI

## Windows setup

Use Python 3.13 on Windows when possible. The setup script will prefer Python 3.13 and fall back to 3.14 automatically if needed. The current checked-in `.venv` was created against a local Python 3.14 install and can break if that interpreter moves or is unavailable.

Run:

```powershell
.\setup_windows.ps1
```

Then launch:

```powershell
.\.venv\Scripts\python.exe main.py
```

## Raspberry Pi setup

Install the Pi dependencies with:

```bash
python3 -m pip install -r requirements-pi.txt
```

Start the server with:

```bash
python3 server.py
```

## GUI behavior

The GUI now opens without trying to connect to the Pi during startup. Use the `Connect to Pi` button in the Manual tab after the window appears.
