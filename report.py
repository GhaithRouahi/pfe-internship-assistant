"""Rebuild data/review.html and open it."""
import os
from src import report

path = report.write()
print(path)
os.startfile(path)
