# Aptadynamic-VPA (Viability Power Administration)

PRAMA projection protocol applied to BPA transmission outage data.
PRAMA projects observables Ω only — it never models domain internals.

Modules: `ingest` → `omega` → `projection` → `validation`.

Data: cleaned BPA outages courtesy of Ian Dobson (Iowa State).
Bus names are anonymized in all outputs. The analysis and any conclusions
are strictly those of the authors and not of Bonneville Power Administration.

Run: `python scripts/run_pipeline.py data/outagesBPA.csv`
