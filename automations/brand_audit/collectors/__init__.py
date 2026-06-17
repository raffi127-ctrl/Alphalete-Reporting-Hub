"""Data collectors — one per source. Each takes a Company and returns a
normalized CollectorResult (metrics + evidence + flags), and FAILS SOFT: a
broken source records an error and an empty result instead of crashing the run.
"""
