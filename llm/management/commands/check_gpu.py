from __future__ import annotations

from django.core.management.base import BaseCommand

from llm.gpu_probe import probe_gpu
from llm.runtime import resolve_inference_target


class Command(BaseCommand):
    help = "Report GPU status on shared hosts (read-only; never stops other jobs)."

    def handle(self, *args, **options):
        probe = probe_gpu()
        _, device = resolve_inference_target()

        if probe.gpu_name:
            self.stdout.write(f"GPU: {probe.gpu_name}")
        if probe.memory_total_mib is not None:
            self.stdout.write(
                f"VRAM: {probe.memory_used_mib} / {probe.memory_total_mib} MiB used "
                f"({probe.memory_free_mib} MiB free)"
            )

        self.stdout.write(f"PyTorch CUDA available to Maisha: {probe.torch_cuda_available}")
        self.stdout.write(f"Maisha inference target: {device}")

        if probe.foreign_processes:
            self.stdout.write("\nOther GPU jobs (left untouched):")
            for p in probe.foreign_processes:
                owner = p.owner or "unknown"
                self.stdout.write(
                    f"  - PID {p.pid} ({owner}): {p.process_name} [{p.used_mib} MiB]"
                )

        for note in probe.notes:
            self.stdout.write(self.style.WARNING(f"\n{note}"))

        if device == "cpu":
            self.stdout.write(
                self.style.WARNING(
                    "\nMaisha will use CPU inference. This is expected on shared "
                    "machines while another GPU job is active."
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS("\nMaisha can use the GPU."))
