"""Public self-serve Document Builder.

A small Streamlit app an ICD can open from a link, fill in their branding
(company, owner, location, colors, logo), and download a finished, branded PDF
— no back-and-forth with the team.

- registry.py : the list of available documents + the inputs each one needs
- app.py      : the Streamlit form (access code → form → generate → download
                → email + log)

Add a new document = add one Generator to registry.py; it shows up in the
dropdown automatically.
"""
