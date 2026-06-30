"""PDF utilities for merging and manipulating PDF files."""

import os
from pypdf import PdfWriter


def concat_pdf(pdf_files: list[str], output_file: str = None) -> str:
    """
    Concatenate multiple PDF files into a single PDF.
    
    Args:
        pdf_files: List of PDF file paths to concatenate
        output_file: Output file path. If None, creates 'merged.pdf' 
                    in the same directory as the first input file
    
    Returns:
        str: Path to the merged PDF file
        
    Raises:
        ValueError: If pdf_files list is empty
        FileNotFoundError: If any input PDF file doesn't exist
        
    Example:
        >>> pdf_files = ['file1.pdf', 'file2.pdf', 'file3.pdf']
        >>> output = concat_pdf(pdf_files)
        >>> print(f"Merged PDF created: {output}")
    """
    if not pdf_files:
        raise ValueError("pdf_files list cannot be empty")
    
    # Verify all input files exist
    for pdf_file in pdf_files:
        if not os.path.exists(pdf_file):
            raise FileNotFoundError(f"PDF file not found: {pdf_file}")
    
    # Determine output file path
    if output_file is None:
        first_file_dir = os.path.dirname(pdf_files[0])
        output_file = os.path.join(first_file_dir, 'merged.pdf')
    
    # Merge PDFs
    writer = PdfWriter()
    try:
        for pdf in pdf_files:
            writer.append(pdf)
        
        with open(output_file, "wb") as f:
            writer.write(f)
    finally:
        writer.close()
    
    return output_file


__all__ = ['concat_pdf']
