"""automations.harvest — harvest-once Tableau cache layer (SHADOW-ONLY).

Nothing on the live 4am path imports this package. It is inert: no existing
report's run.py/pull.py, no day_orchestrator module, no schedule_config.json
entry, and no LaunchAgent references it. Building/running it CANNOT affect the
live 4am orchestrator run. See README.md and output/harvest-architecture-design.md.
"""
