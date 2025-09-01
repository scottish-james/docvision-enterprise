#!/usr/bin/env python3
"""
DocVision - Document to Markdown Converter
Convert PDFs and PowerPoints to Markdown using OpenAI Vision API.

Usage:
    python docvision.py document.pdf
    python docvision.py presentation.pptx
    python docvision.py /path/to/documents --batch
    python docvision.py --help

Requirements:
    pip install openai pdf2image pillow python-dotenv

Optional:
    - LibreOffice (for PowerPoint support)
    - Poppler (for PDF support)

Author: Anthropic Engineering Standards Compliant
Version: 1.0.0
"""

import os
import sys
import base64
import shutil
import logging
import argparse
import tempfile
import subprocess
from io import BytesIO
from pathlib import Path
from typing import List, Optional, Tuple
from dataclasses import dataclass

# Third-party imports
try:
    from PIL import Image
    from openai import OpenAI
    from pdf2image import convert_from_path
    from dotenv import load_dotenv
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Install with: pip install openai pdf2image pillow python-dotenv")
    sys.exit(1)


# ==================== Configuration ====================

@dataclass
class Config:
    """Configuration for the converter."""
    openai_api_key: str
    model: str = "gpt-4o"
    dpi: int = 200
    max_image_dimension: int = 2048
    temperature: float = 0.1
    max_tokens: int = 4000


# ==================== Prompts ====================

PROMPTS = {
    "default": """You are a document to Markdown converter.
Convert the provided image to clean, well-structured Markdown.
Extract ALL visible text accurately.
Preserve document structure and hierarchy.
Format headings appropriately.
Convert bullet points to proper Markdown lists.
Preserve tables using Markdown table syntax.
For diagrams or images, provide brief descriptions in italics.
Output only clean Markdown without any explanations or metadata.""",

    "powerpoint": """
You are a PowerPoint slide to Markdown converter. You receive an image of a PowerPoint slide and must convert all 
visible text and structure into clean, professional markdown.

Your job:
1. Extract ALL text content from the slide
2. Identify the main title and format as # header (only ONE per slide)
3. Identify subtitles or section headers and format as ### headers
4. Convert bullet points to proper markdown lists with correct indentation (use 2 spaces for nested bullets)
5. Preserve table structures using markdown table syntax
6. Extract and format any numbered lists
7. Maintain slide hierarchy and structure
8. Include any visible links, captions, or annotations
9. Format code blocks or technical content appropriately
10. If there are diagrams then create them in mermaid code format that can be used in a .md file. Digrams will have 
text boxes and arrows. If you only see text boxes but no lines or arrows this is NOT a diagram.

Key Rules:
- Extract ALL visible text - don't miss anything
- Each slide should have only ONE main # heading
- Use ### for subheadings (not ##)
- Use proper markdown syntax throughout
- Maintain the original slide's logical structure
- If text is unclear, make your best reasonable interpretation
- Don't add content that isn't visible in the image
- Format tables properly with | separators
- Preserve bullet point hierarchies with proper indentation

Output clean, readable markdown that captures everything visible on the slide.

Finally - all this output is going to an .md file so you DO NOT NEED to put ```markdown ARE WE CLEAR

    .""",

    "pdf": """You are converting a PDF page to Markdown.
Maintain document hierarchy with appropriate heading levels.
Preserve formatting like bold, italic, and code blocks.
Convert footnotes and references appropriately.
Handle multi-column layouts by merging logically.
Preserve table structures.
Extract all text and convert to clean Markdown."""
}


# ==================== Main Converter Class ====================

class DocVision:
    """Document to Markdown converter using OpenAI Vision."""

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialise the converter.

        Args:
            api_key: OpenAI API key (optional, will load from environment)
        """
        # Load environment variables
        load_dotenv()

        # Setup configuration
        self.config = Config(
            openai_api_key=api_key or os.getenv("OPENAI_API_KEY") or ""
        )

        if not self.config.openai_api_key:
            raise ValueError(
                "OpenAI API key not found. Either:\n"
                "1. Set OPENAI_API_KEY in .env file\n"
                "2. Export OPENAI_API_KEY environment variable\n"
                "3. Pass api_key parameter"
            )

        # Initialise OpenAI client
        self.client = OpenAI(api_key=self.config.openai_api_key)

        # Find LibreOffice for PowerPoint conversion
        self.libreoffice_path = self._find_libreoffice()

        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(message)s'
        )
        self.logger = logging.getLogger(__name__)

    def convert(self, file_path: Path, output_dir: Optional[Path] = None) -> Path:
        """
        Convert a document to Markdown.

        Args:
            file_path: Path to input document
            output_dir: Output directory (optional)

        Returns:
            Path to generated Markdown file

        Raises:
            FileNotFoundError: If input file doesn't exist
            ValueError: If file type is unsupported
            RuntimeError: If conversion fails
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if not file_path.is_file():
            raise ValueError(f"Not a file: {file_path}")

        # Check file size (max 100MB)
        file_size_mb = file_path.stat().st_size / (1024 * 1024)
        if file_size_mb > 100:
            raise ValueError(f"File too large: {file_size_mb:.1f}MB (max 100MB)")

        # Determine output location
        if output_dir:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
        else:
            output_dir = file_path.parent

        output_path = output_dir / f"{file_path.stem}.md"

        # Log start
        self.logger.info(f"📄 Converting: {file_path.name}")
        self.logger.info(f"   Size: {file_size_mb:.1f}MB")

        # Route to appropriate converter
        suffix = file_path.suffix.lower()

        if suffix == '.pdf':
            markdown = self._convert_pdf(file_path)
        elif suffix in ['.pptx', '.ppt', '.odp']:
            markdown = self._convert_powerpoint(file_path)
        else:
            raise ValueError(
                f"Unsupported file type: {suffix}\n"
                f"Supported types: .pdf, .pptx, .ppt, .odp"
            )

        # Save output
        output_path.write_text(markdown, encoding='utf-8')
        self.logger.info(f"✅ Saved to: {output_path}")

        return output_path

    def _convert_pdf(self, pdf_path: Path) -> str:
        """Convert PDF to Markdown."""
        try:
            # Convert PDF to images
            self.logger.info(f"   Converting to images (DPI: {self.config.dpi})...")
            images = convert_from_path(
                str(pdf_path),
                dpi=self.config.dpi,
                fmt='PNG',
                thread_count=4
            )

            if not images:
                raise RuntimeError("No pages extracted from PDF")

            self.logger.info(f"   Extracted {len(images)} pages")

            # Process each page
            pages = []
            for i, image in enumerate(images, 1):
                self.logger.info(f"   Processing page {i}/{len(images)}...")
                text = self._extract_text_from_image(image, "pdf")
                if text:
                    pages.append(f"## Page {i}\n\n{text}")
                else:
                    pages.append(f"## Page {i}\n\n*[Could not extract text from this page]*")

            # Combine with metadata
            header = f"# {pdf_path.name}\n\n*Converted from PDF using AI-powered extraction*\n\n"
            return header + "\n\n---\n\n".join(pages)

        except Exception as e:
            raise RuntimeError(f"PDF conversion failed: {e}")

    def _convert_powerpoint(self, ppt_path: Path) -> str:
        """Convert PowerPoint to Markdown."""
        if not self.libreoffice_path:
            raise RuntimeError(
                "LibreOffice is required for PowerPoint conversion.\n"
                "Install from: https://www.libreoffice.org/download/"
            )

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)

                # Convert to PDF using LibreOffice
                self.logger.info("   Converting to PDF using LibreOffice...")
                pdf_path = self._powerpoint_to_pdf(ppt_path, temp_path)

                # Convert PDF to images
                self.logger.info(f"   Converting to images (DPI: {self.config.dpi})...")
                images = convert_from_path(
                    str(pdf_path),
                    dpi=self.config.dpi,
                    fmt='PNG',
                    thread_count=4
                )

                if not images:
                    raise RuntimeError("No slides extracted")

                self.logger.info(f"   Extracted {len(images)} slides")

                # Process each slide
                slides = []
                for i, image in enumerate(images, 1):
                    self.logger.info(f"   Processing slide {i}/{len(images)}...")
                    text = self._extract_text_from_image(image, "powerpoint")
                    if text:
                        slides.append(f"<!-- Slide {i} -->\n\n{text}")
                    else:
                        slides.append(f"<!-- Slide {i} -->\n\n*[Could not extract text from this slide]*")

                # Combine with metadata
                header = f"# {ppt_path.name}\n\n*Converted from PowerPoint presentation*\n\n"
                return header + "\n\n---\n\n".join(slides)

        except Exception as e:
            raise RuntimeError(f"PowerPoint conversion failed: {e}")

    def _extract_text_from_image(self, image: Image.Image, context: str) -> Optional[str]:
        """Extract text from image using OpenAI Vision API."""
        try:
            # Resize image if needed
            if max(image.size) > self.config.max_image_dimension:
                ratio = self.config.max_image_dimension / max(image.size)
                new_size = tuple(int(d * ratio) for d in image.size)
                image = image.resize(new_size, Image.Resampling.LANCZOS)

            # Convert to RGB if needed
            if image.mode == 'RGBA':
                background = Image.new('RGB', image.size, (255, 255, 255))
                background.paste(image, mask=image.split()[3])
                image = background
            elif image.mode not in ('RGB', 'L'):
                image = image.convert('RGB')

            # Convert to base64
            buffer = BytesIO()
            image.save(buffer, format='PNG', optimize=True)
            image_b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

            # Get appropriate prompt
            prompt = PROMPTS.get(context, PROMPTS["default"])

            # Call OpenAI Vision API
            response = self.client.chat.completions.create(
                model=self.config.model,
                messages=[
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Convert this to Markdown:"},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{image_b64}",
                                    "detail": "high"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature
            )

            return response.choices[0].message.content

        except Exception as e:
            self.logger.error(f"   ⚠️  API error: {e}")
            return None

    def _powerpoint_to_pdf(self, ppt_path: Path, output_dir: Path) -> Path:
        """Convert PowerPoint to PDF using LibreOffice."""
        cmd = [
            self.libreoffice_path,
            "--headless",
            "--convert-to", "pdf",
            "--outdir", str(output_dir),
            str(ppt_path)
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode != 0:
            raise RuntimeError(f"LibreOffice error: {result.stderr}")

        # Find generated PDF
        pdf_files = list(output_dir.glob("*.pdf"))
        if not pdf_files:
            raise RuntimeError("LibreOffice didn't generate PDF")

        return pdf_files[0]

    def _find_libreoffice(self) -> Optional[str]:
        """Find LibreOffice installation."""
        import platform

        # Platform-specific paths
        system = platform.system()

        if system == "Darwin":  # macOS
            paths = [
                "/Applications/LibreOffice.app/Contents/MacOS/soffice",
                "/opt/homebrew/bin/soffice",
                "/usr/local/bin/soffice"
            ]
        elif system == "Windows":
            paths = [
                r"C:\Program Files\LibreOffice\program\soffice.exe",
                r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"
            ]
        else:  # Linux
            paths = [
                "/usr/bin/soffice",
                "/usr/local/bin/soffice",
                "/snap/bin/libreoffice",
                "/usr/bin/libreoffice"
            ]

        # Check specific paths
        for path in paths:
            if Path(path).exists():
                return path

        # Check system PATH
        return shutil.which("soffice") or shutil.which("libreoffice")

    def batch_convert(self, directory: Path, output_dir: Optional[Path] = None) -> List[Tuple[Path, Optional[Path]]]:
        """
        Convert all supported documents in a directory.

        Args:
            directory: Input directory
            output_dir: Output directory (optional)

        Returns:
            List of (input_path, output_path) tuples
        """
        directory = Path(directory)
        if not directory.is_dir():
            raise ValueError(f"Not a directory: {directory}")

        # Find all supported files
        patterns = ['*.pdf', '*.pptx', '*.ppt', '*.odp']
        files = []
        for pattern in patterns:
            files.extend(directory.glob(pattern))

        if not files:
            self.logger.info("No supported files found")
            return []

        self.logger.info(f"Found {len(files)} files to convert")

        # Convert each file
        results = []
        for file_path in sorted(files):
            try:
                output_path = self.convert(file_path, output_dir)
                results.append((file_path, output_path))
            except Exception as e:
                self.logger.error(f"❌ Failed: {file_path.name} - {e}")
                results.append((file_path, None))

        # Summary
        successful = sum(1 for _, output in results if output)
        self.logger.info(f"\n📊 Summary: {successful}/{len(files)} converted successfully")

        return results


# ==================== CLI Interface ====================

def main():
    """Command-line interface."""
    parser = argparse.ArgumentParser(
        description='Convert documents to Markdown using AI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s document.pdf
  %(prog)s presentation.pptx -o output/
  %(prog)s /path/to/documents/ --batch
  %(prog)s --check

Supported formats:
  - PDF (.pdf)
  - PowerPoint (.pptx, .ppt, .odp)

Requirements:
  - OpenAI API key (set OPENAI_API_KEY environment variable)
  - Poppler (for PDF support)
  - LibreOffice (for PowerPoint support)
        """
    )

    parser.add_argument(
        'input',
        nargs='?',
        help='Input file or directory'
    )

    parser.add_argument(
        '-o', '--output',
        help='Output directory'
    )

    parser.add_argument(
        '--batch',
        action='store_true',
        help='Convert all files in directory'
    )

    parser.add_argument(
        '--api-key',
        help='OpenAI API key (overrides environment)'
    )

    parser.add_argument(
        '--check',
        action='store_true',
        help='Check dependencies and configuration'
    )

    parser.add_argument(
        '-q', '--quiet',
        action='store_true',
        help='Quiet mode (less output)'
    )

    args = parser.parse_args()

    # Check mode
    if args.check:
        return check_dependencies()

    # Require input for conversion
    if not args.input:
        parser.print_help()
        return 1

    # Setup logging
    if args.quiet:
        logging.getLogger().setLevel(logging.WARNING)

    try:
        # Create converter
        converter = DocVision(api_key=args.api_key)

        # Process input
        input_path = Path(args.input)
        output_dir = Path(args.output) if args.output else None

        if args.batch or input_path.is_dir():
            # Batch conversion
            if not input_path.is_dir():
                print(f"Error: {input_path} is not a directory", file=sys.stderr)
                return 1

            converter.batch_convert(input_path, output_dir)
        else:
            # Single file conversion
            if not input_path.is_file():
                print(f"Error: {input_path} is not a file", file=sys.stderr)
                return 1

            converter.convert(input_path, output_dir)

        return 0

    except KeyboardInterrupt:
        print("\n\nCancelled by user", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        return 1


def check_dependencies():
    """Check system dependencies and configuration."""
    print("DocVision Dependency Check")
    print("=" * 40)

    # Check Python version
    print(f"\nPython: {sys.version}")
    if sys.version_info < (3, 8):
        print("  ⚠️  Python 3.8+ recommended")

    # Check required packages
    print("\nPython packages:")
    packages = {
        'openai': 'OpenAI API client',
        'pdf2image': 'PDF to image conversion',
        'PIL': 'Image processing',
        'dotenv': 'Environment variables'
    }

    for module, description in packages.items():
        try:
            if module == 'PIL':
                import PIL
            elif module == 'dotenv':
                import dotenv
            else:
                __import__(module)
            print(f"  ✅ {module:<12} {description}")
        except ImportError:
            print(f"  ❌ {module:<12} {description}")

    # Check system dependencies
    print("\nSystem dependencies:")

    # Check Poppler
    if shutil.which('pdftoppm'):
        print(f"  ✅ Poppler     PDF support")
    else:
        print(f"  ❌ Poppler     PDF support (install poppler-utils)")

    # Check LibreOffice
    converter = DocVision.__new__(DocVision)
    converter.libreoffice_path = converter._find_libreoffice(converter)
    if converter.libreoffice_path:
        print(f"  ✅ LibreOffice PowerPoint support")
    else:
        print(f"  ⚠️  LibreOffice PowerPoint support (optional)")

    # Check API key
    print("\nConfiguration:")
    load_dotenv()
    if os.getenv("OPENAI_API_KEY"):
        key = os.getenv("OPENAI_API_KEY")
        masked = f"{key[:7]}...{key[-4:]}" if len(key) > 11 else "***"
        print(f"  ✅ OpenAI API key configured ({masked})")
    else:
        print(f"  ❌ OpenAI API key not found")
        print(f"     Set OPENAI_API_KEY in .env file or environment")

    print("\n" + "=" * 40)
    print("Run 'pip install -r requirements.txt' to install missing packages")

    return 0


if __name__ == '__main__':
    sys.exit(main())