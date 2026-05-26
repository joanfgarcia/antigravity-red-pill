import os
import sys

# Añadir directorios al path para importaciones correctas
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import microscope
import torch

from red_pill.inference.bitnet.modeling_bitnet import BitNet4LayerModel
from red_pill.inference.bitnet.translator import SovereignTranslator

# Códigos ANSI para colores
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_CYAN = "\033[36m"
C_GREEN = "\033[32m"
C_YELLOW = "\033[33m"
C_RED = "\033[31m"
C_MAGENTA = "\033[35m"


def clear_screen():
	os.system("cls" if os.name == "nt" else "clear")


def find_specimens():
	"""Busca todos los archivos .pt de especímenes en el directorio de storage y archive."""
	base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
	storage_dir = os.path.join(base_dir, "storage", "curriculum")
	archive_dir = os.path.join(storage_dir, "archive")

	specimens = []

	# Buscar en storage/curriculum/
	if os.path.exists(storage_dir):
		for f in os.listdir(storage_dir):
			if f.endswith(".pt") or f.endswith(".bin"):
				specimens.append(os.path.join(storage_dir, f))

	# Buscar en storage/curriculum/archive/
	if os.path.exists(archive_dir):
		for f in os.listdir(archive_dir):
			if f.endswith(".pt") or f.endswith(".bin"):
				specimens.append(os.path.join(archive_dir, f))

	# Ordenar alfabéticamente
	specimens.sort()
	return specimens


def select_specimen(specimens):
	"""Muestra el menú de selección de espécimen."""
	while True:
		clear_screen()
		print(f"{C_BOLD}{C_CYAN}================================================================================")
		print("🔬          CENTRO DE REGISTRO Y SELECCIÓN DE ESPECÍMENES DEL BÚNKER            ")
		print(f"================================================================================{C_RESET}")
		print(f"{C_BOLD}Selecciona el espécimen de silicio sobre el que deseas enfocar el microscopio:{C_RESET}\n")

		print(f"  [{C_GREEN}0{C_RESET}] Sujeto Virgen de Control (Inicialización Aleatoria)")

		for idx, path in enumerate(specimens, 1):
			name = os.path.basename(path)
			folder = "Archivo Frío" if "archive" in path else "Arena Activa"
			size_kb = os.path.getsize(path) / 1024 if os.path.exists(path) else 0
			print(f"  [{C_GREEN}{idx}{C_RESET}] {C_BOLD}{name}{C_RESET} ({folder}) | Tamaño: {size_kb:.1f} KB | Ruta: {os.path.relpath(path)}")

		print(f"\n  [{C_RED}Q{C_RESET}] Salir del laboratorio")

		choice = input(f"\n{C_YELLOW}Introduce número o letra de tu elección: {C_RESET}").strip()

		if choice.upper() == "Q":
			print(f"\n{C_RED}Saliendo del laboratorio. Guardando bitácora...{C_RESET}")
			sys.exit(0)

		try:
			idx_choice = int(choice)
			if idx_choice == 0:
				return "random", "Sujeto Virgen de Control"
			elif 1 <= idx_choice <= len(specimens):
				path = specimens[idx_choice - 1]
				return path, os.path.basename(path)
		except ValueError:
			pass

		input(f"\n{C_RED}Selección inválida. Presiona Enter para volver a intentar...{C_RESET}")


def run_menu(specimen_path, specimen_name, model, translator):
	"""Muestra el menú de lentes de diagnóstico para el modelo cargado."""
	while True:
		clear_screen()
		print(f"{C_BOLD}{C_CYAN}================================================================================")
		print(f"🔬            MICROSCOPIO COGNITIVO - ENFOQUE: {C_YELLOW}{specimen_name.upper()}{C_CYAN}             ")
		print(f"================================================================================{C_RESET}")
		print(f"{C_BOLD}Selecciona la lente o el test clínico a realizar:{C_RESET}\n")

		print(f"  [{C_GREEN}1{C_RESET}] Lente 1: Estructura Sináptica Ternaria (Conteo de pesos)")
		print(f"  [{C_GREEN}2{C_RESET}] Lente 2: Dinámica Homeostática de Silicio (Simulación de estrés)")
		print(f"  [{C_GREEN}3{C_RESET}] Lente 3: Sonda Lingüística de Capa 1 (Test de señalización y empatía)")
		print(f"  [{C_GREEN}4{C_RESET}] Lente 4: Espectro SVD (Valores singulares de atención)")
		print(f"  [{C_GREEN}5{C_RESET}] {C_BOLD}Ejecutar Diagnóstico Completo{C_RESET} (Todas las lentes secuenciales)")
		print(f"  [{C_GREEN}6{C_RESET}] {C_MAGENTA}Cambiar de Espécimen / Volver al listado{C_RESET}")
		print(f"  [{C_RED}Q{C_RESET}] Salir del laboratorio")

		choice = input(f"\n{C_YELLOW}Selecciona una opción: {C_RESET}").strip()

		if choice == "6":
			return
		elif choice.upper() == "Q":
			print(f"\n{C_RED}Saliendo del laboratorio. Cerrando microscopio...{C_RESET}")
			sys.exit(0)

		clear_screen()

		if choice == "1":
			microscope.inspect_synapses(model)
		elif choice == "2":
			microscope.inspect_homeostasis(model)
		elif choice == "3":
			microscope.inspect_linguistics(model, translator)
		elif choice == "4":
			microscope.inspect_svd(model)
		elif choice == "5":
			print(f"Ejecutando suite completa para: {C_BOLD}{specimen_name}{C_RESET}")
			microscope.inspect_synapses(model)
			microscope.inspect_homeostasis(model)
			microscope.inspect_linguistics(model, translator)
			microscope.inspect_svd(model)
		else:
			print(f"{C_RED}Opción inválida.{C_RESET}")

		input(f"\n{C_YELLOW}Presiona Enter para volver al menú de lentes... {C_RESET}")


def main():
	translator = SovereignTranslator()
	vocab_embeddings = translator.get_concept_embeddings()

	while True:
		specimens = find_specimens()
		path, name = select_specimen(specimens)

		# Cargar el modelo
		clear_screen()
		print(f"{C_CYAN}Cargando espécimen: {C_BOLD}{name}...{C_RESET}")

		model = BitNet4LayerModel(vocab_embeddings=vocab_embeddings, hidden_dim=256, num_layers=4)
		if path != "random" and os.path.exists(path):
			try:
				model.load_state_dict(torch.load(path, map_location="cpu"))
			except Exception as e:
				print(f"{C_RED}Error al cargar pesos del espécimen: {e}. Usando inicialización de control.{C_RESET}")
				input("\nPresiona Enter para continuar...")

		run_menu(path, name, model, translator)


if __name__ == "__main__":
	try:
		main()
	except KeyboardInterrupt:
		print(f"\n\n{C_RED}Microscopio interrumpido bruscamente. Apagando luces del laboratorio...{C_RESET}")
		sys.exit(0)
