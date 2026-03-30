import glob
import json
import os
import re
import shutil
import socket
import subprocess
import time
from datetime import datetime

from smartdrive.infrastructure.settings import BASE_MOUNT, SMARTDRIVE_AUDIT_DIR


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
ENERGY_RATES_JSON_PATH = os.path.join(PROJECT_ROOT, "static", "data", "energy_rates.json")
DEFAULT_ENERGY_PRICE_EUR_PER_KWH = 0.11
DAILY_POWER_HISTORY_PATH = os.path.join(SMARTDRIVE_AUDIT_DIR, "system_power_daily.json")


def _read_text(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8") as file_handle:
            return file_handle.read().strip()
    except Exception:
        return None


def _read_float(path: str) -> float | None:
    raw_value = _read_text(path)
    if raw_value is None:
        return None
    try:
        return float(raw_value)
    except ValueError:
        return None


def _read_cpu_times() -> tuple[int, int] | None:
    raw_stat = _read_text("/proc/stat")
    if not raw_stat:
        return None

    first_line = raw_stat.splitlines()[0]
    parts = first_line.split()
    if len(parts) < 5 or parts[0] != "cpu":
        return None

    numeric_values = [int(value) for value in parts[1:]]
    idle = numeric_values[3] + (numeric_values[4] if len(numeric_values) > 4 else 0)
    total = sum(numeric_values)
    return total, idle


def _cpu_percent() -> float:
    first = _read_cpu_times()
    if first is None:
        return 0.0

    time.sleep(0.12)
    second = _read_cpu_times()
    if second is None:
        return 0.0

    total_delta = second[0] - first[0]
    idle_delta = second[1] - first[1]
    if total_delta <= 0:
        return 0.0

    busy_delta = total_delta - idle_delta
    return max(0.0, min(100.0, (busy_delta / total_delta) * 100.0))


def _memory_percent() -> float:
    meminfo_raw = _read_text("/proc/meminfo")
    if not meminfo_raw:
        return 0.0

    values_kb: dict[str, int] = {}
    for line in meminfo_raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        tokens = value.strip().split()
        if not tokens:
            continue
        try:
            values_kb[key] = int(tokens[0])
        except ValueError:
            continue

    total_kb = values_kb.get("MemTotal", 0)
    available_kb = values_kb.get("MemAvailable", 0)
    if total_kb <= 0:
        return 0.0

    used_kb = max(0, total_kb - available_kb)
    return max(0.0, min(100.0, (used_kb / total_kb) * 100.0))


def _disk_percent() -> float:
    candidate_path = BASE_MOUNT if os.path.exists(BASE_MOUNT) else "/"
    try:
        usage = shutil.disk_usage(candidate_path)
    except Exception:
        return 0.0

    if usage.total <= 0:
        return 0.0
    return max(0.0, min(100.0, (usage.used / usage.total) * 100.0))


def _temperature_celsius() -> float | None:
    thermal_paths = sorted(glob.glob("/sys/class/thermal/thermal_zone*/temp"))
    for thermal_path in thermal_paths:
        value = _read_float(thermal_path)
        if value is None:
            continue
        if value > 1000:
            value /= 1000.0
        if 0.0 < value < 150.0:
            return value

    try:
        command_output = subprocess.check_output(
            ["vcgencmd", "measure_temp"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=0.8,
        )
        match = re.search(r"temp=([0-9]+(?:\.[0-9]+)?)", command_output)
        if match:
            return float(match.group(1))
    except Exception:
        pass

    return None


def _power_watts() -> float | None:
    has_explicit_zero_reading = False

    for power_path in sorted(glob.glob("/sys/class/power_supply/*/power_now")):
        power_micro_watts = _read_float(power_path)
        if power_micro_watts is None:
            continue

        if power_micro_watts > 0:
            return power_micro_watts / 1_000_000.0
        if power_micro_watts == 0:
            has_explicit_zero_reading = True

    for battery_dir in sorted(glob.glob("/sys/class/power_supply/*")):
        current_micro_amp = _read_float(os.path.join(battery_dir, "current_now"))
        voltage_micro_volt = _read_float(os.path.join(battery_dir, "voltage_now"))
        if current_micro_amp is not None and voltage_micro_volt is not None and voltage_micro_volt > 0:
            power_w = (abs(current_micro_amp) * voltage_micro_volt) / 1_000_000_000_000.0
            if power_w > 0:
                return power_w
            has_explicit_zero_reading = True

    rapl_power_w = _power_watts_from_rapl()
    if rapl_power_w is not None:
        return rapl_power_w

    if has_explicit_zero_reading:
        return 0.0

    return None


def _is_ac_online() -> bool:
    for online_path in sorted(glob.glob("/sys/class/power_supply/*/online")):
        online_raw = _read_text(online_path)
        if online_raw == "1":
            return True
    return False


def _cpu_power_limit_watts() -> float | None:
    candidates = [
        "/sys/class/powercap/intel-rapl:0/constraint_0_power_limit_uw",
        "/sys/class/powercap/intel-rapl:0/constraint_0_max_power_uw",
        "/sys/class/powercap/intel-rapl:0/constraint_1_power_limit_uw",
        "/sys/class/powercap/intel-rapl:0/constraint_1_max_power_uw",
    ]

    for candidate_path in candidates:
        limit_uw = _read_float(candidate_path)
        if limit_uw and limit_uw > 0:
            return limit_uw / 1_000_000.0

    return None


def _estimate_power_watts(cpu_percent: float) -> float:
    power_cap_w = _cpu_power_limit_watts() or 45.0
    power_cap_w = max(12.0, min(125.0, power_cap_w))

    idle_w = min(12.0, max(5.0, power_cap_w * 0.2))
    estimated_w = idle_w + (max(0.0, min(100.0, cpu_percent)) / 100.0) * (power_cap_w - idle_w)
    return round(estimated_w, 2)


def _intel_gpu_usage_from_intel_gpu_top() -> list[dict]:
    usage_raw = _intel_gpu_busy_percent_from_intel_gpu_top()
    if usage_raw is None:
        return []

    return [{
        "name": "Intel iGPU",
        "usage_percent": max(0.0, min(100.0, usage_raw)),
    }]


def _intel_gpu_busy_percent_from_intel_gpu_top() -> float | None:
    intel_gpu_top_path = shutil.which("intel_gpu_top")
    if intel_gpu_top_path is None:
        return None

    candidate_commands = [[intel_gpu_top_path, "-J", "-s", "120"]]
    if shutil.which("sudo") is not None:
        candidate_commands.append(["sudo", "-n", intel_gpu_top_path, "-J", "-s", "120"])

    for command in candidate_commands:
        raw_output = ""
        try:
            completed = subprocess.run(
                command,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=1.0,
                check=False,
            )
            raw_output = completed.stdout or ""
        except subprocess.TimeoutExpired as exc:
            timed_out_output = exc.stdout
            if isinstance(timed_out_output, bytes):
                raw_output = timed_out_output.decode("utf-8", errors="ignore")
            else:
                raw_output = timed_out_output or ""

        if not raw_output:
            continue

        samples = _extract_json_dicts(raw_output)
        for sample in reversed(samples):
            busy = _intel_gpu_busy_from_intel_gpu_top_sample(sample)
            if busy is not None:
                return busy

    return None


def _extract_json_dicts(raw_output: str) -> list[dict]:
    decoder = json.JSONDecoder()
    parsed: list[dict] = []
    start_index = 0

    while start_index < len(raw_output):
        json_start = raw_output.find("{", start_index)
        if json_start == -1:
            break

        try:
            payload, consumed = decoder.raw_decode(raw_output[json_start:])
        except json.JSONDecodeError:
            start_index = json_start + 1
            continue

        if isinstance(payload, dict):
            parsed.append(payload)

        start_index = json_start + consumed

    return parsed


def _intel_gpu_busy_from_intel_gpu_top_sample(sample: dict) -> float | None:
    engines = sample.get("engines")
    if not isinstance(engines, dict):
        return None

    busy_values: list[float] = []
    for engine_data in engines.values():
        if not isinstance(engine_data, dict):
            continue
        busy = engine_data.get("busy")
        if isinstance(busy, (int, float)):
            busy_values.append(float(busy))

    if not busy_values:
        return None

    avg_busy = sum(busy_values) / len(busy_values)
    return max(0.0, min(100.0, avg_busy))


def _battery_metrics() -> dict:
    battery_dirs = sorted(glob.glob("/sys/class/power_supply/BAT*"))
    if not battery_dirs:
        return {
            "present": False,
            "capacity_percent": None,
            "status": None,
            "health_percent": None,
            "power_w": None,
        }

    battery_dir = battery_dirs[0]
    capacity_percent = _read_float(os.path.join(battery_dir, "capacity"))
    status = _read_text(os.path.join(battery_dir, "status"))

    charge_full = _read_float(os.path.join(battery_dir, "charge_full"))
    charge_full_design = _read_float(os.path.join(battery_dir, "charge_full_design"))

    health_percent = None
    if charge_full and charge_full_design and charge_full_design > 0:
        health_percent = max(0.0, min(100.0, (charge_full / charge_full_design) * 100.0))

    current_now = _read_float(os.path.join(battery_dir, "current_now"))
    voltage_now = _read_float(os.path.join(battery_dir, "voltage_now"))
    battery_power_w = None
    if current_now is not None and voltage_now is not None and voltage_now > 0:
        battery_power_w = (abs(current_now) * voltage_now) / 1_000_000_000_000.0

    return {
        "present": True,
        "capacity_percent": capacity_percent,
        "status": status,
        "health_percent": health_percent,
        "power_w": battery_power_w,
    }


def _gpu_usage() -> dict:
    entries = _intel_gpu_usage_from_intel_gpu_top()
    intel_avg = 0.0
    if entries:
        intel_avg = sum(item["usage_percent"] for item in entries) / len(entries)

    return {
        "entries": entries,
        "intel_percent": round(intel_avg, 1),
    }


def _load_daily_power_history() -> dict:
    try:
        with open(DAILY_POWER_HISTORY_PATH, "r", encoding="utf-8") as file_handle:
            data = json.load(file_handle)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {"months": {}}


def _save_daily_power_history(history: dict) -> None:
    try:
        os.makedirs(os.path.dirname(DAILY_POWER_HISTORY_PATH), exist_ok=True)
        with open(DAILY_POWER_HISTORY_PATH, "w", encoding="utf-8") as file_handle:
            json.dump(history, file_handle, ensure_ascii=True)
    except Exception:
        pass


def _update_daily_power_average(now: datetime, power_w: float) -> tuple[dict, str, str]:
    history = _load_daily_power_history()
    months = history.setdefault("months", {})

    month_key = f"{now.year:04d}-{now.month:02d}"
    month_bucket = months.setdefault(month_key, {"days": {}})
    day_key = f"{now.day:02d}"
    day_bucket = month_bucket.setdefault("days", {}).setdefault(day_key, {
        "samples": 0,
        "avg_power_w": 0.0,
    })

    samples = int(day_bucket.get("samples", 0))
    avg_power_w = float(day_bucket.get("avg_power_w", 0.0))
    new_samples = samples + 1
    new_avg = ((avg_power_w * samples) + power_w) / new_samples

    day_bucket["samples"] = new_samples
    day_bucket["avg_power_w"] = round(new_avg, 4)
    day_bucket["updated_at"] = now.isoformat(timespec="seconds")

    # Keep only the current and previous two months to avoid unbounded growth.
    month_keys = sorted(months.keys())
    if len(month_keys) > 3:
        for old_month_key in month_keys[:-3]:
            months.pop(old_month_key, None)

    return history, month_key, day_key


def _finalize_closed_days(
    month_days: dict,
    current_day_key: str,
    energy_price_eur_per_kwh: float,
    now: datetime,
) -> None:
    for day_key, day_bucket in month_days.items():
        if not isinstance(day_bucket, dict):
            continue
        if day_key >= current_day_key:
            continue
        if isinstance(day_bucket.get("closed_cost_eur"), (int, float)):
            continue

        avg_power_w = day_bucket.get("avg_power_w")
        if not isinstance(avg_power_w, (int, float)):
            continue
        if avg_power_w < 0:
            continue

        day_kwh = (float(avg_power_w) / 1000.0) * 24.0
        day_bucket["closed_kwh"] = round(day_kwh, 6)
        day_bucket["closed_cost_eur"] = round(day_kwh * energy_price_eur_per_kwh, 6)
        day_bucket["closed_at"] = now.isoformat(timespec="seconds")


def _month_spend_until_now(
    now: datetime,
    energy_price_eur_per_kwh: float,
    current_power_w: float,
) -> tuple[float, float, float]:
    history, month_key, current_day_key = _update_daily_power_average(now, current_power_w)
    months = history.setdefault("months", {})
    month_bucket = months.setdefault(month_key, {"days": {}})
    month_days = month_bucket.setdefault("days", {})

    _finalize_closed_days(
        month_days=month_days,
        current_day_key=current_day_key,
        energy_price_eur_per_kwh=energy_price_eur_per_kwh,
        now=now,
    )

    closed_days_cost_eur = 0.0
    for day_key, day_bucket in month_days.items():
        if day_key >= current_day_key or not isinstance(day_bucket, dict):
            continue
        closed_cost = day_bucket.get("closed_cost_eur")
        if isinstance(closed_cost, (int, float)):
            closed_days_cost_eur += float(closed_cost)

    today_bucket = month_days.get(current_day_key, {})
    today_avg_power_w = current_power_w
    if isinstance(today_bucket, dict):
        avg_power_w = today_bucket.get("avg_power_w")
        if isinstance(avg_power_w, (int, float)) and avg_power_w >= 0:
            today_avg_power_w = float(avg_power_w)

    elapsed_today_hours = (
        now.hour
        + (now.minute / 60.0)
        + (now.second / 3600.0)
    )
    today_kwh = (today_avg_power_w / 1000.0) * max(0.0, elapsed_today_hours)
    today_cost_eur = today_kwh * energy_price_eur_per_kwh

    month_bucket["closed_days_cost_eur"] = round(closed_days_cost_eur, 6)
    month_bucket["today_partial_cost_eur"] = round(today_cost_eur, 6)
    month_bucket["updated_at"] = now.isoformat(timespec="seconds")

    _save_daily_power_history(history)

    month_spent_eur = closed_days_cost_eur + today_cost_eur
    return month_spent_eur, today_cost_eur, closed_days_cost_eur


def _power_watts_from_rapl() -> float | None:
    energy_path = "/sys/class/powercap/intel-rapl:0/energy_uj"
    if not os.path.exists(energy_path):
        return None

    first_energy = _read_float(energy_path)
    if first_energy is None:
        return None

    sample_seconds = 0.15
    time.sleep(sample_seconds)

    second_energy = _read_float(energy_path)
    if second_energy is None:
        return None

    max_range = _read_float("/sys/class/powercap/intel-rapl:0/max_energy_range_uj")
    if second_energy < first_energy and max_range:
        second_energy += max_range

    delta_energy_uj = second_energy - first_energy
    if delta_energy_uj <= 0:
        return None

    power_w = (delta_energy_uj / 1_000_000.0) / sample_seconds
    if power_w <= 0:
        return None

    return min(power_w, 500.0)


def _energy_price_eur_per_kwh() -> float:
    try:
        with open(ENERGY_RATES_JSON_PATH, "r", encoding="utf-8") as file_handle:
            raw_config = json.load(file_handle)
    except Exception:
        return DEFAULT_ENERGY_PRICE_EUR_PER_KWH

    if not isinstance(raw_config, dict):
        return DEFAULT_ENERGY_PRICE_EUR_PER_KWH

    raw_eur = raw_config.get("energy_price_eur_per_kwh")
    if isinstance(raw_eur, (int, float)) and raw_eur > 0:
        return float(raw_eur)

    raw_cents = raw_config.get("energy_price_cts_per_kwh")
    if isinstance(raw_cents, (int, float)) and raw_cents > 0:
        return float(raw_cents) / 100.0

    return DEFAULT_ENERGY_PRICE_EUR_PER_KWH


def _uptime_human() -> str:
    raw_uptime = _read_text("/proc/uptime")
    if not raw_uptime:
        return "N/D"

    try:
        seconds = int(float(raw_uptime.split()[0]))
    except (ValueError, IndexError):
        return "N/D"

    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)

    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    return f"{hours}h {minutes}m"


def read_system_stats() -> dict:
    cpu_cores = os.cpu_count() or 1
    cpu_percent = _cpu_percent()
    measured_power_w = _power_watts()
    ac_online = _is_ac_online()

    power_source = "measured"
    if measured_power_w is None:
        power_w = _estimate_power_watts(cpu_percent)
        power_source = "estimated"
    elif measured_power_w == 0.0 and ac_online:
        power_w = _estimate_power_watts(cpu_percent)
        power_source = "estimated_ac_fallback"
    else:
        power_w = measured_power_w

    energy_price_eur_per_kwh = _energy_price_eur_per_kwh()
    gpu_usage = _gpu_usage()
    battery = _battery_metrics()
    now = datetime.now()

    cost_per_hour_eur = None
    cost_per_day_eur = None
    cost_per_month_eur = None
    cost_month_to_date_eur = None
    cost_today_so_far_eur = None
    cost_closed_days_eur = None
    if power_w is not None:
        power_kw = power_w / 1000.0
        cost_per_hour_eur = power_kw * energy_price_eur_per_kwh
        cost_per_day_eur = cost_per_hour_eur * 24.0
        cost_per_month_eur = cost_per_day_eur * 30.0

        (
            cost_month_to_date_eur,
            cost_today_so_far_eur,
            cost_closed_days_eur,
        ) = _month_spend_until_now(
            now=now,
            energy_price_eur_per_kwh=energy_price_eur_per_kwh,
            current_power_w=power_w,
        )

    return {
        "hostname": socket.gethostname(),
        "temperature_c": _temperature_celsius(),
        "power_w": power_w,
        "power_source": power_source,
        "ac_online": ac_online,
        "energy_price_eur_per_kwh": energy_price_eur_per_kwh,
        "estimated_cost_per_hour_eur": cost_per_hour_eur,
        "estimated_cost_per_day_eur": cost_per_day_eur,
        "estimated_cost_per_month_eur": cost_per_month_eur,
        "estimated_cost_month_to_date_eur": cost_month_to_date_eur,
        "estimated_cost_today_so_far_eur": cost_today_so_far_eur,
        "estimated_cost_closed_days_eur": cost_closed_days_eur,
        "cpu_cores": cpu_cores,
        "cpu_percent": cpu_percent,
        "memory_percent": _memory_percent(),
        "disk_percent": _disk_percent(),
        "battery": battery,
        "uptime": _uptime_human(),
        "gpu_usage": gpu_usage,
    }