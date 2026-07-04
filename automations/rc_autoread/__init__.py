"""RingCentral wrap-up auto-read — scans the shared RingCentral extension
for unread SMS, and marks a conversation read once it has hit a known
wrap-up message (install confirmations, DirecTV/cell-phone hand-offs,
fiber-install reminders, or a lone customer photo near the top of the
thread). Conversations where the customer replied *after* the wrap-up are
left unread so a human still sees them. Read-only against Google Sheets —
this module talks only to the RingCentral API, not to any report Sheet."""
