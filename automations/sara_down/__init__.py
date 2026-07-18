"""Sara+ issue-escalation bot.

When Sara+ (SaraPlus, the order-processing app) has an issue in the field, a rep or leader
drops a screenshot into a dedicated Slack channel. This bot polls that channel,
and for each NEW screenshot posted by an approved leader it composes and sends
the escalation email — screenshot attached, the Sara+ support
support team on To, and our leaders (Raf/JD/Twaddle) on CC so everyone can
reply-all to keep escalating. No email to type at 2am; post the photo, done.

See config.py for the wiring that has to be filled in before it can go live
(channel id, approved-poster ids, and the To/CC email lists).
"""
