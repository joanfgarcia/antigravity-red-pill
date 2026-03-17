# Emotional Decay Multipliers: Empirical Basis

To satisfy the findings of the Red Pill V5.6.3 Audit and the Operator's directive, this document formalizes the empirical and scientific backing for the Emotional Decay Multipliers (Chroma) used in the Red Pill Protocol's erosion equations.

## 1. The Fading Affect Bias (FAB)
The core premise of the Red Pill's emotional multipliers is that different emotional valences and arousal states decay at different rates. This aligns perfectly with the extensively documented psychological phenomenon known as the **Fading Affect Bias (FAB)**.

- **Scientific Principle**: FAB states that the emotional intensity (affect) associated with negative autobiographical memories diminishes more quickly and to a greater extent over time than the affect linked to positive memories (Walker et al., 2003). 
- **Application in Red Pill**: 
  - `yellow` (Joy/Positive): Multiplier of `0.5` (slower decay). Supported by FAB, as positive feelings preserve their emotional weight longer.
  - `orange` (Anxiety/Negative): Multiplier of `1.5` (faster decay). Supported by FAB; negative affective arousal naturally clears faster to maintain emotional resilience.

## 2. Anxiety and Accelerated Forgetting
For negative high-arousal states like anxiety (`orange`), the accelerated decay rate (`1.5x`) is supported by physiological mechanisms:

- **Scientific Principle**: Acute stress and anxiety trigger the release of cortisol and adrenaline. While these hormones can hyper-focus immediate short-term encoding (salience), chronic or acute high-stress spikes actually *impair* long-term memory consolidation and retrieveal (Roozendaal, 2002). Furthermore, high-stress environments lead to distracted encoding, steepening the Ebbinghaus forgetting curve if the memory is not repeatedly reinforced.
- **Application in Red Pill**: The `1.5` multiplier accurately simulates the fragile consolidation of anxious states once the immediate stressor is removed.

## 3. Parametrization Strategy (v6.1.0)
To avoid hardcoding theoretical constants and to provide scientific flexibility, the Emotional Decay Multipliers will be externalized.

**Implementation**:
1. **External Config**: Extract the multipliers to `src/red_pill/data/affect_models.yaml`.
2. **Model Selection**: Introduce an environment variable (e.g., `AFFECT_DECAY_MODEL=PIONEER`) to allow the Operator to toggle between:
   - `PIONEER`: The default, highly pronounced synthetic multipliers (`yellow=0.5, orange=1.5`).
   - `ACADEMIC`: A flatter, more conservative model based strictly on Warriner et al. VAD dimensions.
   - `FLAT`: No multi-dimensional decay (`1.0` for all).
3. **Engine Update**: Update `src/red_pill/config.py` to load from this YAML dynamically at startup without adding recurring overhead.

---
### References
1. Walker, W. R., Skowronski, J. J., & Thompson, C. P. (2003). *Life is pleasant—and memory helps to keep it that way!*. Review of General Psychology.
2. Roozendaal, B. (2002). *Stress and memory: opposing effects of glucocorticoids on memory consolidation and memory retrieval*. Neurobiology of Learning and Memory.
