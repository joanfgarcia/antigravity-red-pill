#!/usr/bin/env node
// validate-report.mjs — Forge — Role contract gate.
//
// Runtime JSON-Schema validator for role reports. Every role report
// emitted to .cell/reports/ is checked against its JSON Schema BEFORE the
// orchestrator trusts it. Advisory results survive only if the contract holds;
// the deterministic gate (gate-check.mjs) recomputes the official verdict.
//
// Zero external dependencies. Supports the JSON-Schema subset used by the
// Forge role schemas in references/schemas/:
//   type, const, enum, required, properties, additionalProperties,
//   items (schema or primitive), minItems, minLength, maxLength, pattern,
//   minimum, maximum, allOf, if/then, $defs + $ref (#/$defs/<name>).
// Unknown keywords are ignored (draft-2020-12 semantics).
//
// Usage:
//   node validate-report.mjs <schema.json> <report.json>
//   node validate-report.mjs <report.json> <schema.json>   # order auto-detected
//   node validate-report.mjs <schema.json>  -              # report from stdin
// Output: JSON { valid: boolean, errors: string[] }    exit 0 valid, 1 invalid.

import { readFileSync } from 'node:fs';

const [_node, _script, arg1, arg2] = process.argv;

function looksLikeSchema(path) {
  try {
    const data = JSON.parse(readFileSync(path, 'utf8'));
    return (
      data && typeof data === 'object' &&
      (data.$schema || data.required || data.properties || data.$defs || data.type)
    );
  } catch {
    return false;
  }
}

// Order-agnostic: (schema, report) is canonical; (report, schema) is accepted.
let schemaPath = arg1;
let reportPath = arg2;
if (arg2 && !looksLikeSchema(arg1) && looksLikeSchema(arg2)) {
  [schemaPath, reportPath] = [arg2, arg1];
}

function readJson(path, label) {
  if (path === '-') throw new Error(`${label}: '-' is only valid when reading the report`);
  const raw = readFileSync(path, 'utf8');
  return JSON.parse(raw);
}

let schema;
let instance;
try {
  schema = readJson(schemaPath ?? '', 'schema');
} catch (e) {
  fail(`Cannot read schema ${schemaPath}: ${e.message}`);
}
try {
  instance = reportPath && reportPath !== '-'
    ? readJson(reportPath, 'report')
    : JSON.parse(readFileSync(0, 'utf8'));
} catch (e) {
  fail(`Cannot read report ${reportPath}: ${e.message}`);
}

function fail(msg) {
  console.log(JSON.stringify({ valid: false, errors: [msg] }, null, 2));
  process.exit(1);
}

// ── Validation core ──────────────────────────────────────────────────────────
const TRIVIAL_PATTERN = null; // gate-check.mjs owns trivial-evidence checks.

function deepEqual(a, b) {
  if (a === b) return true;
  if (typeof a !== 'object' || typeof b !== 'object' || a === null || b === null) return false;
  const aKeys = Object.keys(a);
  const bKeys = Object.keys(b);
  if (aKeys.length !== bKeys.length) return false;
  return aKeys.every((k) => deepEqual(a[k], b[k]));
}

function matchesType(value, type) {
  switch (type) {
    case 'object': return typeof value === 'object' && value !== null && !Array.isArray(value);
    case 'array': return Array.isArray(value);
    case 'string': return typeof value === 'string';
    case 'integer': return typeof value === 'number' && Number.isInteger(value);
    case 'number': return typeof value === 'number';
    case 'boolean': return typeof value === 'boolean';
    case 'null': return value === null;
    default: return true; // unknown type: don't block
  }
}

function validate(sch, data, errors, path, root) {
  if (sch == null) return;

  if (sch.$ref) {
    const ref = sch.$ref; // supports "#/$defs/<name>"
    const m = /^#\/\$defs\/([A-Za-z0-9_]+)$/.exec(ref);
    if (!m) { errors.push(`[${path}] unsupported $ref "${ref}"`); return; }
    const def = (root.$defs || {})[m[1]];
    if (!def) { errors.push(`[${path}] missing $defs entry "${m[1]}"`); return; }
    validate(def, data, errors, path, root);
    if (sch.properties || sch.required || sch.const || sch.enum) validateRest(sch, data, errors, path, root);
    return;
  }

  validateRest(sch, data, errors, path, root);
}

function validateRest(sch, data, errors, path, root) {
  if (sch.type !== undefined) {
    const types = Array.isArray(sch.type) ? sch.type : [sch.type];
    if (!types.some((t) => matchesType(data, t))) {
      errors.push(`[${path}] expected type ${types.join('|')}, got ${typeof data === 'object' && data !== null && !Array.isArray(data) ? 'object' : Array.isArray(data) ? 'array' : typeof data} (${JSON.stringify(data).slice(0, 60)})`);
      return; // type failure: skip property-level checks to reduce noise
    }
  }
  if (sch.const !== undefined && !deepEqual(data, sch.const)) {
    errors.push(`[${path}] const failed: expected ${JSON.stringify(sch.const)}, got ${JSON.stringify(data).slice(0, 80)}`);
  }
  if (sch.enum !== undefined) {
    const ok = Array.isArray(sch.enum) && sch.enum.some((v) => deepEqual(data, v));
    if (!ok) errors.push(`[${path}] enum failed: value ${JSON.stringify(data).slice(0, 60)} not in [${sch.enum.map((e) => JSON.stringify(e)).join(', ')}]`);
  }

  if (typeof data === 'string') {
    if (sch.minLength !== undefined && data.length < sch.minLength) errors.push(`[${path}] minLength ${sch.minLength} (got ${data.length})`);
    if (sch.maxLength !== undefined && data.length > sch.maxLength) errors.push(`[${path}] maxLength ${sch.maxLength} (got ${data.length})`);
    if (sch.pattern !== undefined) {
      try { if (!new RegExp(sch.pattern).test(data)) errors.push(`[${path}] pattern ${sch.pattern} not matched by "${data.slice(0, 60)}"`); }
      catch { errors.push(`[${path}] invalid pattern regex ${sch.pattern}`); }
    }
  }

  if (typeof data === 'number' && sch.maximum !== undefined && data > sch.maximum) {
    errors.push(`[${path}] maximum ${sch.maximum} (got ${data})`);
  }
  if (typeof data === 'number' && sch.minimum !== undefined && data < sch.minimum) {
    errors.push(`[${path}] minimum ${sch.minimum} (got ${data})`);
  }

  if (Array.isArray(data)) {
    if (sch.minItems !== undefined && data.length < sch.minItems) errors.push(`[${path}] minItems ${sch.minItems} (got ${data.length})`);
    const itemsSch = sch.items;
    if (itemsSch) {
      data.forEach((item, i) => {
        if (Array.isArray(itemsSch)) { // tuple form: validate against per-index schema
          if (itemsSch[i]) validate(itemsSch[i], item, errors, `${path}[${i}]`, root);
        } else {
          validate(itemsSch, item, errors, `${path}[${i}]`, root);
        }
      });
    }
  }

  if (typeof data === 'object' && data !== null && !Array.isArray(data)) {
    const props = sch.properties || {};
    for (const [name, sub] of Object.entries(props)) {
      if (Object.prototype.hasOwnProperty.call(data, name)) {
        validate(sub, data[name], errors, `${path}.${name}`, root);
      }
    }
    for (const req of sch.required || []) {
      if (!Object.prototype.hasOwnProperty.call(data, req)) {
        errors.push(`[${path}] missing required property "${req}"`);
      }
    }
    const extra = Object.keys(data).filter((k) => !(k in props));
    if (extra.length) {
      if (sch.additionalProperties === false) {
        errors.push(`[${path}] unexpected properties: ${extra.join(', ')}`);
      } else if (sch.additionalProperties && typeof sch.additionalProperties === 'object') {
        for (const k of extra) validate(sch.additionalProperties, data[k], errors, `${path}.${k}`, root);
      }
    }
  }

  if (sch.allOf !== undefined) {
    sch.allOf.forEach((sub, i) => {
      const pre = errors.length;
      validate(sub, data, errors, `${path} (allOf[${i}])`, root);
      // Bail out of allOf if already invalid: avoid cascading if/then noise per schema
      if (errors.length > pre && !sub.if) return;
    });
  } else if (sch.if !== undefined) {
    // if/then: evaluate the guard in isolation, then apply then on success
    const guardErrors = [];
    validate(sch.if, data, guardErrors, `${path} (if)`, root);
    if (guardErrors.length === 0 && sch.then !== undefined) {
      // Validate then against the guard context path (already namespaced by (if))
      const thenErrors = [];
      validate(sch.then, data, thenErrors, path, root);
      errors.push(...thenErrors.map((e) => e));
    }
    // Guard remains advisory when it trivially matches nothing (partial properties)
    if (sch.else !== undefined && guardErrors.length > 0) {
      validate(sch.else, data, errors, `${path} (else)`, root);
    }
  }
}

const errors = [];
validate(schema, instance, errors, '$', schema);

const result = { valid: errors.length === 0, errors };
console.log(JSON.stringify(result, null, 2));
process.exit(result.valid ? 0 : 1);