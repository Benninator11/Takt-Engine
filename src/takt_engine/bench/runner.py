"""CPU/memory stability benchmark with telemetry and thermal stop threshold."""
from dataclasses import dataclass
import shutil
import subprocess
import threading
import time
from typing import Callable, Optional

from takt_engine.core.runtime import RuntimeStatus, read_status


@dataclass(frozen=True)
class BenchmarkResult:
    passed: bool
    duration_seconds: int
    peak_temperature_c: Optional[float]
    final_status: RuntimeStatus
    return_code: int
    summary: str
    threads: int = 1
    requested_duration_seconds: int = 0


def run_benchmark(
    duration_seconds: int,
    threads: int,
    on_update: Callable[[str, RuntimeStatus, int], None] | None = None,
    stop_event: threading.Event | None = None,
    status_reader: Callable[[], RuntimeStatus] = read_status,
    process_factory: Callable[..., subprocess.Popen] = subprocess.Popen,
) -> BenchmarkResult:
    if not 10 <= int(duration_seconds) <= 600:
        raise ValueError("Die Testdauer muss zwischen 10 und 600 Sekunden liegen.")
    if not 1 <= int(threads) <= 64:
        raise ValueError("Die Thread-Anzahl muss zwischen 1 und 64 liegen.")
    if not shutil.which("stress-ng"):
        raise RuntimeError("stress-ng ist nicht installiert. Bitte scripts/install-deps.sh ausführen.")
    stop_event = stop_event or threading.Event()
    duration_seconds, threads = int(duration_seconds), int(threads)
    initial = status_reader()
    peak_temp = initial.temperature_c
    observed_flags_during_test = bool(initial.active_throttling or initial.undervoltage)
    started = time.monotonic()
    deadline = started + duration_seconds
    command = [
        "stress-ng", "--cpu", str(threads), "--cpu-method", "matrixprod",
        "--vm", "1", "--vm-bytes", "20%", "--timeout", f"{duration_seconds}s",
        "--metrics-brief",
    ]
    process = process_factory(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    stop_reason = ""
    latest = initial
    try:
        while process.poll() is None:
            if stop_event.is_set():
                stop_reason = "Test durch den Benutzer gestoppt."
                process.terminate()
                break
            latest = status_reader()
            observed_flags_during_test = observed_flags_during_test or bool(latest.active_throttling or latest.undervoltage)
            if latest.temperature_c is not None:
                peak_temp = latest.temperature_c if peak_temp is None else max(peak_temp, latest.temperature_c)
                if latest.temperature_c >= 80.0:
                    stop_reason = "Sicherheitstopp bei 80 °C: Temperatur zu hoch."
                    process.terminate()
                    break
            remaining = max(0, int(deadline - time.monotonic()))
            if on_update:
                on_update("Benchmark läuft", latest, duration_seconds - remaining)
            if time.monotonic() >= deadline:
                break
            time.sleep(1)
        try:
            output, _ = process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            output, _ = process.communicate()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()

    return_code = int(process.returncode or 0)
    elapsed = min(duration_seconds, max(0, int(time.monotonic() - started)))
    latest = status_reader()
    current_flags = latest.active_throttling or latest.undervoltage
    new_historical_flags = latest.historical_flags and not initial.historical_flags
    thermal_fail = peak_temp is None or peak_temp >= 80.0
    stopped_early = bool(stop_reason)
    passed = (return_code == 0 and not current_flags and not observed_flags_during_test
              and not new_historical_flags and not thermal_fail and not stopped_early
              and elapsed >= duration_seconds - 1)
    pieces = []
    if passed:
        pieces.append("Bestanden: kein aktives Throttling und Temperatur unter 80 °C erkannt.")
    else:
        pieces.append("Nicht bestanden oder vorzeitig beendet.")
    if stop_reason:
        pieces.append(stop_reason)
    if current_flags or observed_flags_during_test or new_historical_flags:
        pieces.append("Unterspannung oder Drosselung wurde während des Tests erkannt.")
    if peak_temp is None:
        pieces.append("Keine Temperaturmessung verfügbar; der Test kann daher nicht als bestanden gelten.")
    if latest.historical_flags:
        pieces.append("Hinweis: historische Throttling-/Unterspannungsflags sind gesetzt.")
    if peak_temp is not None:
        pieces.append(f"Maximal gemessene Temperatur: {peak_temp:.1f} °C.")
    if return_code not in (0, -15, -9):
        pieces.append(f"stress-ng beendete sich mit Code {return_code}.")
    return BenchmarkResult(
        passed, elapsed, peak_temp, latest, return_code, " ".join(pieces),
        threads=threads, requested_duration_seconds=duration_seconds,
    )
