// manifest-compile.mjs — compilador puro del burst manifest de Forge a stages
// del dag_job (PLAN_IMPL_FORGE_DAG_LOOP.md, Tarea 1.1; ampliado en 2.4).
//
// Convierte el burst manifest (fases → pasos con role/prompt) en las `stages`
// de un manifest dag_job:
//   - cada fase → etapa `compound` con `id = phase.id`
//   - cada paso → sub-etapa `type: "agent"`, `minion: "agent"`,
//     `id = step.role`, `prompt = step.prompt`
//   - EXCEPCIÓN (2.4): un paso con `panel: true` → `{type: "dag",
//     recipe: "forge-panel"}` — el panel adversarial se pide EXPLÍCITAMENTE
//     (decisión del Operador 2026-08-14) y viaja por referencia.
//   - orden secuencial DENTRO de la fase: cada paso depende del anterior
//   - orden secuencial ENTRE fases: cada compound depende de la fase anterior
//   - `step.model` → `stage.model`; `step.on_fail` → `stage.on_fail`;
//     `phase.on_fail` → compound
//   - ids únicos por RUTA: roles repetidos en la MISMA fase se sufijan
//     `-2`, `-3`… por orden de aparición
//   - fases vacías se OMITEN; la siguiente fase depende de la última NO omitida
//
// Función PURA: sin CLI, sin lectura de ficheros, sin process.exit.
// El nombre del subagente opencode (`step.agent`) se ignora a propósito: el
// camino job-manager no lo usa (anotado, no implementado).

export function compileStages(phases) {
	if (!Array.isArray(phases)) return [];

	const stages = [];
	let prevPhaseId = null;

	for (const phase of phases) {
		const steps = Array.isArray(phase.steps) ? phase.steps : [];
		if (steps.length === 0) continue; // fase vacía: se omite por completo

		const compound = { id: phase.id, type: 'compound', sub_etapas: [] };
		if (phase.on_fail) compound.on_fail = phase.on_fail;
		if (prevPhaseId !== null) compound.depends_on = [prevPhaseId];

		const seen = new Map(); // role → veces visto en ESTA fase
		let prevStepId = null;

		for (const step of steps) {
			const baseId = step.role;
			const count = (seen.get(baseId) || 0) + 1;
			seen.set(baseId, count);
			const id = count === 1 ? baseId : `${baseId}-${count}`;

			// 2.4: panel adversarial por REFERENCIA (decisión del Operador 2026-08-14).
			if (step.panel === true) {
				const ref = { id, type: 'dag', recipe: 'forge-panel' };
				if (step.on_fail) ref.on_fail = step.on_fail;
				if (prevStepId !== null) ref.depends_on = [prevStepId];
				compound.sub_etapas.push(ref);
				prevStepId = id;
				continue;
			}

			const stage = { id, type: 'agent', minion: 'agent', prompt: step.prompt };
			if (step.model) stage.model = step.model;
			if (step.on_fail) stage.on_fail = step.on_fail;
			if (prevStepId !== null) stage.depends_on = [prevStepId];

			compound.sub_etapas.push(stage);
			prevStepId = id;
		}

		stages.push(compound);
		prevPhaseId = phase.id;
	}

	return stages;
}
