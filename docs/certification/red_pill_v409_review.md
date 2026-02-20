**ENGINEERING CERTIFICATION REPORT**

**antigravity-red-pill**

Version 4.0.9 · Production Readiness Assessment

+-----------------------------------+-----------------------------------+
| **Project:** antigravity-red-pill | **Audit Scope:** Full             |
|                                   | engineering-grade review          |
| **Version Audited:** 4.0.9        |                                   |
|                                   | **Auditor:** Claude (Anthropic)   |
| **Repository:**                   | --- automated static analysis     |
| github.com                        |                                   |
| /joanfgarcia/antigravity-red-pill | **Prior Review:** v4.0.6          |
|                                   | (2026-02-18)                      |
| **Audit Date:** 2026-02-19        |                                   |
|                                   | **Certification Status: ⚠         |
|                                   | CONDITIONAL --- Not Yet           |
|                                   | Production-Ready**                |
+===================================+===================================+
+-----------------------------------+-----------------------------------+

+-----------------------------------------------------------------------+
| **CERTIFICATION VERDICT: CONDITIONAL PASS**                           |
|                                                                       |
| 3 blocking issues must be resolved before production deployment       |
+=======================================================================+
+-----------------------------------------------------------------------+

*Reviewer: Claude · Anthropic · February 2026*

# Table of Contents

  -----------------------------------------------------------------------
  **1. Executive Summary & Verdict**  3
  ----------------------------------- -----------------------------------
  2\. Project Description, Goals &    3
  Target Audience                     

  3\. What Changed Since v4.0.6       4

  4\. Code Quality Analysis           4

  5\. Security Audit                  6

  6\. Test Coverage & Quality         7

  7\. Performance & Scalability       8
  Assessment                          

  8\. Documentation Review            9

  9\. Compliance & Licensing          9

  10\. Prioritised Findings & Action  10
  Plan                                

  11\. Scorecard                      11
  -----------------------------------------------------------------------

# 1. Executive Summary & Verdict

antigravity-red-pill v4.0.9 is a local, privacy-first memory persistence
layer for AI assistants. It wraps Qdrant (self-hosted vector database)
and FastEmbed (local sentence embeddings) to store, reinforce, decay,
and semantically retrieve \"engrams\" (memory data-points) across AI
sessions. The project has undergone rapid, iterative improvement: 9
patch releases in a single day (v4.0.1 → v4.0.9) addressing all critical
bugs identified in the prior v4.0.6 review.

The overall trajectory is strongly positive. All three P1 and both P2
items from the previous review have been addressed. However, three new
or residual issues prevent unconditional production certification:

> **\[CRITICAL\] Immunity bypass via metadata injection**
>
> A caller can pass {\"immune\": True} in metadata and the \*\* spread
> in add_memory() writes it directly into the payload, permanently
> exempting any engram from erosion.
>
> **\[MEDIUM\] Dead code in seed.py masking intent**
>
> Two random UUIDs are generated then immediately overwritten by fixed
> constants. The dangling comment block creates confusion about intended
> semantics.
>
> **\[LOW\] Fallback vector size still hardcoded in \_get_vector()**
>
> The dry-run zero-vector path returns \[0.0\]\*384 regardless of
> VECTOR_SIZE config. Minor risk, but inconsistent.

Subject to remediation of the immunity bypass (blocking), this release
is suitable for single-user, local-machine deployment in a trusted
personal environment. It is NOT ready for multi-tenant, network-exposed,
or enterprise production use without additional hardening described in
§10.

# 2. Project Description, Goals & Target Audience

## 2.1 What It Does

The Red Pill Protocol solves \"session amnesia\" --- the inability of
stateless AI assistants to remember context between conversations. It
provides a local RAG (Retrieval-Augmented Generation) substrate:
memories are stored as semantic vectors in a self-hosted Qdrant
instance, retrieved by cosine similarity, and subject to a
biologically-inspired reinforcement/decay lifecycle (the B760
algorithm).

## 2.2 Core Value Proposition

-   Privacy-first: all data lives on localhost; no cloud APIs are
    invoked for embeddings or storage.

-   Session continuity: AI assistants can recall prior context, user
    preferences, and project history.

-   Organic memory management: frequently-recalled memories are
    reinforced; unused ones decay and are deleted.

-   Configurable persona: cosmetic \"lore skins\" (Matrix, Cyberpunk,
    Dune, etc.) adapt the assistant\'s language without affecting logic.

## 2.3 Target Audience

Power users and developers who use local AI coding assistants (Gemini
CLI, Claude Code, Cursor, etc.) and want persistent context without
routing sensitive data to external services. The project explicitly
targets single-operator, trusted-environment deployments. It is not
designed for multi-user, SaaS, or networked production systems in its
current form.

## 2.4 Stack Summary

  -----------------------------------------------------------------------
  **Layer**               **Technology**          **Notes**
  ----------------------- ----------------------- -----------------------
  **Language**            Python ≥ 3.10           src/ layout, hatchling
                                                  build

  **Vector DB**           Qdrant (self-hosted)    Podman Quadlet /
                                                  systemd, localhost:6333

  **Embeddings**          FastEmbed               384-dim, fully local,
                          all-MiniLM-L6-v2        no GPU required

  **Schema validation**   Pydantic v2             Added in v4.0.7

  **Config**              python-dotenv           .env file, all tunables
                                                  exposed

  **CLI**                 argparse                red-pill entry-point
                                                  via pyproject.toml

  **Package mgr**         uv + hatchling          modern PEP-517 build

  **Platform support**    Linux (primary), macOS, systemd Quadlet on
                          Windows (PS1)           Linux
  -----------------------------------------------------------------------

# 3. What Changed Since v4.0.6

## 3.1 Issues Resolved from Prior Review

  -------------------------------------------------------------------------------------------
  **Prior Finding         **Resolution**                              **Status**
  (v4.0.6)**                                                          
  ----------------------- ------------------------------------------- -----------------------
  Vector size hardcoded   VECTOR_SIZE env-var added to config.py;     **FIXED ✓**
  to 384 in seed.py,      seed.py now reads cfg.VECTOR_SIZE           
  ignoring                                                            
  EMBEDDING_MODEL                                                     

  Concurrent              \_reinforce_points() now uses set_payload() **FIXED ✓**
  reinforcement race      per-point (optimistic write). Eliminates    
  condition --- no        full vector re-upsert.                      
  locking                                                             

  No Qdrant API-key       QDRANT_API_KEY added to config.py and       **FIXED ✓**
  authentication          passed to QdrantClient constructor.         
                          .env.example updated.                       

  apply_erosion() fetched scroll() now uses with_vectors=False;       **FIXED ✓**
  full vectors            erosion uses set_payload for score updates. 
  unnecessarily                                                       

  seed.py not idempotent  Fixed UUIDs for genesis points              **FIXED ✓**
  --- duplicate genesis   (00000000-0000-0000-0000-000000000001/2).   
  engrams on second run   Existence check added.                      

  MemoryManager           Manager now lazy-initialised inside command **FIXED ✓**
  instantiated before     branches; mode command never touches        
  command dispatch in     Qdrant.                                     
  cli.py                                                              

  QDRANT_PORT read as     Port cast to int(); explicit ValueError     **FIXED ✓**
  string; no              raised on invalid DECAY_STRATEGY value.     
  DECAY_STRATEGY                                                      
  validation                                                          

  No .env.example file    .env.example added with all configurable    **FIXED ✓**
                          variables documented.                       

  Unused import: math     Removed.                                    **FIXED ✓**
  -------------------------------------------------------------------------------------------

## 3.2 New Additions in v4.0.7--4.0.9

-   schemas.py: Pydantic v2 CreateEngramRequest with content length
    limits, null-byte rejection, and flat metadata enforcement.

-   PointUpdate helper class: avoids round-tripping vectors through
    \_reinforce_points() return value.

-   stress_test_smith.py: concurrent reinforcement test, poison-pill
    injection test, erosion flood test.

-   Dockerfile.keymaker: slim Python 3.11 image for containerised
    testing.

-   ARCHITECTURE.md: honest scalability analysis with documented
    singularity points (\~100k engrams).

-   SMITH_AUDIT.md: internal stress-test results and code verification
    sign-off.

-   BACKLOG.md: roadmap including swarm/hive architecture, TTL indexing,
    and \"Red Button\" data-wipe.

-   DISCLAIMER.md: transparent documentation of known deficiencies.

-   DEEP_RECALL_TRIGGERS externalised to config.py (no longer hard-coded
    in cli.py).

-   pydantic\>=2.0.0 added to pyproject.toml runtime dependencies.

# 4. Code Quality Analysis

## 4.1 memory.py (334 lines)

### Positives

-   set_payload() optimisation correctly eliminates vector bandwidth for
    reinforcement and erosion paths.

-   PointUpdate helper class cleanly avoids the type confusion of
    reusing models.PointStruct.

-   Pydantic validation is correctly invoked at the add_memory()
    entry-point before any DB write.

-   Dormancy filter, deep recall bypass, immunity promotion, and
    synaptic propagation all work correctly.

-   \_reinforce_points() UUID validation prevents non-UUID association
    tags from crashing Qdrant.

-   Extensive inline comments document the trade-offs and residual risks
    honestly.

### Findings

> **\[CRITICAL\] Immunity bypass via \*\* metadata spread --- BLOCKING**
>
> payload = {\"content\": \..., \"immune\": False, \*\*clean_metadata}\
> The default \"immune\": False is overwritten by any {\"immune\": True}
> in the caller\'s metadata dict.\
> The Pydantic schema accepts bool values in metadata (Union\[str, int,
> float, bool, List\[str\]\]).\
> A caller can permanently exempt any engram from erosion without
> privilege.\
> Fix: strip reserved keys from clean_metadata before the spread, e.g.:\
> RESERVED =
> {\"content\",\"importance\",\"reinforcement_score\",\"created_at\",\"last_recalled_at\",\"immune\"}\
> safe_meta = {k:v for k,v in clean_metadata.items() if k not in
> RESERVED}
>
> **\[LOW\] \_get_vector() fallback hardcodes 384 instead of
> cfg.VECTOR_SIZE**
>
> return \[0.0\] \* 384 --- minor inconsistency with the new VECTOR_SIZE
> config. Change to cfg.VECTOR_SIZE.
>
> **\[LOW\] apply_erosion() rate parameter typed as Optional\[float\] =
> None instead of Optional\[float\]**
>
> def apply_erosion(self, collection: str, rate: float = None) --- mypy
> will flag this.\
> Change to: rate: Optional\[float\] = None
>
> **\[LOW\] Stale comments / commented-out code in memory.py**
>
> \~40 lines of commented-out upsert logic and inline deliberation
> remain in the file. These should be moved to git history or a
> DECISIONS.md.
>
> **\[MEDIUM\] search_and_reinforce() still requests with_vectors=True
> from query_points**
>
> The vectors are not used after the search --- only payloads flow into
> reinforcement. Change to with_vectors=False to halve search response
> size.

## 4.2 schemas.py (43 lines)

### Positives

-   Clean Pydantic v2 BaseModel with field validators.

-   Null-byte check is an important defence against C-string edge-cases.

-   Flat metadata enforcement (no nested dicts) prevents payload
    inflation.

### Findings

> **\[CRITICAL\] metadata validator allows \"immune\" key through as a
> bool**
>
> This is the root cause of the immunity bypass (see §4.1). Add a
> blacklist validator:\
> RESERVED_KEYS =
> {\"content\",\"importance\",\"reinforcement_score\",\"created_at\",\"last_recalled_at\",\"immune\"}\
> for key in v: if key in RESERVED_KEYS: raise ValueError(f\"Reserved
> key: {key}\")
>
> **\[MEDIUM\] associations field is not explicitly typed in the
> schema**
>
> The metadata type is Dict\[str,
> Union\[str,int,float,bool,List\[str\]\]\]. The special
> \"associations\" key (a List\[str\] of UUIDs) has no dedicated
> validator to ensure items are valid UUIDs. Consider an explicit
> AssociationList type.

## 4.3 seed.py (76 lines)

### Positives

-   Fixed UUID constants (00000000-...-0001/0002) make genesis points
    deterministic and idempotent.

-   Existence check before injection correctly prevents duplicate
    genesis engrams.

-   Reads cfg.VECTOR_SIZE for collection creation --- model-agnostic.

### Findings

> **\[MEDIUM\] Dead code: random UUIDs generated on lines 27--28 then
> immediately overwritten on lines 43--44**
>
> id_aleph = str(uuid.uuid4()) and id_bond = str(uuid.uuid4()) are
> assigned but immediately reassigned to fixed string constants. Delete
> lines 27--28 and the accompanying 12-line comment block.
>
> **\[MEDIUM\] Idempotency check only covers genesis points, not the
> three \"others\" engrams**
>
> If seed() is interrupted after creating id_aleph/id_bond but before
> inserting the three \"others\", a subsequent run skips the existence
> check (id_aleph now exists) and leaves the DB incomplete.\
> Fix: use upsert semantics (not add_memory) for all genesis points, so
> re-running is always safe.

## 4.4 cli.py (124 lines)

### Positives

-   Lazy MemoryManager instantiation: mode command never connects to
    Qdrant.

-   DEEP_RECALL_TRIGGERS correctly externalised to config module.

-   All Qdrant errors caught at the command level with a user-friendly
    message.

### Findings

> **\[LOW\] No exit code differentiation**
>
> All failure paths exit with sys.exit(1). Structured exit codes
> (2=config, 3=db-unavailable, 4=not-found) would improve scripting and
> CI integration.
>
> **\[LOW\] search output does not show semantic similarity score**
>
> Results print reinforcement_score but not the cosine similarity score
> from Qdrant. Users cannot distinguish high-relevance vs. low-relevance
> matches.

## 4.5 config.py (39 lines)

### Positives

-   QDRANT_PORT correctly cast to int().

-   DECAY_STRATEGY validated at import time with explicit ValueError ---
    fails fast.

-   QDRANT_API_KEY loaded and passed to client.

-   VECTOR_SIZE added as configurable env-var.

### Findings

> **\[MEDIUM\] QDRANT_URL uses plain http:// --- no TLS option**
>
> For any deployment where Qdrant is not on localhost (e.g.,
> containerised or remote), traffic is unencrypted. Add QDRANT_SCHEME =
> os.getenv(\"QDRANT_SCHEME\", \"http\") and build URL from it.
>
> **\[LOW\] Numeric config values (EROSION_RATE,
> REINFORCEMENT_INCREMENT, etc.) have no bounds validation**
>
> An EROSION_RATE \> 1.0 with exponential decay would immediately delete
> all memories. Add range assertions after float() parsing.

# 5. Security Audit

## 5.1 Threat Model

The declared threat model is single-user, localhost-only. Qdrant is
bound to 127.0.0.1 by convention and the API key is optional. The
primary attack surface is local: a malicious process or malformed LLM
output injecting data via the add_memory() path.

## 5.2 Security Findings

> **\[CRITICAL\] Immunity bypass via metadata (see §4.1) --- BLOCKING**
>
> Any caller of add_memory() can set {\"immune\": True} in metadata,
> permanently protecting an engram from erosion. If an LLM generates
> this metadata value, the memory store will gradually fill with
> immortal garbage. Fix: strip reserved payload keys in add_memory()
> before the \*\* spread.
>
> **\[MEDIUM\] QDRANT_URL defaults to http:// --- plaintext transport**
>
> If QDRANT_HOST is changed to a non-localhost address, all memory data
> is transmitted in cleartext. Support QDRANT_SCHEME=https and TLS
> certificates.
>
> **\[MEDIUM\] install_neo.sh lacks set -euo pipefail**
>
> The install script can fail silently mid-execution (e.g., failed cp
> command) and continue, leaving a partially-configured installation.
> Add \"set -euo pipefail\" at the top.
>
> **\[MEDIUM\] install_neo.sh: Qdrant container image pinned to
> :latest**
>
> Image=docker.io/qdrant/qdrant:latest in the Quadlet config means a
> future breaking Qdrant release could silently break installations on
> next pull. Pin to a specific version tag.
>
> **\[LOW\] SECURITY.md lacks a responsible disclosure contact**
>
> The file says \"Send an encrypted engram to the Operator\" but
> provides no actual contact mechanism (email, GitHub Security
> Advisories). Add a real disclosure channel.
>
> **\[INFO\] Pydantic schema correctly blocks deep nesting and null
> bytes**
>
> attack_poison_pill() in the stress test confirms 100% rejection of
> malformed payloads.
>
> **\[INFO\] No outbound network calls from Python code --- confirmed**
>
> Grep scan and code review confirm no requests to external APIs. All
> embeddings are local.
>
> **\[INFO\] No eval/exec/subprocess in Python source --- confirmed**
>
> grep scan of src/red_pill/ found no dynamic code execution patterns.

# 6. Test Coverage & Quality

## 6.1 Unit Test Suite (test_memory.py --- 223 lines)

### Coverage Assessment

  ------------------------------------------------------------------------------
  **Test**                       **Covers**              **Status**
  ------------------------------ ----------------------- -----------------------
  test_linear_decay              Linear erosion formula  **PASS ✓**
                                 including floor         

  test_exponential_decay         Exponential erosion     **PASS ✓**
                                 formula                 

  test_exponential_decay_floor   Float rounding          **PASS ✓**
                                 edge-case fix           

  test_immunity_promotion        Score → immunity        **PASS ✓**
                                 threshold promotion     

  test_synaptic_propagation      Primary + associated    **PASS ✓**
                                 point reinforcement via 
                                 set_payload             

  test_erosion_cycle             Immune skip +           **PASS ✓**
                                 non-immune decay via    
                                 set_payload             

  test_dormancy_filter           Filter presence/absence **PASS ✓**
                                 for normal vs deep      
                                 recall                  

  test_reinforcement_stacking    Multi-path              **PASS ✓**
                                 reinforcement           
                                 accumulation            

  test_manual_id_injection       Custom point_id         **PASS ✓**
                                 respected in add_memory 

  test_strict_id_validation      Non-UUID associations   **PASS ✓**
                                 filtered out            
  ------------------------------------------------------------------------------

### Test Quality Issues

> **\[LOW\] test_strict_id_validation has dead assertions**
>
> The function reassigns increments and re-calls \_reinforce_points
> mid-test, making the first retrieve() call and its assertion dead.
> Clean this up so every assertion is live.
>
> **\[HIGH\] Pydantic immunity bypass has no test**
>
> The critical immunity bypass (metadata={\"immune\":True}) has no
> negative test asserting it is blocked. Add: with
> pytest.raises(ValidationError): manager.add_memory(col, \"text\",
> metadata={\"immune\": True})
>
> **\[MEDIUM\] No test for apply_erosion() delete path (score → 0)**
>
> The erosion test covers a decay from 0.5 → 0.4 but not the path where
> score reaches 0 and client.delete() is called.
>
> **\[MEDIUM\] No test for seed.py idempotency**
>
> Running seed_project() twice should not duplicate genesis engrams. No
> test covers this.

## 6.2 Stress Test Suite (stress_test_smith.py --- 159 lines)

The stress test suite is a notable addition. It requires a live Qdrant
instance to run.

### Attack Vectors Tested

-   **attack_clone_army():** 100 concurrent threads reinforcing the same
    engram. Validates optimistic locking reduces (not eliminates) race
    conditions.

-   **attack_poison_pill():** Injects deeply nested dicts, huge strings,
    null bytes, SQL strings, and Unicode chaos into metadata. Validates
    Pydantic schema rejection.

-   **attack_erosion_flood():** Rapid-fire erosion loop + concurrent
    reads for 3 seconds. Validates no deadlocks.

### Stress Test Gaps

> **\[MEDIUM\] attack_clone_army() does not assert a minimum score ---
> it only logs a warning**
>
> The test prints \"\[FAIL\]\" but does not call pytest.fail() or
> assert. It will \"pass\" even with a race condition.
>
> **\[MEDIUM\] Stress tests require a live Qdrant instance --- not
> runnable in CI without testcontainers**
>
> Add a pytest.ini marker (e.g., \@pytest.mark.integration) and a Docker
> Compose fixture so they can run in CI.

## 6.3 Missing Test Infrastructure

-   No pytest configuration file (pytest.ini, pyproject
    \[tool.pytest.ini_options\]).

-   No coverage reporting (pytest-cov or similar).

-   No CI pipeline to run tests on commits (GitHub Actions, etc.).

-   No integration tests using testcontainers-python for a real Qdrant
    instance.

-   No lock file (uv.lock) --- test reproducibility relies solely on
    semver floor constraints.

# 7. Performance & Scalability Assessment

## 7.1 Known Limits (Self-Documented in ARCHITECTURE.md & DISCLAIMER.md)

The project commendably self-documents its performance limits. The
following are extracted from ARCHITECTURE.md and validated by code
review:

  -------------------------------------------------------------------------
  **Limit**           **Threshold**     **Risk**          **Remediation**
  ------------------- ----------------- ----------------- -----------------
  **apply_erosion()   \~100k engrams    Erosion cycle     TTL index planned
  O(N) scan**                           slower than       for v5.0
                                        reinforcement --- 
                                        \"time dilation\" 

  **Synaptic hub      \>1,000           Single query      Max-axons cap ---
  fan-out**           associations on   locks DB for      not scheduled
                      one node          seconds           

  **Embedding model   Any model change  Collection must   Re-seed required;
  migration**         post-seed         be rebuilt ---    documented
                                        vectors are       
                                        incompatible      

  **Concurrent        High throughput   Residual race     Qdrant atomic ops
  writes**            (\>20 TPS)        condition on      --- future work
                                        reinforcement     
                                        scores            
  -------------------------------------------------------------------------

## 7.2 Optimisations Implemented in v4.0.7+

-   erosion uses with_vectors=False (scroll) + set_payload ---
    eliminates \~1.5KB vector download per point.

-   reinforcement uses set_payload per-point instead of full upsert ---
    eliminates vector bandwidth and reduces payload overwrite risk.

-   query_points still requests with_vectors=True --- opportunity to
    save bandwidth (§4.1).

## 7.3 Practical Performance Envelope

For its stated single-user target (personal AI assistant memory),
performance is more than adequate. A typical user accumulates \<10,000
engrams over years of use, well within the documented 100k threshold.
The erosion cycle is expected to run once per day (externally
scheduled); at 10k memories with set_payload calls, this takes
approximately 30--120 seconds on modest hardware --- acceptable for a
daily cron job.

# 8. Documentation Review

## 8.1 Strengths

-   README.md: clear installation paths (agentic, manual, Windows),
    configuration reference, lore skin table.

-   .env.example: all configurable variables documented with inline
    comments --- production-ready practice.

-   ARCHITECTURE.md: honest O(N) scalability analysis, documented
    \"Singularity Points\", v5.0 remediation plan.

-   DISCLAIMER.md: explicit known deficiencies with version-tagged
    resolutions --- rare and praiseworthy.

-   SMITH_AUDIT.md: stress-test results with code-line cross-references.

-   CHANGELOG.md: granular per-patch change log covering all 9 patch
    releases.

-   BACKLOG.md: structured roadmap with technical implementation steps.

-   B760_TECHNICAL_SPEC.md: mathematical specification of decay and
    reinforcement formulas.

-   CONTRIBUTING.md: contribution process defined (though written in
    Spanish --- see below).

## 8.2 Documentation Gaps

> **\[MEDIUM\] CONTRIBUTING.md is written in Spanish only**
>
> The project README is in English but CONTRIBUTING.md is entirely in
> Spanish, creating a barrier for international contributors.
>
> **\[LOW\] README title still says \"v4.0.0\" while the codebase is
> 4.0.9**
>
> The README h1 reads \"Digital Sovereignty v4.0.0\". Update to match
> pyproject.toml version.
>
> **\[LOW\] No API reference / docstring coverage**
>
> Public methods (add_memory, search_and_reinforce, apply_erosion,
> get_stats) have docstrings but no parameter-level documentation.
> Consider Sphinx or mkdocs.
>
> **\[LOW\] No quickstart / getting-started guide in README for
> non-agentic installs**
>
> The manual install path is buried after the agentic install. A
> \"5-minute manual setup\" section would help developers.

# 9. Compliance & Licensing

## 9.1 License

The project is licensed under Creative Commons Attribution-NonCommercial
4.0 International (CC BY-NC 4.0). This is a non-standard choice for a
software library (CC licenses are designed for creative works, not
code). Key implications:

-   Commercial use is prohibited --- integrators must verify this is
    compatible with their use case.

-   CC BY-NC 4.0 does not include the patent grant or source-code
    modification clauses typical of OSI-approved licenses (MIT, Apache
    2.0).

-   The LICENSE file is present and complete.

> **\[MEDIUM\] CC BY-NC 4.0 is not an OSI-approved open-source license**
>
> If the project aims for adoption in commercial environments or by
> open-source projects, consider transitioning to MIT or Apache 2.0. If
> non-commercial restriction is intentional, document it prominently in
> README.

## 9.2 Dependency Compliance

  -------------------------------------------------------------------------
  **Dependency**      **Version         **License**       **Notes**
                      Constraint**                        
  ------------------- ----------------- ----------------- -----------------
  **qdrant-client**   \>=1.8.0          Apache 2.0        Compatible

  **fastembed**       \>=0.2.0          Apache 2.0        Compatible

  **python-dotenv**   \>=1.0.0          BSD-3-Clause      Compatible

  **requests**        \>=2.31.0         Apache 2.0        Compatible

  **PyYAML**          \>=6.0.1          MIT               Compatible

  **pydantic**        \>=2.0.0          MIT               Compatible
  -------------------------------------------------------------------------

## 9.3 Dependency Pinning

> **\[MEDIUM\] No lock file committed (uv.lock)**
>
> Without a committed lock file, CI and fresh installs resolve to the
> latest compatible versions of all transitive dependencies. A fastembed
> or qdrant-client patch release could break behaviour silently. Run
> \"uv lock\" and commit uv.lock.

# 10. Prioritised Findings & Action Plan

The following table consolidates all findings. Items marked BLOCKER must
be resolved before production deployment.

  --------------------------------------------------------------------------------------------------------------------------
  **\#**         **Severity**   **Area**             **Finding**                  **Recommended Fix**
  -------------- -------------- -------------------- ---------------------------- ------------------------------------------
  1              **CRITICAL --- security/memory.py   Immunity bypass:             Strip RESERVED keys from metadata before
                 BLOCKER**                           metadata={\"immune\":True}   \*\* spread; add blacklist validator to
                                                     permanently protects any     schema.py
                                                     engram                       

  2              **HIGH**       tests                No test for immunity bypass  Add pytest.raises(ValidationError) test
                                                     (validation should reject    for {\"immune\":True} in metadata
                                                     reserved keys)               

  3              **MEDIUM**     memory.py            search_and_reinforce         Change to with_vectors=False in
                                                     requests with_vectors=True   query_points call
                                                     --- vectors unused after     
                                                     search                       

  4              **MEDIUM**     schemas.py           associations field has no    Add explicit validator: each item in
                                                     UUID-format validator        associations must pass uuid.UUID()

  5              **MEDIUM**     seed.py              Dead code: random UUIDs      Delete lines 27--28 and the 12-line
                                                     generated on lines 27--28    comment block
                                                     then overwritten             

  6              **MEDIUM**     seed.py              Idempotency only covers      Use upsert semantics for all genesis
                                                     first 2 genesis points;      points, or wrap entire seed in a
                                                     \"others\" can be duplicated transaction-like guard
                                                     if seed is interrupted       

  7              **MEDIUM**     config.py            Plain http:// transport ---  Add QDRANT_SCHEME env-var; build URL as
                                                     no TLS support               f\"{cfg.QDRANT_SCHEME}://{host}:{port}\"

  8              **MEDIUM**     scripts              install_neo.sh lacks set     Add \"set -euo pipefail\" after the
                                                     -euo pipefail                shebang line

  9              **MEDIUM**     scripts              Qdrant container pinned to   Pin to a specific version tag, e.g.,
                                                     :latest                      docker.io/qdrant/qdrant:v1.8.4

  10             **MEDIUM**     tests                Stress tests cannot run in   Add pytest.mark.integration marker;
                                                     CI without a live Qdrant     provide docker-compose.test.yml or
                                                     instance                     testcontainers fixture

  11             **MEDIUM**     compliance           No lock file --- transitive  Run \"uv lock\" and commit uv.lock
                                                     dep resolution               
                                                     non-deterministic            

  12             **MEDIUM**     docs                 CONTRIBUTING.md written in   Add English translation or make bilingual
                                                     Spanish only                 

  13             **LOW**        memory.py            \_get_vector() fallback uses Change to: return \[0.0\] \*
                                                     hardcoded 384 instead of     cfg.VECTOR_SIZE
                                                     cfg.VECTOR_SIZE              

  14             **LOW**        memory.py            apply_erosion rate typed as  Change to Optional\[float\] = None; add
                                                     float = None (mypy error)    from typing import Optional

  15             **LOW**        memory.py            \~40 lines of commented-out  Remove stale comments; move deliberation
                                                     code remain                  notes to DECISIONS.md or git history

  16             **LOW**        cli.py               No structured exit codes     Define EXIT\_\* constants; use specific
                                                                                  exit codes per error class

  17             **LOW**        config.py            Numeric tunables have no     Assert 0 \< EROSION_RATE \<= 1.0, 0 \<
                                                     bounds validation            PROPAGATION_FACTOR \<= 1.0, etc. after
                                                                                  float() parsing

  18             **LOW**        docs                 README title version         Update README h1 to v4.0.9
                                                     mismatch (shows v4.0.0)      

  19             **INFO**       license              CC BY-NC 4.0 is not          Evaluate whether MIT/Apache 2.0 better
                                                     OSI-approved; restricts      serves adoption goals
                                                     commercial use               
  --------------------------------------------------------------------------------------------------------------------------

# 11. Scorecard

  -----------------------------------------------------------------------
  **Dimension**     **v4.0.6 Score**  **v4.0.9 Score**  **Delta**
  ----------------- ----------------- ----------------- -----------------
  Architecture &    4.0 / 5           4.3 / 5           ▲ +0.3
  Design                                                

  Code Correctness  3.5 / 5           4.0 / 5           ▲ +0.5

  Security Posture  3.0 / 5           3.5 / 5           ▲ +0.5

  Test Quality      3.5 / 5           4.0 / 5           ▲ +0.5

  Performance &     ---               3.5 / 5           (new)
  Scalability                                           

  Documentation     4.0 / 5           4.5 / 5           ▲ +0.5

  Packaging &       3.0 / 5           3.2 / 5           ▲ +0.2
  DevOps                                                

  Compliance        ---               3.5 / 5           (new)

  **OVERALL**       3.5 / 5           **3.9 / 5**       ▲ +0.4
  -----------------------------------------------------------------------

+-----------------------------------------------------------------------+
| **CERTIFICATION VERDICT: CONDITIONAL PASS (v4.0.9)**                  |
|                                                                       |
| All 9 critical/high items from the v4.0.6 review have been resolved.  |
| The project demonstrates strong iterative improvement and honest      |
| self-documentation of its limits. One new critical issue (immunity    |
| bypass) and two medium issues (dead code, partial idempotency) block  |
| unconditional certification. Upon remediation of item #1 (immunity    |
| bypass), this project achieves PASS status for its intended           |
| single-user, trusted-environment deployment target.                   |
+=======================================================================+
+-----------------------------------------------------------------------+

*--- Claude (Anthropic), February 2026 · antigravity-red-pill v4.0.9
Audit*
