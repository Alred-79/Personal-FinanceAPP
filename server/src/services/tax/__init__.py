"""The tax & messy-data layer (Pillar 3).

Tax bucket tagging, tax-document ingestion, and a deterministic tax-summary /
estimated-tax engine. The agent ORGANIZES, SUMMARIZES, and ESTIMATES — it never
gives tax advice. Every surface in here is factual statements about the user's
own numbers; the advice firewall stays the backstop and a deterministic input
screen routes filing-advice questions to a static resource before the model is
called.

US calendar-year filer assumption throughout (see the tax-year note in
``summary_service``): dates are bare ``YYYY-MM-DD`` strings, USD-only, no
timezone — exactly the IRS cash-basis convention for a calendar-year filer.
"""
