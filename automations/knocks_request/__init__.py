"""On-demand knocks — `/knocks` in Slack returns one office's knock board for
one day, without waiting for the morning run.

`service` is the engine (cache-first, live pull only when it has to, no Slack);
`handler` is the Slack modal + DM that rides the Jiraiya listener; `run` is the
offline CLI used to test either without posting anything."""
