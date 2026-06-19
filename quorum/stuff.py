import os

# Your specific list of files
files_to_merge = [
    "core/coordination.py",
    "pipeline/session_context.py",
    "pipeline/models.py",
    "core/plan.py",
    "models/state.py",
    "agents/planner.py",
    "agents/governance_guardian.py",
    "agents/sql_engineer.py",
    "agents/cost_sentinel.py",
    "agents/orchestrator.py",
    "agents/reviewer.py",
    "pipeline/run_agent.py",
    "pipeline/adapter.py",
    "core/run_store.py",
    "backend/services/orchestration.py",
    "core/investigation.py",
    "agents/investigator.py",
    "agents/adjudicator.py",
    "core/adjudication.py"
]

output_filename = "combined_code.txt"

with open(output_filename, "w", encoding="utf-8") as outfile:
    for file_path in files_to_merge:
        if os.path.exists(file_path):
            # Writes a clear markdown visual anchor for each file
            outfile.write(f"\n\n# ==========================================\n")
            outfile.write(f"# FILE: {file_path}\n")
            outfile.write(f"# ==========================================\n\n")
            
            with open(file_path, "r", encoding="utf-8") as infile:
                outfile.write(infile.read())
            print(f"Merged: {file_path}")
        else:
            print(f"Skipped (Not Found): {file_path}")

print(f"\nDone! All files merged into '{output_filename}'")
