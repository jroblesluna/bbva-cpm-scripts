using System;
using System.Runtime.InteropServices;

namespace AlwaysPrintService.UserSession
{
    /// <summary>
    /// P/Invoke declarations for launching a process inside the interactive user session
    /// from a Session 0 Windows Service.
    /// </summary>
    internal static class NativeMethods
    {
        // ── kernel32 ────────────────────────────────────────────────────────────

        [DllImport("kernel32.dll", SetLastError = true)]
        internal static extern uint WTSGetActiveConsoleSessionId();

        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        internal static extern bool CloseHandle(IntPtr hObject);

        // ── wtsapi32 ────────────────────────────────────────────────────────────

        [DllImport("wtsapi32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        internal static extern bool WTSQueryUserToken(uint sessionId, out IntPtr phToken);

        // ── advapi32 ────────────────────────────────────────────────────────────

        [DllImport("advapi32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        internal static extern bool DuplicateTokenEx(
            IntPtr hExistingToken,
            uint dwDesiredAccess,
            ref SECURITY_ATTRIBUTES lpTokenAttributes,
            SECURITY_IMPERSONATION_LEVEL impersonationLevel,
            TOKEN_TYPE tokenType,
            out IntPtr phNewToken);

        [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        [return: MarshalAs(UnmanagedType.Bool)]
        internal static extern bool CreateProcessAsUser(
            IntPtr hToken,
            string? lpApplicationName,
            string lpCommandLine,
            ref SECURITY_ATTRIBUTES lpProcessAttributes,
            ref SECURITY_ATTRIBUTES lpThreadAttributes,
            [MarshalAs(UnmanagedType.Bool)] bool bInheritHandles,
            uint dwCreationFlags,
            IntPtr lpEnvironment,
            string? lpCurrentDirectory,
            ref STARTUPINFO lpStartupInfo,
            out PROCESS_INFORMATION lpProcessInformation);

        // ── userenv ─────────────────────────────────────────────────────────────

        [DllImport("userenv.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        internal static extern bool CreateEnvironmentBlock(
            out IntPtr lpEnvironment,
            IntPtr hToken,
            [MarshalAs(UnmanagedType.Bool)] bool bInherit);

        [DllImport("userenv.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        internal static extern bool DestroyEnvironmentBlock(IntPtr lpEnvironment);

        // ── Constants ───────────────────────────────────────────────────────────

        internal const uint TOKEN_ALL_ACCESS        = 0xF01FF;
        internal const uint CREATE_UNICODE_ENVIRONMENT = 0x00000400;
        internal const uint NORMAL_PRIORITY_CLASS   = 0x00000020;
        internal const uint NO_ACTIVE_SESSION       = 0xFFFFFFFF;

        // ── Structs ─────────────────────────────────────────────────────────────

        [StructLayout(LayoutKind.Sequential)]
        internal struct SECURITY_ATTRIBUTES
        {
            public int nLength;
            public IntPtr lpSecurityDescriptor;
            [MarshalAs(UnmanagedType.Bool)]
            public bool bInheritHandle;
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        internal struct STARTUPINFO
        {
            public int    cb;
            public string? lpReserved;
            public string? lpDesktop;
            public string? lpTitle;
            public uint   dwX, dwY, dwXSize, dwYSize;
            public uint   dwXCountChars, dwYCountChars;
            public uint   dwFillAttribute;
            public uint   dwFlags;
            public short  wShowWindow;
            public short  cbReserved2;
            public IntPtr lpReserved2;
            public IntPtr hStdInput, hStdOutput, hStdError;
        }

        [StructLayout(LayoutKind.Sequential)]
        internal struct PROCESS_INFORMATION
        {
            public IntPtr hProcess;
            public IntPtr hThread;
            public uint   dwProcessId;
            public uint   dwThreadId;
        }

        internal enum SECURITY_IMPERSONATION_LEVEL
        {
            SecurityAnonymous,
            SecurityIdentification,
            SecurityImpersonation,
            SecurityDelegation
        }

        internal enum TOKEN_TYPE
        {
            TokenPrimary = 1,
            TokenImpersonation
        }
    }
}
