"""Benchmark fixture: off-by-one bug in a pagination helper."""


def paginate(items, page, per_page):
    """Return the requested page of items.

    The slice start is computed with ``page * per_page`` instead of
    ``(page - 1) * per_page``, so page 1 silently skips the first page of
    results. This is the bug the benchmark issue describes.
    """
    start = page * per_page
    end = start + per_page
    return items[start:end]


def page_count(total, per_page):
    if per_page <= 0:
        raise ValueError("per_page must be positive")
    return (total + per_page - 1) // per_page
