# Equipment Algorithms

## Pump

Implemented candidates: `affinity_y3`, `speed_poly`, `flow_speed_5term`.
Pump CSV power and frequency fields are joined with mapped flow CSVs by
timestamp. Final selection uses full-period CVRMSE with NMBE as the tie-breaker.
The optional MBL speed/system FMU remains archived reference work.

## Chiller

Archived candidates: `ElectricEIR`, `ElectricReformulatedEIR`, `Carnot_TEva`.

## Cooling tower

Archived candidates: `Merkel`, `YorkCalc`. Site A two-fan external scaling must be applied exactly once.

## Heat exchanger

Archived candidates: `ConstantEffectiveness`, `PlateEffectivenessNTU`. Full-period simulation is chunked and failed chunks must be reported.
