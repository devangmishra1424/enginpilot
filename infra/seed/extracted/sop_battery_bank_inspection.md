## Battery Bank Inspection SOP

## Document Information

| Document ID    | EP-SOP-BAT-001                                       |
|----------------|------------------------------------------------------|
| Title          | Battery Bank Inspection SOP                          |
| Version        | v1.2                                                 |
| Asset Class    | Battery Bank                                         |
| Applies To     | Eaton 9PX battery system in the curatedMVP asset set |
| Frequency      | Quarterly                                            |
| Classification | Internal Engineering-CuratedMVP SOP                  |

## 1. Scope

This SOP covers dedicated battery-bank visual inspection, ambient-temperature assessment, review of battery alarms and self-test status, and documentation of visible battery condition.

This SOP does not authorize battery terminal tightening, cleaning, replacement, energized electrical work, battery module disassembly, battery replacement without an approved work order, insulation-resistance testing without OEM procedure, use of metal tools near battery modules, or battery-system isolation without approved site procedures.

## 2. Relationship to UPS Preventive Maintenance SOP

This SOP is separate from EP-SOP-UPS-001 - UPS Preventive Maintenance SOP .

Opening of battery-compartment access panels in Section 5 is permitted under this procedure only.

EP-SOP-UPS-001 excludes panel opening from its own scope. A technician performing general UPS PM must not open battery panels unless also performing this dedicated battery inspection under EP-SOP-BAT-001.

## 3. Personnel, PPE, and Safety Requirements

1.  Only personnel authorized by the site for battery-system inspection may perform this SOP.
2.  Follow site electrical-safety requirements and PPE requirements.

3.  Use an observer or second person where required by site procedure for energized-equipment work areas.
4.  Remove metallic jewelry and secure loose conductive items before approaching battery compartments.
5.  Do not use metal tools near battery modules.
6.  Do not place conductive objects on battery equipment.
7.  Do not touch exposed terminals or attempt terminal work under this SOP.
8.  Escalate any evidence of leakage, swelling, heat damage, corrosion, damaged insulation, or abnormal odor.

## 4. Ambient Temperature Assessment

1.  Measure and record ambient temperature at the battery or UPS intake using the approved site instrument.
2.  Record the measurement in the maintenance record.

| Status                                       | Ambient Temperature   | Required Action                                                                                                                                          |
|----------------------------------------------|-----------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------|
| Pass -Optimal                                | ≤25°C                 | Record the reading. Eaton identifies 25°C as the reference temperature for full battery life.                                                            |
| Monitor -Acceptable but Reduced Battery Life | >25°C to 30°C         | Log the reading and note potential accelerated battery degradation. No immediate escalation is required solely because the temperature is in this range. |
| Escalate                                     | >30°C                 | Notify facilities engineering immediately and record the condition.                                                                                      |

Controlled Note: The &gt;30°C escalation threshold is an engineering judgment used for this curated MVP SOP. The Eaton manual does not specify a formal 30°C escalation trigger.

[NEEDS OEM CONFIRMATION: site-approved formal escalation threshold.]

[Source: Eaton 9PX 1-3 kVA Manual, Section 6.1.]

## 5. Battery Inspection Procedure

1.  Confirm the UPS and battery asset ID, location, model, and inspection date.
2.  Confirm battery type as sealed, maintenance-free, valve-regulated lead-acid batteries.
3.  Review active battery alarms, battery replacement alerts, self-test results, and runtime indications.

[Source: Eaton 9PX 1-3 kVA Manual, Table 9 - Battery Specifications.]

Confirmed specification: Minimum 3-year float service life at 25°C.

4.  For Eaton 9PX G2 units only, review ABM+ health indicators where available. Do not apply ABM+ requirements to standard Eaton 9PX units.
5.  Open battery-compartment access panels for external visual observation only, where permitted by site procedure.
6.  Inspect battery modules and accessible battery-compartment areas for swelling, deformation, leakage, visible corrosion, damaged insulation, loose visible hardware, abnormal odor, discoloration, excessive heat, moisture, or contamination.
7.  Do not touch terminals, tighten connections, clean corrosion, remove modules, or use metal tools.
8.  Close access panels after visual inspection and confirm that the compartment is secure.
9.  Record all findings and create a maintenance ticket for abnormal conditions.

## 6. Battery Replacement Criteria

1.  Replace batteries based on OEM battery-health alarms, failed self-tests, reduced runtime, physical degradation, leakage, swelling, corrosion requiring service, or other documented failure indicators.
2.  Eaton states that batteries are rated for a 3-5 year service life, with actual life varying based on usage frequency and ambient temperature.
3.  Eaton states that battery replacement is recommended at a minimum of every 4 years to maintain peak efficiency.

[Source: Eaton 9PX 1-3 kVA Manual, Section 6.1 and Section 6.3.]

4.  Eaton states that battery life is divided by two for each 10°C above 25°C.
5.  Do not use a fixed replacement interval as the only replacement criterion without confirming the installed battery configuration and site operating conditions.

[Source: Eaton 9PX 1-3 kVA Manual, Section 6.1.]

## 7. Insulation-Resistance Testing

If insulation-resistance testing is required by the OEM service procedure, it must be performed only by qualified electrical personnel with the battery system fully isolated and in accordance with the OEM-specified test procedure.

[NEEDS OEM CONFIRMATION: insulation-resistance testing requirement, test voltage, acceptance criteria, and interval were not confirmed from available Eaton documentation. Do not perform this test without OEM guidance.]

## 8. Escalation Conditions

Escalate immediately to qualified electrical personnel, facilities engineering, or OEM-authorized service personnel for ambient temperature above 30°C, battery swelling, leakage, deformation, abnormal odor, overheating, discoloration, smoke, burning smell, replacement alarms, failed selftests, abnormal runtime, visible corrosion requiring intervention, damaged insulation, exposed conductive parts, moisture, repeated battery alarms, or any task requiring terminal work, module removal, replacement, isolation, or invasive electrical testing.

## 9. Documentation and Post-Inspection Verification

1.  Record the asset ID, date, time, inspector, ambient-temperature reading, and inspection result.
2.  Record battery alarms, self-test status, runtime observations, and ABM+ status where applicable to 9PX G2.
3.  Record all visible abnormalities, escalation actions, and work-order references.
4.  Confirm that battery access panels are closed and secure after inspection.
5.  Do not mark the inspection as complete if an unresolved safety concern, alarm, physical battery defect, or elevated-temperature condition remains open.

## Revision History

| Version   | Date       | Author                 | Change                                                                                        |
|-----------|------------|------------------------|-----------------------------------------------------------------------------------------------|
| v1.0      | -          | ENGINPILOT Engineering | Initial draft                                                                                 |
| v1.1      | -          | ENGINPILOT Engineering | Battery-SOP cross-reference and scope clarification                                           |
| v1.2      | 2026-07-05 | ENGINPILOT Engineering | Final controlled version. Added confirmed Eaton minimum four-year replacement recommendation. |