import json
import platform
import shutil
import subprocess


def get_cpu():
	try:
		if platform.system() == "Windows":
			return subprocess.check_output(["wmic", "cpu", "get", "name"]).decode().split("\n")[1].strip()
		elif platform.system() == "Darwin":
			return subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"]).decode().strip()
		else:
			# Linux
			output = subprocess.check_output(["lscpu"]).decode()
			for line in output.split("\n"):
				if "Model name" in line:
					return line.split(":")[1].strip()
	except Exception:
		return platform.processor() or "Unknown"


def get_ram():
	try:
		if platform.system() == "Windows":
			ram = subprocess.check_output(["wmic", "computersystem", "get", "totalphysicalmemory"]).decode().split("\n")[1].strip()
			return f"{round(int(ram) / (1024**3))} GB"
		elif platform.system() == "Darwin":
			ram = subprocess.check_output(["sysctl", "-n", "hw.memsize"]).decode().strip()
			return f"{round(int(ram) / (1024**3))} GB"
		else:
			# Linux
			with open("/proc/meminfo", "r") as f:
				for line in f:
					if "MemTotal" in line:
						ram_kb = int(line.split()[1])
						return f"{round(ram_kb / (1024**2))} GB"
	except Exception:
		return "Unknown"


def get_vram():
	if shutil.which("nvidia-smi"):
		try:
			cmd = ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"]
			output = subprocess.check_output(cmd).decode().strip().split(", ")
			return f"{output[0]} ({output[1]} MB)"
		except Exception:
			pass
	return "None Detected"


def get_encryption():
	try:
		if platform.system() == "Windows":
			# Check BitLocker via powershell
			cmd = ["powershell", "-Command", "Get-BitLockerVolume -MountPoint $env:SystemDrive | Select-Object -ExpandProperty ProtectionStatus"]
			status = subprocess.check_output(cmd).decode().strip()
			return "ACTIVE (BitLocker)" if "On" in status else "OFF"
		elif platform.system() == "Darwin":
			cmd = ["fdesetup", "status"]
			status = subprocess.check_output(cmd).decode().strip()
			return "ACTIVE (FileVault)" if "is On" in status else "OFF"
		else:
			# Linux (check for crypt in lsblk, then /dev/mapper fallback)
			try:
				lsblk_out = subprocess.check_output(["lsblk", "-no", "TYPE"]).decode()
				if "crypt" in lsblk_out.lower():
					return "ACTIVE (LUKS/Crypt)"
			except Exception:
				pass

			# Fallback for Silverblue / OSTree (check /dev/mapper)
			try:
				import os

				if os.path.exists("/dev/mapper"):
					mapper_list = os.listdir("/dev/mapper")
					if any(m.startswith("luks-") for m in mapper_list):
						return "ACTIVE (LUKS Fallback)"
			except Exception:
				pass

			return "OFF (SEC-001 Warning)"
	except Exception:
		return "Unknown (Requires Admin/Tools)"


def main():
	report = {
		"os": platform.system(),
		"cpu": get_cpu(),
		"ram": get_ram(),
		"vram": get_vram(),
		"encryption": get_encryption(),
		"engine": "Podman" if shutil.which("podman") else ("Docker" if shutil.which("docker") else "None"),
	}
	print(json.dumps(report, indent=2))


if __name__ == "__main__":
	main()
