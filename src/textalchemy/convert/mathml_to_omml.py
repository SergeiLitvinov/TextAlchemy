"""Compatibility entry point for the shared MathML-to-Office-Math structure converter."""

from textalchemy.core.mathml import MATHML, OMML, mathml_to_omml

__all__ = ['MATHML', 'OMML', 'mathml_to_omml']
