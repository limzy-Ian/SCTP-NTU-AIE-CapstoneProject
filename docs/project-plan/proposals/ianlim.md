Reviewed: data\images\nameplates (12 machines JPGs)
MYSQL\machines table (12 entries)
Existing Columns 4:
Machine_ID (primary key)
Machine_name - duplicate and not unique and ambiguous. Better identify with Serial_no and Location
Model: Brand and Model number. Better identify with Brand and Model
Year_installed: Integer.
Assumption: All this can be manually update if only less than 50 machines
This table should be improved and updated (no RAG/AI required) with:
Machine_ID (primary key)
Serial_no (unique)
Location
Brand
Model
Year_installed
MFG_Date
Power
Capacity
Weight
Lubicant
Grease_interval
Name_plate_JPG

Reviewed data\docs\sops\0000_gm_brief_email.txt
This project is to fullfill GM mains requirement (email SOP). MOM audit coming + what I want from the AI tool
(0) MOM WSH audit likely in Q4.
(1) our incident history queryable — but CAREFUL, we changed severity scale in Jul 2025, old 1 = new 5, auditors WILL catch us if we mix them up. 
(2) Techs keep asking 'what oil this machine use' / 'what's the grease interval' — answers are on the nameplates, we photographed all of them. 
(3) CNC-02 been feeling 'off' according to night shift — check the vibration logs? If we can show predictive maintenance to the auditor, big win.
(4) our sensor CSV is a mess — vendor mixed timestamp formats and half the temperature in Fahrenheit.

Suggestion:
(1) safety_incidents table dont tally with JPG. Auditor red flags.
(2) Machine Table if updated properly AI tool will be able to query already.
(3)(4) Build AI tool to monitor vibrations_temps csv, automatically ingest universal time and temp to SQL. analyze maintenance done/cycle relation with vibration. Alerts of vibrations /temp/  threshold/ changes.

Reviewed data\doc\sops\SOP-CRANE-02.txt
Max load information mis-match in SOP due to manuel update. compared with data\images\nameplates jpgs.

Suggestion:
I guess another one is to incorporate "Singapore MOM Workplace Safety Audit, Incident Classification & Reporting" AI skills and to analyse the safety incidents tracking that is currently in systems. Review with GM/prof to determine which is more critical to persuade.