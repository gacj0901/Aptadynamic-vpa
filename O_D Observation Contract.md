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
Violation of C2 can make Ξ track raw activity instead of structural deviation.
Historical numerical claims from kernel 0.1.0 require causal revalidation.

C3 is a bi-partitional gate and must pass independently in calibration and
evaluation. It has two passing branches: absolute,
\(|r_{\Delta\omega}| < r_*=0.5\), or relative,
\(|r_{deg}|-|r_{\Delta\omega}| > s_{min}=0.01\). Every record carries both
correlations, the separation, thresholds, and the deciding branch. A pass in
one partition cannot compensate for failure in the other.

### C4. Informational Density
The variance of Ξ over the characteristic memory timescale \( \tau_m \) must substantially exceed baseline stochastic noise.  
- BPA and NYISO density diagnostics are exploratory and must be regenerated
  under kernel 0.2.1 before quantitative comparison.

### C5. Bipartite Outcome
The domain must distinguish **occurrence** (\( Y_o \)) from **severity** (\( Y_s \)) separately.  
Occurrence and severity are separate outcomes and are evaluated independently.
Any superiority over a baseline is an empirical hypothesis for a particular
domain and induction epoch, never a guarantee of this contract.

### C6. Stationary Evaluation Instrument

Causality is necessary but not sufficient. Comparison thresholds MUST be fitted
once on a declared, versioned calibration partition that is temporally disjoint
from evaluation, then frozen for the entire aggregated evaluation period.
Boundary ties use a declared seeded random rule. Any recalibration starts a new
calibration epoch (`calib_v1`, `calib_v2`, ...) and every readout carries that ID.
PRAMA warm-up is consumed inside the same calibration partition.

### C7. Versioned Induction Epochs

Every causal expectation carries an `epoch_id`. A change to estimator family,
context, temporal regime, coverage parameters, or window opens a new induction
epoch. Compliance gates are evaluated within each epoch and never inherited
from another epoch.

### Namespace note

In the universal kernel package, N1 denotes scale invariance (historically
called AS-1 C4). In this deployed domain contract, C4 denotes informational
density. The distinct names prevent the two checks from sharing a record key.

---

### Key Empirical Lesson

BPA and NYISO use the same universal projection kernel \( \pi \). Whether either
record supports an empirical claim is determined only by the reproducible 0.2.1
outputs, not by historical figures.
