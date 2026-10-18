"""Bounded subprocess output and process-tree cleanup for scheduled attempts."""
import asyncio
import os
import signal
import subprocess


class WindowsJob:
    """Kill descendants when this Job Object closes, including after parent exit."""
    def __init__(self):
        import ctypes as c
        from ctypes import wintypes as w

        class Basic(c.Structure):
            _fields_ = [('process_time', c.c_int64), ('job_time', c.c_int64), ('flags', w.DWORD),
                        ('min_working', c.c_size_t), ('max_working', c.c_size_t), ('active', w.DWORD),
                        ('affinity', c.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]

        class IO(c.Structure):
            _fields_ = [(name, c.c_uint64) for name in ('read_ops', 'write_ops', 'other_ops', 'read', 'write', 'other')]

        class Extended(c.Structure):
            _fields_ = [('basic', Basic), ('io', IO), ('process_memory', c.c_size_t),
                        ('job_memory', c.c_size_t), ('peak_process', c.c_size_t), ('peak_job', c.c_size_t)]

        self.api = c.WinDLL('kernel32', use_last_error=True)
        self.api.CreateJobObjectW.argtypes, self.api.CreateJobObjectW.restype = [c.c_void_p, w.LPCWSTR], w.HANDLE
        self.api.SetInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
        self.api.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.api.OpenProcess.argtypes, self.api.OpenProcess.restype = [w.DWORD, w.BOOL, w.DWORD], w.HANDLE
        self.api.CloseHandle.argtypes = [w.HANDLE]
        self.handle = self.api.CreateJobObjectW(None, None)
        limits = Extended()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.handle or not self.api.SetInformationJobObject(self.handle, 9, c.byref(limits), c.sizeof(limits)):
            self.close()
            raise OSError('Cannot create process-tree containment job')

    def assign(self, pid):
        handle = self.api.OpenProcess(0x0101, False, pid)
        try:
            if not handle or not self.api.AssignProcessToJobObject(self.handle, handle):
                raise OSError('Cannot assign scheduled process to containment job')
        finally:
            if handle:
                self.api.CloseHandle(handle)

    def close(self):
        if getattr(self, 'handle', None):
            self.api.CloseHandle(self.handle)
            self.handle = None


async def run_process(*, argv=None, shell=None, cwd, payload=None, on_pid=None, output_limit=None):
    """Cancellation closes the process tree before this coroutine returns."""
    job = WindowsJob() if os.name == 'nt' else None
    options = {'cwd': cwd, 'stdin': asyncio.subprocess.PIPE if payload is not None else asyncio.subprocess.DEVNULL,
               'stdout': asyncio.subprocess.PIPE, 'stderr': asyncio.subprocess.PIPE}
    if os.name == 'nt':
        options['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        options['start_new_session'] = True
    process, readers = None, []
    buffers, exceeded = [bytearray(), bytearray()], [False, False]
    limit = output_limit or (4 * 1024 * 1024 if payload is not None else 4096)

    async def drain(stream, index):
        while chunk := await stream.read(65536):
            buffers[index].extend(chunk)
            if len(buffers[index]) > limit:
                exceeded[index] = True
                del buffers[index][:-limit]

    try:
        process = (await asyncio.create_subprocess_shell(shell, **options) if shell is not None
                   else await asyncio.create_subprocess_exec(*argv, **options))
        if job:
            job.assign(process.pid)
        if on_pid:
            on_pid(process.pid)
        readers = [asyncio.create_task(drain(process.stdout, 0)), asyncio.create_task(drain(process.stderr, 1))]
        if payload is not None:
            try:
                process.stdin.write(payload)
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                process.stdin.close()
        await process.wait()
    finally:
        # Also remove descendants left behind by a successfully exited shell.
        if job:
            job.close()
        if process is not None:
            if os.name != 'nt':
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            elif process.returncode is None:
                # Fallback if assignment failed before containment was established.
                killer = await asyncio.create_subprocess_exec('taskkill', '/PID', str(process.pid), '/T', '/F',
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                await killer.wait()
            await process.wait()
        if readers:
            await asyncio.gather(*readers)
    return {'returncode': process.returncode, 'stdout': buffers[0].decode('utf-8', errors='replace'),
            'stderr': buffers[1].decode('utf-8', errors='replace'), 'output_truncated': any(exceeded)}
