# FlowRemote Windows Demo

Download:

- [FlowRemoteDemo.exe](dist/FlowRemoteDemo.exe)
- [SHA-256 checksum](dist/FlowRemoteDemo.exe.sha256)

Version: `0.10.0`

## Run

1. Download `FlowRemoteDemo.exe`.
2. Double-click it.
3. Wait for the local services to start.
4. The default browser opens the `/demo` page. The header shows v0.10.0.
5. Use **Create account** for registration and AI-RPA onboarding, or click
   **Quick demo login**.

Quick demo account:

```text
Email: alex.morgan@example.com
Password: 123456
```

Runtime data is stored outside the executable:

```text
%LOCALAPPDATA%\FlowRemoteDemo
```

The application uses only a loopback HTTP server. No Python installation is
required.

## Verify the download

PowerShell:

```powershell
Get-FileHash .\FlowRemoteDemo.exe -Algorithm SHA256
```

Expected:

```text
EDF0C01A9C8D2F39E12A35315000BABBE65100757548F0D11F2128E9E54F4CE0
```

## Compatibility

Expected to run on Windows 10/11 x64 with a modern default browser. The file is
not code-signed, so Windows SmartScreen may show an unknown publisher warning.

## Rebuild

```powershell
uv sync
powershell -ExecutionPolicy Bypass -File scripts\build_demo_exe.ps1
```

This version includes source correction, saved business rules, background cleanup,
review undo and result previews. The launcher avoids reusing an older running version.

The executable includes FastAPI, Uvicorn, SQLite support, templates, static
assets, migrations, the local launcher and demonstration data generation.
