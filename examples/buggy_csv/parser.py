def parse_csv(text):
    """A deliberately buggy CSV parser used by the demo."""
    rows = []
    for line in text.splitlines():
        rows.append([cell.strip() for cell in line.split(",")])
    return rows[0] if len(rows) <= 1 else rows
