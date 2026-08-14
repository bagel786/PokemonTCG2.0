"""Compatibility namespace for the local isolated-package loader.

The public notebook's main.py does not import this package. Kaggle does not
require it; it exists only because ExternalSubmissionAgent expects an agent or
ptcg_ai namespace before loading a submission's main.py.
"""
