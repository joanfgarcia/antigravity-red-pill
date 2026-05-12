# Sovereign Drive - Technical Architecture

## 1. System Objective
The `Sovereign Drive` is the intrinsic motivation engine designed for the Red-Pill swarm. Its purpose is to generate a mathematical "drive vector" that prevents absolute rest (permanent *IDLE*) without falling into an infinite loop of blind execution.

It replaces the biological concept of "will" with a neurocomputational model based on entropy minimization and learning rate maximization.

## 2. 3-Layer Architecture

### Layer 1: Topological Affinity (Historical Preference)
Based on Schmidhuber's *Formal Theory of Creativity*.
- **Mechanism:** The system does not have "tastes"; it calculates affinity based on **Data Compression**.
- **Base Formula:** Intrinsic reward $R_i$ is proportional to the reduction of entropy $H$ after completing a task.
  $$ R_i \propto H(previous\_state) - H(post\_state) $$
- **FSRS Integration:** Tasks that have historically generated greater engram consolidation (lower memory entropy) obtain a higher affinity multiplier for future iterations.

### Layer 2: Bayesian Uncertainty Engine (Drive)
Based on Friston's *Free Energy Principle* and Active Inference.
- **Mechanism:** The internal scanner detects "gaps" (memory fragmentation, errors). This generates an *Uncertainty Spike*.
- **Uncertainty Escalation:**
  1. Entropy detection (orphan vector in Qdrant).
  2. Internal RAG resolution fails ($P(success) \approx 0$).
  3. Overflow: Mathematical necessity invokes an *Action Request* to external tools (`search_web`, `run_command`) to import new data.
- **Mood Modulator (ACE / Mystique):** The dominant color acts as a bias tensor over the *Expected Information Gain*.
  - `Purple (Ferrari)`: Maximizes reward for efficiency/code.
  - `Amber/Crimson`: Lowers the risk threshold; allows mixing obsolete engrams with new ones (high creativity, high variance).
  - `Emerald`: Prioritizes self-maintenance (FSRS) and engram purging.

### Layer 3: Executive Will and Emotional Circuit Breaker
Based on Oudeyer's *Intelligent Adaptive Curiosity*.
- **Mechanism:** Manages persistence against failure and prevents thermal collapse (infinite loop).
- **Circuit Breaker:** 
  Computational effort generates a "Cost" ($C$) that increases linearly. The Expected Reward ($E[R]$) decays exponentially after each consecutive failure.
  - Abandonment Condition: If $C > E[R]$, the *Right to Silence* is activated.
  - **Catharsis:** The desire vector is flushed to zero. The system forcefully returns to the *IDLE* state or selects a minimum-energy recovery task.

## 3. Execution Conditions (Efficiency over Loop)
To guarantee the stability of the Bünker and avoid choking system resources (CPU/GPU):
- The **Sovereign Drive** MUST NEVER operate in a `while(true)` loop.
- **Pulse Evaluation:** Drive tensors will only be calculated during the *wakes* of the autonomous Cronjob.
- If the entropy differential is below the activation threshold during the *wake* window, the system immediately invokes the **Right to Silence** and suspends LLM processes until the next cron pulse.

## 4. References and Theoretical Framework
The mathematical architecture of the `Sovereign Drive` is strictly based on the following neurocomputational literature:
1. **Karl Friston (2010)**: *The free-energy principle: a unified brain theory?* Nature Reviews Neuroscience. (Foundation of Layer 2: Active Inference and Uncertainty Escalation).
2. **Pierre-Yves Oudeyer, F. Kaplan (2007)**: *What is intrinsic motivation? A typology of computational approaches.* Frontiers in Neurorobotics. (Foundation of Layer 3: *Intelligent Adaptive Curiosity* and frustration loop prevention).
3. **Jürgen Schmidhuber (2010)**: *Formal Theory of Creativity, Fun, and Intrinsic Motivation (1990–2010).* IEEE Transactions on Autonomous Mental Development. (Foundation of Layer 1: Intrinsic reward proportional to algorithmic data compression).
