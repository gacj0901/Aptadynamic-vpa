# O_D Observation Contract

**Faithfulness conditions for the observation operator**  
Extracted and generalized from BPA and NYISO empirical cases.

An observation operator \( O_D : D \rightarrow \Omega \) is considered **PRAMA-faithful** if and only if it satisfies the following conditions:

### C1. Atomic Observable Event
There exists a timestamped stream of observable events without access to the domain’s internal state.  
**Examples**: BPA/NYISO → outages; LLM → token generation.

### C2. Proper Causal Conditional Expectation
\[
\widehat{O}(t) = E[O(t) \mid \text{domain's own rhythm}],
\]
computed exclusively from past observations.  

In the electrical grid case: \( E[\text{intensity} \mid \text{hour, month}] \).  
The original NYISO implementation violated this by using a constant global median, causing degeneration.

### C3. Δ as Structural Decoupling (not raw intensity)
\[
\Delta_t = \frac{|O_t - \widehat{O}_t|}{\widehat{O}_t + 1}
\]
Violation of C2 necessarily implies violation of C3: the tension accumulator Ξ begins to accumulate raw activity instead of structural deviation. This was the root cause of the initial negative result in NYISO (ratio 0.55).

### C4. Informational Density
The variance of Ξ over the characteristic memory timescale \( \tau_m \) must substantially exceed baseline stochastic noise.  
- BPA satisfies this comfortably.  
- NYISO satisfies it only marginally (hence the corrected ratio of 1.90 instead of ~16).

### C5. Bipartite Outcome
The domain must distinguish **occurrence** (\( Y_o \)) from **severity** (\( Y_s \)) separately.  
PRAMA only guarantees improved discrimination of conditional severity \( P(Y_s \mid Y_o) \). Occurrence forecasting remains the responsibility of causal Markovian baselines.

---

### Key Empirical Lesson

Both successful BPA and corrected NYISO satisfy **C1–C5** while using the **same** universal projection kernel \( \pi \).  

The original NYISO failure was a clear violation of **C2 → C3**. Correcting the observation operator (Δ) was sufficient to reverse the sign, demonstrating the robustness of the kernel when the contract is respected.
