from urllib.parse import urlencode


def build_pagination_state(base_path, page, total_pages, params=None, group_size=5):
    total_pages = max(1, int(total_pages or 1))
    page = max(1, min(int(page or 1), total_pages))
    group_size = max(1, int(group_size or 5))

    params = {
        key: value
        for key, value in (params or {}).items()
        if value not in (None, "", [])
    }

    def build_url(target_page):
        query = dict(params)
        query["page"] = target_page
        encoded = urlencode(query, doseq=True)
        return f"{base_path}?{encoded}" if encoded else base_path

    block_start = ((page - 1) // group_size) * group_size + 1
    block_end = min(block_start + group_size - 1, total_pages)
    prev_block_page = block_start - 1 if block_start > 1 else None
    next_block_page = block_end + group_size if block_end < total_pages else None
    if next_block_page:
        next_block_page = min(total_pages, next_block_page)

    visible_numbers = set(range(block_start, block_end + 1))
    visible_numbers.add(1)
    visible_numbers.add(total_pages)
    if prev_block_page:
        visible_numbers.add(prev_block_page)
    if next_block_page:
        visible_numbers.add(next_block_page)

    items = []
    previous_number = None
    for number in sorted(visible_numbers):
        if number < 1 or number > total_pages:
            continue
        if previous_number is not None and number - previous_number > 1:
            items.append({"kind": "ellipsis"})
        items.append(
            {
                "kind": "page",
                "number": number,
                "url": build_url(number),
                "current": number == page,
                "jump": number in {prev_block_page, next_block_page},
            }
        )
        previous_number = number

    return {
        "page": page,
        "total_pages": total_pages,
        "items": items,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "prev_url": build_url(page - 1) if page > 1 else None,
        "next_url": build_url(page + 1) if page < total_pages else None,
        "first_url": build_url(1),
        "last_url": build_url(total_pages),
    }
