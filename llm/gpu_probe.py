"""Read-only GPU discovery for shared machines.

Never kills or signals other users' processes. Reports who is using the GPU
so operators can coordinate, and helps Maisha pick CPU vs CUDA safely.
"""
from __future__ import annotations

import csv
import io
import subprocess
from dataclasses import dataclass, field


@dataclass
class GpuProcess:
    pid: int
    process_name: str
    used_mib: int
    owner: str | None = None


@dataclass
class GpuProbeResult:
    nvidia_smi_available: bool = False
    gpu_name: str | None = None
    memory_total_mib: int | None = None
    memory_used_mib: int | None = None
    memory_free_mib: int | None = None
    foreign_processes: list[GpuProcess] = field(default_factory=list)
    torch_cuda_available: bool = False
    torch_cuda_error: str | None = None
    recommended_device: str = "cpu"
    notes: list[str] = field(default_factory=list)


def _pid_owner(pid: int) -> str | None:
    try:
        with open(f"/proc/{pid}/status", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("Uid:"):
                    uid = int(line.split()[1])
                    break
            else:
                return None
        import pwd

        return pwd.getpwuid(uid).pw_name
    except (FileNotFoundError, KeyError, PermissionError, ValueError):
        return None


def probe_gpu(my_pid: int | None = None) -> GpuProbeResult:
    """Inspect GPU state without modifying anything."""
    import os

    my_pid = my_pid or os.getpid()
    result = GpuProbeResult()

    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.used,memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            result.nvidia_smi_available = True
            row = next(csv.reader(io.StringIO(proc.stdout.strip())))
            if len(row) >= 4:
                result.gpu_name = row[0].strip()
                result.memory_total_mib = int(float(row[1]))
                result.memory_used_mib = int(float(row[2]))
                result.memory_free_mib = int(float(row[3]))
        elif proc.stderr and "Driver/library version mismatch" in proc.stderr:
            result.notes.append(
                "NVIDIA driver/library version mismatch: the loaded kernel module "
                "does not match the installed driver packages (often after an apt "
                "upgrade without reboot). Reboot the server, or reload the nvidia "
                "modules with sudo, then restart bd-backend."
            )
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        result.notes.append("nvidia-smi is not available on this host.")

    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,process_name,used_gpu_memory",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            for row in csv.reader(io.StringIO(proc.stdout.strip())):
                if len(row) < 3:
                    continue
                pid = int(row[0])
                used = int(float(row[2]))
                owner = _pid_owner(pid)
                entry = GpuProcess(
                    pid=pid,
                    process_name=row[1].strip(),
                    used_mib=used,
                    owner=owner,
                )
                if pid != my_pid:
                    result.foreign_processes.append(entry)
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass

    try:
        import torch

        result.torch_cuda_available = torch.cuda.is_available()
        if result.torch_cuda_available:
            result.recommended_device = "cuda"
        else:
            err = getattr(torch.cuda, "_lazy_init_error", None)
            if err is not None:
                result.torch_cuda_error = str(err)
    except Exception as exc:
        result.torch_cuda_error = str(exc)

    if not result.torch_cuda_available:
        result.recommended_device = "cpu"
        if result.foreign_processes:
            owners = ", ".join(
                f"PID {p.pid} ({p.owner or 'unknown'}) using {p.used_mib} MiB"
                for p in result.foreign_processes
            )
            result.notes.append(
                "GPU memory is in use by other processes on this shared machine: "
                f"{owners}. Maisha will not interfere with them."
            )
        if result.torch_cuda_error:
            result.notes.append(
                "PyTorch cannot open a new CUDA context on this host right now. "
                "Inference will use CPU until the GPU is free or an admin resolves "
                "the driver state (often a reboot or coordinated GPU handoff)."
            )
    elif result.foreign_processes and result.memory_free_mib is not None:
        if result.memory_free_mib < 8000:
            result.notes.append(
                f"Only ~{result.memory_free_mib} MiB GPU memory appears free. "
                "Large models may fail to load; prefer llama3.2-3b or set LLM_DEVICE=cpu."
            )

    return result


def probe_gpu_dict() -> dict:
    probe = probe_gpu()
    return {
        "nvidia_smi_available": probe.nvidia_smi_available,
        "gpu_name": probe.gpu_name,
        "memory_total_mib": probe.memory_total_mib,
        "memory_used_mib": probe.memory_used_mib,
        "memory_free_mib": probe.memory_free_mib,
        "torch_cuda_available": probe.torch_cuda_available,
        "torch_cuda_error": probe.torch_cuda_error,
        "recommended_device": probe.recommended_device,
        "foreign_processes": [
            {
                "pid": p.pid,
                "owner": p.owner,
                "process_name": p.process_name,
                "used_mib": p.used_mib,
            }
            for p in probe.foreign_processes
        ],
        "notes": probe.notes,
    }
