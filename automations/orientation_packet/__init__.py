"""Orientation Packet generator.

Re-skins the team Orientation Manual (originally the Alphalete "RAF FIBER
ORIENTATION MANUAL" in Canva) into a finished, branded PDF for any company.

Someone enters a company name, owner name, location, brand colors, and a logo;
`build.py` renders a print-ready PDF with the manual's content and that
company's branding swapped in.

- content.py : the manual as tokenized page specs ({company}/{owner}/... tokens)
- build.py   : reportlab renderer + CLI

See build.py --help.
"""
