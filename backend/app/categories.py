"""The one list of job categories.

The extraction schema (`routes/scraper.py`) constrains the model to these
values and the feed filter (`routes/jobs.py`) offers them to the UI; keeping
a single definition means a category added here reaches both.
"""

CATEGORIES: tuple[str, ...] = (
    "Engineering",
    "Marketing",
    "Sales",
    "HR",
    "Finance",
    "Design",
    "Operations",
    "Product",
    "Legal",
    "Other",
)
