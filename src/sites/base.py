from dataclasses import dataclass


@dataclass
class Job:
    site: str
    url: str
    title: str
    company: str
    text: str = ""
    meta: str = ""      # short header text (location, contract type) used by the internship filter
