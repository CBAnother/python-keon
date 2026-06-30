"""Tests for PDF module."""

import os
import tempfile
import pytest
from pypdf import PdfWriter, PdfReader
from keon.pdf import concat_pdf


def create_test_pdf(file_path: str, page_count: int = 1):
    """Helper function to create a test PDF file."""
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=200, height=200)
    with open(file_path, 'wb') as f:
        writer.write(f)
    writer.close()


class TestConcatPdf:
    """Test cases for concat_pdf function."""
    
    def test_concat_pdf_basic(self):
        """Test basic PDF concatenation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test PDFs
            pdf1 = os.path.join(tmpdir, 'test1.pdf')
            pdf2 = os.path.join(tmpdir, 'test2.pdf')
            pdf3 = os.path.join(tmpdir, 'test3.pdf')
            
            create_test_pdf(pdf1, page_count=2)
            create_test_pdf(pdf2, page_count=3)
            create_test_pdf(pdf3, page_count=1)
            
            # Merge PDFs
            pdf_files = [pdf1, pdf2, pdf3]
            output = concat_pdf(pdf_files)
            
            # Verify output file exists in the same directory as first PDF
            assert os.path.exists(output)
            assert output == os.path.join(tmpdir, 'merged.pdf')
            
            # Verify merged PDF has correct page count
            reader = PdfReader(output)
            assert len(reader.pages) == 6  # 2 + 3 + 1
    
    def test_concat_pdf_custom_output(self):
        """Test PDF concatenation with custom output path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test PDFs
            pdf1 = os.path.join(tmpdir, 'test1.pdf')
            pdf2 = os.path.join(tmpdir, 'test2.pdf')
            
            create_test_pdf(pdf1, page_count=1)
            create_test_pdf(pdf2, page_count=1)
            
            # Merge with custom output
            custom_output = os.path.join(tmpdir, 'custom_merged.pdf')
            output = concat_pdf([pdf1, pdf2], output_file=custom_output)
            
            # Verify
            assert os.path.exists(output)
            assert output == custom_output
    
    def test_concat_pdf_empty_list(self):
        """Test that empty PDF list raises ValueError."""
        with pytest.raises(ValueError, match="pdf_files list cannot be empty"):
            concat_pdf([])
    
    def test_concat_pdf_nonexistent_file(self):
        """Test that nonexistent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            concat_pdf(['nonexistent.pdf'])
    
    def test_concat_pdf_single_file(self):
        """Test concatenation with single PDF file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf1 = os.path.join(tmpdir, 'test1.pdf')
            create_test_pdf(pdf1, page_count=5)
            
            output = concat_pdf([pdf1])
            
            assert os.path.exists(output)
            reader = PdfReader(output)
            assert len(reader.pages) == 5
