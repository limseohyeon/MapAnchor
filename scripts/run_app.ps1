$ErrorActionPreference = 'Stop'

# Windows PowerShell 5.1: keep Korean console output readable (UTF-8).
if ($PSVersionTable.PSVersion.Major -lt 6) {
    try {
        chcp 65001 | Out-Null
        $utf8 = New-Object System.Text.UTF8Encoding $false
        [Console]::InputEncoding = $utf8
        [Console]::OutputEncoding = $utf8
        $OutputEncoding = $utf8
    } catch {
    }
}
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

function Resolve-PythonPath {
    if ($env:DWG_MAP_PYTHON -and (Test-Path -LiteralPath $env:DWG_MAP_PYTHON)) {
        return $env:DWG_MAP_PYTHON
    }

    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'codex-windspeed-map-venv\Scripts\python.exe'),
        'C:\venvs\dwg-map\Scripts\python.exe',
        (Join-Path $projectRoot '.venv\Scripts\python.exe')
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }

    foreach ($commandName in @('py', 'python')) {
        $command = Get-Command $commandName -ErrorAction SilentlyContinue
        if ($command) {
            return $command.Source
        }
    }

    return $null
}

function Stop-PortListeners {
    param([int[]]$Ports)

    foreach ($port in $Ports) {
        $listenerIds = @(
            Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
                Select-Object -ExpandProperty OwningProcess -Unique
        )
        foreach ($processId in $listenerIds) {
            if ($processId -and $processId -gt 0) {
                & taskkill.exe /PID $processId /T /F 2>$null | Out-Null
            }
        }
    }
}

# Job Object + 콘솔 종료(Ctrl+C / 창 닫기) 시 자식 프로세스 트리를 함께 종료한다.
Add-Type -TypeDefinition @"
using System;
using System.Collections.Concurrent;
using System.Diagnostics;
using System.Runtime.InteropServices;

public static class DwGMapProcessHost
{
    private static readonly ConcurrentDictionary<int, byte> ManagedPids =
        new ConcurrentDictionary<int, byte>();
    private static IntPtr JobHandle = IntPtr.Zero;
    private static ConsoleCtrlDelegate CtrlHandler;
    private static bool Stopping;

    private const int JobObjectExtendedLimitInformation = 9;
    private const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000;
    private const uint CTRL_C_EVENT = 0;
    private const uint CTRL_BREAK_EVENT = 1;
    private const uint CTRL_CLOSE_EVENT = 2;
    private const uint CTRL_LOGOFF_EVENT = 5;
    private const uint CTRL_SHUTDOWN_EVENT = 6;

    private delegate bool ConsoleCtrlDelegate(uint ctrlType);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CreateJobObject(IntPtr lpJobAttributes, string lpName);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetInformationJobObject(
        IntPtr hJob, int jobObjectInfoClass, IntPtr lpJobObjectInfo, uint cbJobObjectInfoLength);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AssignProcessToJobObject(IntPtr hJob, IntPtr hProcess);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr hObject);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetConsoleCtrlHandler(ConsoleCtrlDelegate handler, bool add);

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_BASIC_LIMIT_INFORMATION
    {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct IO_COUNTERS
    {
        public ulong ReadOperationCount;
        public ulong WriteOperationCount;
        public ulong OtherOperationCount;
        public ulong ReadTransferCount;
        public ulong WriteTransferCount;
        public ulong OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    {
        public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
        public IO_COUNTERS IoInfo;
        public UIntPtr ProcessMemoryLimit;
        public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed;
        public UIntPtr PeakJobMemoryUsed;
    }

    public static void Initialize()
    {
        if (JobHandle != IntPtr.Zero)
        {
            return;
        }

        JobHandle = CreateJobObject(IntPtr.Zero, null);
        if (JobHandle == IntPtr.Zero)
        {
            throw new InvalidOperationException(
                "CreateJobObject failed: " + Marshal.GetLastWin32Error());
        }

        var info = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        int length = Marshal.SizeOf(typeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION));
        IntPtr ptr = Marshal.AllocHGlobal(length);
        try
        {
            Marshal.StructureToPtr(info, ptr, false);
            if (!SetInformationJobObject(
                JobHandle, JobObjectExtendedLimitInformation, ptr, (uint)length))
            {
                throw new InvalidOperationException(
                    "SetInformationJobObject failed: " + Marshal.GetLastWin32Error());
            }
        }
        finally
        {
            Marshal.FreeHGlobal(ptr);
        }

        CtrlHandler = new ConsoleCtrlDelegate(HandleConsoleCtrl);
        if (!SetConsoleCtrlHandler(CtrlHandler, true))
        {
            throw new InvalidOperationException(
                "SetConsoleCtrlHandler failed: " + Marshal.GetLastWin32Error());
        }
    }

    public static void Track(int processId)
    {
        using (var process = Process.GetProcessById(processId))
        {
            if (!AssignProcessToJobObject(JobHandle, process.Handle))
            {
                throw new InvalidOperationException(
                    "AssignProcessToJobObject failed: " + Marshal.GetLastWin32Error());
            }
        }
        ManagedPids[processId] = 0;
    }

    public static void StopAll()
    {
        if (Stopping)
        {
            return;
        }
        Stopping = true;

        foreach (var processId in ManagedPids.Keys)
        {
            KillTree(processId);
        }
        ManagedPids.Clear();

        if (JobHandle != IntPtr.Zero)
        {
            CloseHandle(JobHandle);
            JobHandle = IntPtr.Zero;
        }
    }

    private static bool HandleConsoleCtrl(uint ctrlType)
    {
        if (ctrlType == CTRL_C_EVENT ||
            ctrlType == CTRL_BREAK_EVENT ||
            ctrlType == CTRL_CLOSE_EVENT ||
            ctrlType == CTRL_LOGOFF_EVENT ||
            ctrlType == CTRL_SHUTDOWN_EVENT)
        {
            StopAll();
        }
        return false;
    }

    private static void KillTree(int processId)
    {
        try
        {
            using (var kill = Process.Start(new ProcessStartInfo
            {
                FileName = "taskkill.exe",
                Arguments = "/PID " + processId + " /T /F",
                CreateNoWindow = true,
                UseShellExecute = false
            }))
            {
                if (kill != null)
                {
                    kill.WaitForExit(5000);
                }
            }
        }
        catch
        {
        }
    }
}
"@

$pythonPath = Resolve-PythonPath
if (-not $pythonPath) {
    Write-Host 'Python 환경을 찾지 못했습니다.' -ForegroundColor Red
    Write-Host '가상환경을 만든 뒤 DWG_MAP_PYTHON에 python.exe 경로를 지정하세요.'
    Write-Host '예: $env:DWG_MAP_PYTHON = "C:\venvs\dwg-map\Scripts\python.exe"'
    exit 1
}

$env:DWG_MAP_PYTHON = $pythonPath

Write-Host "Python: $pythonPath"
Write-Host '기존 API/Streamlit 프로세스가 있으면 정리합니다...'
Stop-PortListeners -Ports @(8000, 8501)
Start-Sleep -Milliseconds 500

$backend = $null
$frontend = $null

try {
    [DwGMapProcessHost]::Initialize()

    Write-Host '백엔드(API)와 프론트(Streamlit)를 시작합니다...'
    Write-Host '  API:       http://127.0.0.1:8000'
    Write-Host '  Streamlit: http://localhost:8501'
    Write-Host ''
    Write-Host '이 창을 닫거나 Ctrl+C 를 누르면 API/프론트가 함께 종료됩니다.' -ForegroundColor Yellow
    Write-Host ''
    Write-Host '주의: run_backend.ps1 과 동시에 실행하지 마세요. 포트 8000은 하나만 씁니다.' -ForegroundColor DarkYellow

    # API runs in a hidden console; this host window is the only visible terminal.
    $backendCmd = @(
        '/c',
        "title DWG Map API & `"$pythonPath`" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --log-level warning --no-access-log"
    )
    $backend = Start-Process `
        -FilePath 'cmd.exe' `
        -ArgumentList $backendCmd `
        -WorkingDirectory $projectRoot `
        -PassThru `
        -WindowStyle Hidden
    [DwGMapProcessHost]::Track([int]$backend.Id)

    Start-Sleep -Seconds 2

    $frontend = Start-Process `
        -FilePath $pythonPath `
        -ArgumentList @(
            '-m', 'streamlit', 'run', 'frontend/app.py',
            '--server.headless', 'true',
            '--browser.gatherUsageStats', 'false'
        ) `
        -WorkingDirectory $projectRoot `
        -PassThru `
        -WindowStyle Hidden
    [DwGMapProcessHost]::Track([int]$frontend.Id)

    Start-Sleep -Seconds 3
    Start-Process 'http://localhost:8501'

    Write-Host ''
    Write-Host '실행 중입니다. 종료할 때까지 이 창을 유지하세요.' -ForegroundColor Green

    while ($true) {
        if ($backend.HasExited -or $frontend.HasExited) {
            if ($backend.HasExited) {
                Write-Host "API 프로세스가 종료되었습니다. (exit=$($backend.ExitCode))" -ForegroundColor Red
            }
            if ($frontend.HasExited) {
                Write-Host "Streamlit 프로세스가 종료되었습니다. (exit=$($frontend.ExitCode))" -ForegroundColor Red
            }
            break
        }
        Start-Sleep -Seconds 1
    }
}
finally {
    [DwGMapProcessHost]::StopAll()
    Stop-PortListeners -Ports @(8000, 8501)
    Write-Host '앱 프로세스를 종료했습니다.'
}
