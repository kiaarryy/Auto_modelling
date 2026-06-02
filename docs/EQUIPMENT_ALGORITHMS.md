# Equipment Algorithms

## Pump

Implemented candidates: `affinity_y3`, `speed_poly`, `flow_speed_5term`.
Pump CSV power and frequency fields are joined with mapped flow CSVs by
timestamp. Final selection uses full-period CVRMSE with NMBE as the tie-breaker.
The optional MBL speed/system FMU remains archived reference work.

## Chiller

Implemented external-reference candidates: `ElectricEIR`,
`ElectricReformulatedEIR`, `Carnot_TEva`. The runner generates an `AllData2`
steady table, estimates measured nominals, filters start values against the FMI
interface, simulates all candidates, and scores `P`, `QEva`, and `COP`.

## Cooling tower

Implemented external-reference candidates: `Merkel`, `YorkCalc`. The runner
joins chiller/HX flow sources, compresses the full-period axis to five-minute
steps while preserving source-time mapping, forces YorkCalc `nFan=1.0`, and
applies Site A two-fan scaling exactly once in Python.

## Heat exchanger

Archived candidates: `ConstantEffectiveness`, `PlateEffectivenessNTU`. Full-period simulation is chunked and failed chunks must be reported.
