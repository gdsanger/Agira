"""
Data Transfer Objects for the Printing Framework
"""

from dataclasses import dataclass


@dataclass
class PdfResult:
    """
    Result of PDF rendering operation.
    
    Contains the PDF bytes and metadata for HTTP responses.
    """
    
    pdf_bytes: bytes
    filename: str
    content_type: str = "application/pdf"
    
    def __len__(self) -> int:
        """Return the size of PDF in bytes"""
        return len(self.pdf_bytes)
