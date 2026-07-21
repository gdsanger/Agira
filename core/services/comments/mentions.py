"""
Parsing of structured @mention tokens in comment bodies.

A mention is stored in the comment body as a structured token, not as free-text
"@name", so that it can be resolved to a user identity server-side without
guessing from display names:

    @[Display Name](user:<id>)

The picker in the comment textarea (see item_comments_tab.html) inserts this
token when a user is selected from the autocomplete dropdown. Plain "@word"
text typed without picking a suggestion never matches this pattern and is
therefore never treated as a mention.
"""
import re
from typing import List

MENTION_PATTERN = re.compile(r'@\[(?P<name>[^\[\]]{1,150})\]\(user:(?P<id>\d+)\)')


def extract_mentioned_user_ids(body: str) -> List[int]:
    """
    Extract the unique user IDs referenced by structured mention tokens in body.

    Args:
        body: Comment body text (plain text, may contain mention tokens)

    Returns:
        List of user IDs in order of first appearance, without duplicates.
    """
    if not body:
        return []

    ids = []
    seen = set()
    for match in MENTION_PATTERN.finditer(body):
        user_id = int(match.group('id'))
        if user_id not in seen:
            seen.add(user_id)
            ids.append(user_id)
    return ids
