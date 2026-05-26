import os
import select
import socket
import subprocess
import sys
import termios
import time
import tty

# Add project src and scripts to sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(project_root, "src"))
sys.path.insert(0, os.path.join(project_root, "scripts"))

from update_env import update_env

import red_pill.config as cfg
from red_pill.core.paths import get_config_dir, get_data_dir
from red_pill.telemetry import sentinel


def get_key_nonblocking(timeout=1.0):
	fd = sys.stdin.fileno()
	if not os.isatty(fd):
		# Fallback if not interactive terminal
		time.sleep(timeout)
		return None
	old_settings = termios.tcgetattr(fd)
	try:
		tty.setraw(sys.stdin.fileno())
		rlist, _, _ = select.select([sys.stdin], [], [], timeout)
		if rlist:
			key = sys.stdin.read(1)
			return key
	finally:
		termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
	return None


def check_port(port):
	try:
		with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
			s.settimeout(0.5)
			s.connect(("127.0.0.1", port))
			return True
	except Exception:
		return False


def is_service_active(service_name):
	try:
		res = subprocess.run(["systemctl", "--user", "is-active", service_name], capture_output=True, text=True)
		return res.stdout.strip() == "active"
	except Exception:
		return False


def run_service_command(action, service_name):
	try:
		subprocess.run(["systemctl", "--user", action, service_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
		return True
	except Exception:
		return False


def purge_persona_cache():
	cache_path = os.path.join(get_data_dir(), "bunker_persona_cache.json")
	if os.path.exists(cache_path):
		try:
			os.remove(cache_path)
			return True
		except Exception:
			return False
	return False


def print_interface(stats, config):
	# Clear screen using ANSI escape codes
	sys.stdout.write("\033[H\033[J")
	sys.stdout.flush()

	print("\033[38;5;129m┌──────────────────────────────────────────────────────────────┐\033[0m")
	print("\033[38;5;129m│             BÜNKER TACTICAL CONTROL PANEL (v7.1.0)           │\033[0m")
	print("\033[38;5;129m└──────────────────────────────────────────────────────────────┘\033[0m")

	# Hardware Telemetry Panel
	print("\033[96m[ TELEMETRÍA DE HARDWARE ]\033[0m")
	cpu_info = f"CPU: {stats['cpu']['usage_percent']}%"
	if stats["cpu"].get("temp"):
		cpu_info += f" @ {stats['cpu']['temp']}°C"
	mem_info = f"RAM: {stats['memory']['percent']}% ({stats['memory']['available_gb']} GB libre)"
	print(f"  {cpu_info} | {mem_info}")

	# GPU Info
	if stats.get("gpu"):
		for g in stats["gpu"]:
			gpu_type = g.get("type", "GPU")
			gpu_name = g.get("name", "Unknown")
			gpu_usage = g.get("usage", 0)
			gpu_temp = g.get("temp", 0.0)
			gpu_mem = g.get("memory", "N/A")
			print(f"  [{gpu_type}] {gpu_name}: {gpu_usage}% @ {gpu_temp}°C | VRAM: {gpu_mem}")
	else:
		print("  [GPU] No se detecta GPU compatible (CUDA/ROCm).")

	# Qdrant status
	qdrant_status = "\033[92mONLINE\033[0m" if check_port(6333) else "\033[91mOFFLINE\033[0m"
	print(f"  Base Vectorial Qdrant (Puerto 6333): {qdrant_status}")

	# Pain Signals / Minions
	active_signals = stats.get("immune_system", {}).get("active_signals", [])
	signals_count = len(active_signals)
	minions_unread = stats.get("immune_system", {}).get("minion_inbox_unread", 0)
	print(f"  Señales de Dolor Activas: {signals_count} | Minion Inbox No Leídos: {minions_unread}")

	print("\n\033[96m[ PARÁMETROS TÁCTICOS EN CALIENTE ]\033[0m")
	# EMERGENCY_CLOUD_OVERRIDE
	cloud_override = config.EMERGENCY_CLOUD_OVERRIDE
	cloud_status = "\033[91m[FORZADO NUBE]\033[0m" if cloud_override else "\033[92m[LOCAL OFF-LINE]\033[0m"
	print(f"  [1] EMERGENCY_CLOUD_OVERRIDE : {cloud_status}")

	# CONTEXT_HYDRATION_DEPTH
	hydration = config.CONTEXT_HYDRATION_DEPTH
	hyd_status = f"\033[93m{hydration}\033[0m" if hydration == "LOW" else f"\033[92m{hydration}\033[0m"
	print(f"  [2] CONTEXT_HYDRATION_DEPTH   : {hyd_status}")

	# INTERCEPTOR_ENABLED
	interceptor = config.INTERCEPTOR_ENABLED
	int_status = "\033[92m[ACTIVO]\033[0m" if interceptor else "\033[91m[DESACTIVADO]\033[0m"
	print(f"  [3] INTERCEPTOR_ENABLED      : {int_status}")

	# COGNITIVE_ROUTER_ENABLED
	router = config.COGNITIVE_ROUTER_ENABLED
	r_status = "\033[92m[ACTIVO]\033[0m" if router else "\033[91m[DESACTIVADO]\033[0m"
	print(f"  [4] COGNITIVE_ROUTER_ENABLED : {r_status}")

	print("\n\033[96m[ SERVICIOS DE INFERENCIA ]\033[0m")
	# redpill-llm.service
	svc_active = is_service_active("redpill-llm.service")
	svc_status = "\033[92m[ACTIVO / RUNNING]\033[0m" if svc_active else "\033[91m[INACTIVO / STOPPED]\033[0m"
	print(f"  Servicio Hypervisor Local (systemd): {svc_status}")
	print("  [5] Iniciar Servicio  |  [6] Detener Servicio  |  [7] Reiniciar Servicio")

	print("\n\033[96m[ ACCIONES DE PURGA Y CONTROL ]\033[0m")
	print("  [8] Limpiar Caché de Persona (bunker_persona_cache.json)")
	print("  [9] Forzar Recarga Física de Configuración")

	print("\nPresione [Q] para salir. Ingrese opción: ", end="")
	sys.stdout.flush()


def main():
	action_msg = ""
	while True:
		try:
			# Use sentinel telemetry report structures
			stats = sentinel.get_stats()
		except Exception:
			stats = {"cpu": {"usage_percent": 0.0, "temp": None}, "memory": {"percent": 0.0, "available_gb": 0.0}, "gpu": []}

		# Reload configuration (checks env mtime dynamically)
		config = cfg.get_config()

		print_interface(stats, config)
		if action_msg:
			print(f"\n\033[93m>>> {action_msg}\033[0m")
			action_msg = ""

		key = get_key_nonblocking(timeout=2.0)
		if key is None:
			continue

		key = key.upper()
		if key == "Q":
			break
		elif key == "1":
			new_val = not config.EMERGENCY_CLOUD_OVERRIDE
			update_env({"EMERGENCY_CLOUD_OVERRIDE": str(new_val)})
			cfg.get_config.cache_clear()
			action_msg = f"EMERGENCY_CLOUD_OVERRIDE cambiado a {new_val}"
		elif key == "2":
			new_val = "LOW" if config.CONTEXT_HYDRATION_DEPTH == "HIGH" else "HIGH"
			update_env({"CONTEXT_HYDRATION_DEPTH": new_val})
			cfg.get_config.cache_clear()
			action_msg = f"CONTEXT_HYDRATION_DEPTH cambiado a {new_val}"
		elif key == "3":
			new_val = not config.INTERCEPTOR_ENABLED
			update_env({"INTERCEPTOR_ENABLED": str(new_val)})
			cfg.get_config.cache_clear()
			action_msg = f"INTERCEPTOR_ENABLED cambiado a {new_val}"
		elif key == "4":
			new_val = not config.COGNITIVE_ROUTER_ENABLED
			update_env({"COGNITIVE_ROUTER_ENABLED": str(new_val)})
			cfg.get_config.cache_clear()
			action_msg = f"COGNITIVE_ROUTER_ENABLED cambiado a {new_val}"
		elif key == "5":
			run_service_command("start", "redpill-llm.service")
			action_msg = "Lanzado inicio de redpill-llm.service"
		elif key == "6":
			run_service_command("stop", "redpill-llm.service")
			action_msg = "Lanzada detención de redpill-llm.service"
		elif key == "7":
			run_service_command("restart", "redpill-llm.service")
			action_msg = "Lanzado reinicio de redpill-llm.service"
		elif key == "8":
			purged = purge_persona_cache()
			action_msg = "Caché de persona purgada exitosamente" if purged else "No se pudo purgar la caché o no existía"
		elif key == "9":
			env_path = os.path.join(get_config_dir(), ".env")
			if os.path.exists(env_path):
				try:
					os.utime(env_path, None)
					cfg.get_config.cache_clear()
					action_msg = "Configuración física recargada mediante utime/mtime"
				except Exception as e:
					action_msg = f"Error al actualizar mtime de .env: {e}"
			else:
				action_msg = "No se encontró el archivo .env para recargar"


if __name__ == "__main__":
	try:
		main()
	except KeyboardInterrupt:
		sys.stdout.write("\nMenu cerrado.\n")
		sys.stdout.flush()
