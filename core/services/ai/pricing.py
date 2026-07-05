"""
Cost calculation for AI API usage.
"""

from decimal import Decimal, InvalidOperation
from typing import Optional


def parse_price_input(value: Optional[str]) -> Optional[Decimal]:
    """
    Parse a user-supplied token price into a Decimal.

    Accepts both the technical format (``0.01``) and the German decimal
    format (``0,01``). Empty or whitespace-only input is treated as "no
    price" and returns ``None``.

    Args:
        value: Raw price string from a form field (or ``None``).

    Returns:
        The parsed :class:`~decimal.Decimal`, or ``None`` for empty input.

    Raises:
        ValueError: If the value is non-empty but cannot be parsed as a
            decimal number.

    Example:
        >>> parse_price_input('0,01')
        Decimal('0.01')
        >>> parse_price_input('0.01')
        Decimal('0.01')
        >>> parse_price_input('') is None
        True
    """
    if value is None:
        return None

    normalized = value.strip()
    if not normalized:
        return None

    # Normalize the German decimal separator to a dot so both "0,01" and
    # "0.01" parse identically. Thousands separators are not expected here
    # (prices are small, per-1M-token values), so a bare comma is treated
    # as a decimal separator.
    normalized = normalized.replace(',', '.')

    try:
        return Decimal(normalized)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid price value: {value!r}") from exc


def calculate_cost(
    input_tokens: Optional[int],
    output_tokens: Optional[int],
    input_price_per_1m: Optional[Decimal],
    output_price_per_1m: Optional[Decimal]
) -> Optional[Decimal]:
    """
    Calculate the cost of an AI API call.
    
    Args:
        input_tokens: Number of input tokens used
        output_tokens: Number of output tokens generated
        input_price_per_1m: Price per 1 million input tokens
        output_price_per_1m: Price per 1 million output tokens
        
    Returns:
        Total cost in USD, or None if any required data is missing
        
    Example:
        >>> calculate_cost(1000, 500, Decimal('5.0'), Decimal('15.0'))
        Decimal('0.012500')
    """
    # Return None if any required data is missing
    if input_tokens is None or output_tokens is None:
        return None
    if input_price_per_1m is None or output_price_per_1m is None:
        return None
    
    # Calculate cost
    # cost = (input_tokens / 1_000_000 * input_price) + (output_tokens / 1_000_000 * output_price)
    input_cost = (Decimal(input_tokens) / Decimal(1_000_000)) * input_price_per_1m
    output_cost = (Decimal(output_tokens) / Decimal(1_000_000)) * output_price_per_1m
    
    total_cost = input_cost + output_cost
    
    return total_cost
