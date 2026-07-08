## UPS Preventive Maintenance SOP

## Document Information

| Document ID    | EP-SOP-UPS-001                                                                          |
|----------------|-----------------------------------------------------------------------------------------|
| Title          | UPS Preventive Maintenance SOP                                                          |
| Version        | v1.1                                                                                    |
| Asset Class    | UPS                                                                                     |
| Applies To     | Eaton 9PX 1-3 kVA; use model-specific controls where the installed unit is Eaton 9PX G2 |
| Frequency      | Quarterly                                                                               |
| Classification | Internal Engineering -Curated MVP SOP                                                   |

## 1. Scope

This SOP covers external, non-invasive inspection of an energized UPS, including visual condition checks, ambient-temperature assessment, review of displayed status and alarm information, and documentation of abnormalities.

This SOP does not cover:

-  Opening UPS enclosure panels.
-  Internal electrical inspection or repair.
-  Energized electrical work.
-  Battery terminal inspection, tightening, cleaning, or replacement.
-  Internal fan cleaning or component replacement.
-  Any work requiring isolation, lockout/tagout, or electrical disassembly.

Cross-reference: Battery compartment access and dedicated battery visual inspection are covered by EP-SOP-BAT-001 - Battery Bank Inspection SOP . That is a separate procedure.

## 2. Personnel, PPE, and Safety Requirements

1.  Only personnel authorized by the site for data-center equipment inspection may perform this SOP.
2.  Follow site electrical-safety requirements, access-control requirements, and incident-reporting procedures.
3.  Use PPE required by the site risk assessment.

4.  Maintain safe clearance around the UPS and do not obstruct ventilation paths.
5.  Do not insert tools, fingers, probes, or foreign objects into openings.
6.  Do not use compressed air inside or through UPS openings.
7.  Do not open panels under this SOP.
8.  Escalate any condition requiring invasive service to qualified electrical or OEM-authorized personnel.

## 3. Pre-Inspection Checks

1.  Confirm the UPS asset ID, location, model, and inspection date.
2.  Confirm that the UPS is in normal operating mode before beginning inspection.
3.  Review the front-panel display or approved monitoring interface for active alarms, warnings, fault codes, load indication, and battery-related status.
4.  Record any active alarm before proceeding.
5.  Confirm that the UPS intake and exhaust areas are accessible and not blocked.

## 4. Ambient Temperature Assessment

1.  Measure and record ambient temperature at the UPS air intake using the approved site instrument.
2.  Record the measurement in the maintenance record.

| Status                                       | Ambient Temperature   | Required Action                                                                                                                                          |
|----------------------------------------------|-----------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------|
| Pass -Optimal                                | ≤25°C                 | Record the reading. Eaton identifies 25°C as the reference temperature for full battery life.                                                            |
| Monitor -Acceptable but Reduced Battery Life | >25°C to 30°C         | Log the reading and note potential accelerated battery degradation. No immediate escalation is required solely because the temperature is in this range. |
| Escalate                                     | >30°C                 | Notify facilities engineering immediately and record the condition.                                                                                      |

Controlled Note: The &gt;30°C escalation threshold is an engineering judgment used for this curated MVP SOP. The Eaton manual does not specify a formal 30°C escalation trigger.

[NEEDS OEM CONFIRMATION: site-approved formal escalation threshold.]

[Source: Eaton 9PX 1-3 kVA Manual, Section 6.1 - 25°C reference and battery-life relationship.]

## 5. External Visual Inspection

1.  Inspect the UPS enclosure for dents, cracks, corrosion, loose external hardware, damaged labels, or evidence of impact.
2.  Inspect accessible external cables, plugs, connectors, and cable routing for visible damage, strain, overheating marks, or insecure routing.
3.  Inspect ventilation openings for dust accumulation, blockage, or restricted airflow.
4.  Check the surrounding area for water, condensation, dust buildup, foreign objects, or other environmental hazards.
5.  Listen for unusual noise, including abnormal fan noise, rattling, buzzing, or vibration.
6.  Check for unusual odor, visible smoke, discoloration, or abnormal external heat.
7.  Do not remove covers, panels, or guards during this inspection.

## 6. Status, Alarm, and Battery Review

1.  Review displayed alarms, warnings, and event indicators.
2.  Record active UPS faults, warnings, overload conditions, bypass status, battery alarms, and selftest results where available.
3.  Review battery replacement alerts and battery-health information.
4.  For Eaton 9PX G2 units only, review ABM+ health indicators where available.
5.  Do not imply that ABM+ applies to standard Eaton 9PX units.

[Source: Eaton 9PX G2 documentation applies ABM+ to the G2 model family only.]

## 7. Escalation Conditions

Escalate to facilities engineering, qualified electrical personnel, or OEM-authorized service personnel for ambient temperature above 30°C, active fault alarms, recurring warnings, battery replacement alarms, failed self-tests, abnormal runtime, overheating, smoke, burning odor, moisture, damaged cables, enclosure damage, abnormal vibration, excessive noise, or any condition requiring invasive service.

## 8. Documentation and Post-Inspection Verification

1.  Record the asset ID, date, time, inspector name, and ambient-temperature reading.
2.  Record all active alarms, warnings, observed abnormalities, and actions taken.
3.  Record whether the UPS remained in normal operation after inspection.
4.  Create or update a maintenance ticket for all escalated conditions.

5.  Confirm that the UPS ventilation path remains unobstructed after inspection.
6.  Do not close an inspection record as "pass" if an unresolved alarm, abnormal temperature, visible damage, or safety concern remains.

## Revision History

| Version   | Date       | Author                 | Change                                                                                                                   |
|-----------|------------|------------------------|--------------------------------------------------------------------------------------------------------------------------|
| v1.0      | -          | ENGINPILOT Engineering | Initial draft                                                                                                            |
| v1.1      | 2026-07-05 | ENGINPILOT Engineering | Final controlled version. Corrected temperature treatment, battery-SOP cross-reference, and model- specificABM+ wording. |