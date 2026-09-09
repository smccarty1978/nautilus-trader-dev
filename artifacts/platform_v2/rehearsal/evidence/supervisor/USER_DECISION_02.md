# USER_DECISION_REQUIRED SUPERVISOR_ESCALATION_REQUIRED -- rehearsal_checkpoint_norm

worker 006_deterministic_repair_83703076 reports a platform defect: Study-side defect FIXED and committed 3b63ccd2 (CRITICAL-1 plus WARNING-2, WARNING-3, NOTE-1 swept together, recompiled 9eb2ff0d6e63). Controller still CONTRACT_BLOCKER because audit currency keys on the execution composite alone, so a repair can never clear an audit verdict. PLATFORM DEFECT: supervisor core routes AUDIT_BLOCKER only to launch_repair, with no re-audit route, so it loops repair workers to MAX_ATTEMPTS. See report. -- answer {"retry": true} to reset the attempt counters, anything else to stop

Answer: `python scripts/research.py supervise decide rehearsal_checkpoint_norm --answer <json file>`
