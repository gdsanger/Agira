"""
Cost calculation for AI API usage.
"""

from decimal import Decimal
from typing import Optional


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
