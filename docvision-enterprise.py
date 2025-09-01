#!/usr/bin/env python3
"""
DocVision - Document to Markdown Converter with Enterprise LLM Support
Convert PDFs and PowerPoints to Markdown using Enterprise LLM only.

Usage:
    python docvision.py document.pdf
    python docvision.py presentation.pptx
    python docvision.py /path/to/documents --batch
    python docvision.py --help

Requirements:
    pip install pdf2image pillow python-dotenv requests

    Required files:
    - JWT_token.txt (Enterprise LLM authentication)
    - model_url.txt (Enterprise LLM endpoint)

Optional:
    - LibreOffice (for PowerPoint support)
    - Poppler (for PDF support)

Author: Enterprise Edition
Version: 3.0.1
"""

import os
import sys
import base64
import shutil
import logging
import argparse
import tempfile
import subprocess
import json
import requests
import time  # Added for pause functionality
from io import BytesIO
from pathlib import Path
from typing import List, Optional, Tuple, Dict
from dataclasses import dataclass

# Third-party imports
try:
    from PIL import Image
    from pdf2image import convert_from_path
    from dotenv import load_dotenv
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Install with: pip install pdf2image pillow python-dotenv requests")
    sys.exit(1)


# ==================== Configuration ====================

@dataclass
class Config:
    """Configuration for the converter."""
    # Enterprise LLM settings
    enterprise_jwt_token: Optional[str] = None
    enterprise_model_url: Optional[str] = None

    # Common settings
    dpi: int = 200
    max_image_dimension: int = 2048
    temperature: float = 0.1
    max_tokens: int = 4000
    batch_size: int = 5  # For slide batching
    pause_seconds: int = 10  # Pause between image processing


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

    "powerpoint": """You are a PowerPoint slide to Markdown converter. You receive an image of a PowerPoint slide and must convert all visible text and structure into clean, professional markdown.

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
10. If there are diagrams then create them in mermaid code format that can be used in a .md file. Diagrams will have text boxes and arrows. If you only see text boxes but no lines or arrows this is NOT a diagram.

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

Finally - all this output is going to an .md file so you DO NOT NEED to put ```markdown ARE WE CLEAR""",

    "pdf": """You are converting a PDF page to Markdown.
Maintain document hierarchy with appropriate heading levels.
Preserve formatting like bold, italic, and code blocks.
Convert footnotes and references appropriately.
Handle multi-column layouts by merging logically.
Preserve table structures.
Extract all text and convert to clean Markdown.""",

    "batch_enhancement": """You are a PowerPoint to Markdown converter. You receive a batch of PowerPoint slides (max 5 slides) and must clean them up into professional, well-structured markdown.

Your job:
1. Extract and preserve ALL text content from every slide
2. Fix bullet point hierarchies - create proper nested lists with 2-space indentation
3. Identify main titles and format as # headers (only ONE per slide)
4. Identify subtitles or section headers and format as ### headers (not ##)
5. Preserve ALL hyperlinks and formatting (bold, italic, code blocks)
6. Fix broken list structures and ensure numbered lists are properly formatted
7. Ensure tables are properly formatted with | separators
8. Clean up spacing and structure while maintaining logical flow
9. Keep slide markers like <!-- Slide 1 --> for reference
10. If there are diagrams, create them in mermaid code format for .md files
11. Include all visible links, captions, annotations, and footnotes
12. Format technical content and code blocks appropriately

Key Rules:
- Keep ALL original text content - don't miss or skip anything
- Fix bullet nesting based on context and visual hierarchy
- Each slide should have only ONE main # heading
- Use ### for subheadings throughout (never ##)
- Preserve all hyperlinks exactly as provided
- Use proper markdown syntax throughout
- Maintain the original slides' logical structure
- Format tables properly with aligned columns where possible

The input will have slide markers like <!-- Slide 1 --> to separate slides. Keep these markers in your output.

Output clean, readable markdown that maintains the original document's complete content but fixes structure and formatting issues.

Finally - all this output is going to an .md file so you DO NOT NEED to put ```markdown blocks ARE WE CLEAR"""
}


# ==================== Enterprise LLM Client ====================

class EnterpriseLLMClient:
    """Client for connecting to enterprise LLM endpoints."""

    def __init__(self, jwt_token: str, model_url: str):
        """
        Initialise enterprise LLM client.

        Args:
            jwt_token: JWT authentication token
            model_url: Enterprise model endpoint URL
        """
        self.jwt_token = jwt_token
        self.model_url = model_url
        self.headers = {
            "Authorization": f"Bearer {self.jwt_token}",
            "Content-Type": "application/json"
        }
        self.logger = logging.getLogger(__name__)

    def test_connection(self) -> bool:
        """Test connectivity to the enterprise endpoint."""
        try:
            response = requests.head(self.model_url, timeout=10)
            self.logger.info(f"Enterprise endpoint reachable (status: {response.status_code})")
            return True
        except Exception as e:
            self.logger.warning(f"Enterprise endpoint test failed: {e}")
            return False

    def extract_text_from_image(self, image: Image.Image, context: str = "default") -> Optional[str]:
        """
        Extract text from image using enterprise LLM.

        Args:
            image: PIL Image object
            context: Context for prompt selection

        Returns:
            Extracted text or None if failed
        """
        try:
            # Convert image to base64
            buffer = BytesIO()
            image.save(buffer, format='PNG', optimize=True)
            image_b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

            # Get appropriate prompt
            prompt = PROMPTS.get(context, PROMPTS["default"])

            # Prepare payload for enterprise LLM
            payload = {
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": f"Convert this image to Markdown:\n[Image data: {image_b64[:100]}...]"}
                ],
                "max_tokens": 4000,
                "temperature": 0.1
            }

            # Make request
            response = requests.post(
                self.model_url,
                headers=self.headers,
                json=payload,
                timeout=120
            )

            if response.status_code == 200:
                result = response.json()

                # Try different response formats
                if "choices" in result and result["choices"]:
                    return result["choices"][0]["message"]["content"]
                elif "generated_text" in result:
                    return result["generated_text"]
                elif "content" in result:
                    return result["content"]
                else:
                    return str(result)
            else:
                self.logger.error(f"Enterprise LLM error {response.status_code}: {response.text}")
                return None

        except Exception as e:
            self.logger.error(f"Enterprise LLM request failed: {e}")
            return None

    def enhance_markdown_batch(self, markdown_content: str) -> str:
        """
        Enhance a batch of markdown content using enterprise LLM.

        Args:
            markdown_content: Raw markdown content

        Returns:
            Enhanced markdown content
        """
        try:
            payload = {
                "messages": [
                    {"role": "system", "content": PROMPTS["batch_enhancement"]},
                    {"role": "user", "content": markdown_content}
                ],
                "max_tokens": 4000,
                "temperature": 0.1
            }

            response = requests.post(
                self.model_url,
                headers=self.headers,
                json=payload,
                timeout=120
            )

            if response.status_code == 200:
                result = response.json()

                if "choices" in result and result["choices"]:
                    return result["choices"][0]["message"]["content"]
                elif "generated_text" in result:
                    return result["generated_text"]
                elif "content" in result:
                    return result["content"]

            return markdown_content  # Return original on error

        except Exception as e:
            self.logger.error(f"Batch enhancement failed: {e}")
            return markdown_content


# ==================== Main Converter Class ====================

class DocVision:
    """Document to Markdown converter with Enterprise LLM support."""

    def __init__(self, config: Optional[Config] = None):
        """
        Initialise the converter.

        Args:
            config: Configuration object
        """
        # Load environment variables
        load_dotenv()

        # Setup configuration
        self.config = config or self._load_config()

        # Initialise LLM client
        self.llm_client = self._initialise_llm_client()

        # Find LibreOffice for PowerPoint conversion
        self.libreoffice_path = self._find_libreoffice()

        # Setup logging
        logging.basicConfig(level=logging.INFO, format='%(message)s')
        self.logger = logging.getLogger(__name__)

    def _load_config(self) -> Config:
        """Load configuration from files."""
        config = Config()

        # Load enterprise credentials
        if not os.path.exists("JWT_token.txt") or not os.path.exists("model_url.txt"):
            raise ValueError(
                "Enterprise LLM configuration files not found.\n"
                "Required files:\n"
                "  - JWT_token.txt (containing your JWT token)\n"
                "  - model_url.txt (containing the model endpoint URL)"
            )

        with open("JWT_token.txt", "r") as f:
            config.enterprise_jwt_token = f.read().strip()

        with open("model_url.txt", "r") as f:
            config.enterprise_model_url = f.read().strip()

        if not config.enterprise_jwt_token:
            raise ValueError("JWT_token.txt is empty")

        if not config.enterprise_model_url:
            raise ValueError("model_url.txt is empty")

        return config

    def _initialise_llm_client(self) -> EnterpriseLLMClient:
        """Initialise the Enterprise LLM client."""
        self.logger.info("[INFO] Using Enterprise LLM")

        client = EnterpriseLLMClient(
            self.config.enterprise_jwt_token,
            self.config.enterprise_model_url
        )

        # Test connection
        if not client.test_connection():
            self.logger.warning("[WARN] Enterprise endpoint may be unreachable")

        return client

    def convert(self, file_path: Path, output_dir: Optional[Path] = None, enhance: bool = True) -> Path:
        """
        Convert a document to Markdown.

        Args:
            file_path: Path to input document
            output_dir: Output directory (optional)
            enhance: Whether to apply enhancement (default: True)

        Returns:
            Path to generated Markdown file
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
        self.logger.info(f"[PROCESSING] Converting with Enterprise LLM: {file_path.name}")
        self.logger.info(f"   Size: {file_size_mb:.1f}MB")

        # Route to appropriate converter
        suffix = file_path.suffix.lower()

        if suffix == '.pdf':
            markdown = self._convert_pdf(file_path)
        elif suffix in ['.pptx', '.ppt', '.odp']:
            markdown = self._convert_powerpoint(file_path, enhance)
        else:
            raise ValueError(
                f"Unsupported file type: {suffix}\n"
                f"Supported types: .pdf, .pptx, .ppt, .odp"
            )

        # Save output
        output_path.write_text(markdown, encoding='utf-8')
        self.logger.info(f"[SUCCESS] Saved to: {output_path}")

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

                # Resize if needed
                image = self._resize_image(image)

                text = self.llm_client.extract_text_from_image(image, "pdf")
                if text:
                    pages.append(f"## Page {i}\n\n{text}")
                else:
                    pages.append(f"## Page {i}\n\n*[Could not extract text from this page]*")

                # Add pause between pages to avoid rate limits
                if i < len(images):  # Don't pause after the last page
                    self.logger.info(f"   Pausing {self.config.pause_seconds} seconds to avoid rate limits...")
                    time.sleep(self.config.pause_seconds)

            # Combine with metadata
            header = f"# {pdf_path.name}\n\n*Converted from PDF using Enterprise LLM*\n\n"
            return header + "\n\n---\n\n".join(pages)

        except Exception as e:
            raise RuntimeError(f"PDF conversion failed: {e}")

    def _convert_powerpoint(self, ppt_path: Path, enhance: bool = True) -> str:
        """Convert PowerPoint to Markdown with optional enhancement."""
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

                # Process slides with enhancement by default
                if enhance:
                    return self._process_slides_with_enhancement(images, ppt_path.name)
                else:
                    return self._process_slides_standard(images, ppt_path.name)

        except Exception as e:
            raise RuntimeError(f"PowerPoint conversion failed: {e}")

    def _process_slides_standard(self, images: List[Image.Image], filename: str) -> str:
        """Process slides using standard extraction."""
        slides = []

        for i, image in enumerate(images, 1):
            self.logger.info(f"   Processing slide {i}/{len(images)}...")

            # Resize if needed
            image = self._resize_image(image)

            text = self.llm_client.extract_text_from_image(image, "powerpoint")
            if text:
                slides.append(f"<!-- Slide {i} -->\n\n{text}")
            else:
                slides.append(f"<!-- Slide {i} -->\n\n*[Could not extract text from this slide]*")

            # Add pause between slides to avoid rate limits
            if i < len(images):  # Don't pause after the last slide
                self.logger.info(f"   Pausing {self.config.pause_seconds} seconds to avoid rate limits...")
                time.sleep(self.config.pause_seconds)

        # Combine with metadata
        header = f"# {filename}\n\n*Converted from PowerPoint presentation*\n\n"
        return header + "\n\n---\n\n".join(slides)

    def _process_slides_with_enhancement(self, images: List[Image.Image], filename: str) -> str:
        """Process slides with enterprise LLM enhancement in batches."""
        self.logger.info("   Using enhanced batch processing...")

        # First extract all slides
        raw_slides = []
        for i, image in enumerate(images, 1):
            self.logger.info(f"   Extracting slide {i}/{len(images)}...")

            # Resize if needed
            image = self._resize_image(image)

            text = self.llm_client.extract_text_from_image(image, "powerpoint")
            if text:
                raw_slides.append(f"<!-- Slide {i} -->\n\n{text}")
            else:
                raw_slides.append(f"<!-- Slide {i} -->\n\n*[Could not extract text from this slide]*")

            # Add pause between slides to avoid rate limits
            if i < len(images):  # Don't pause after the last slide
                self.logger.info(f"   Pausing {self.config.pause_seconds} seconds to avoid rate limits...")
                time.sleep(self.config.pause_seconds)

        # Process in batches for enhancement
        enhanced_slides = []
        batch_size = self.config.batch_size

        for i in range(0, len(raw_slides), batch_size):
            batch = raw_slides[i:i + batch_size]
            batch_content = "\n\n".join(batch)

            self.logger.info(
                f"   Enhancing batch {i // batch_size + 1}/{(len(raw_slides) + batch_size - 1) // batch_size}...")

            enhanced = self.llm_client.enhance_markdown_batch(batch_content)
            enhanced_slides.append(enhanced)

            # Pause between enhancement batches too
            if i + batch_size < len(raw_slides):
                self.logger.info(f"   Pausing {self.config.pause_seconds} seconds between enhancement batches...")
                time.sleep(self.config.pause_seconds)

        # Combine with metadata
        header = f"# {filename}\n\n*Converted from PowerPoint presentation with enhancement*\n\n"
        return header + "\n\n---\n\n".join(enhanced_slides)

    def _resize_image(self, image: Image.Image) -> Image.Image:
        """Resize image if needed."""
        if max(image.size) > self.config.max_image_dimension:
            ratio = self.config.max_image_dimension / max(image.size)
            new_size = tuple(int(d * ratio) for d in image.size)
            image = image.resize(new_size, Image.Resampling.LANCZOS)

        # Convert RGBA to RGB if needed
        if image.mode == 'RGBA':
            background = Image.new('RGB', image.size, (255, 255, 255))
            background.paste(image, mask=image.split()[3])
            image = background
        elif image.mode not in ('RGB', 'L'):
            image = image.convert('RGB')

        return image

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

    def batch_convert(self, directory: Path, output_dir: Optional[Path] = None, enhance: bool = True) -> List[
        Tuple[Path, Optional[Path]]]:
        """
        Convert all supported documents in a directory.

        Args:
            directory: Input directory
            output_dir: Output directory (optional)
            enhance: Whether to use enhancement (default: True)

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
        self.logger.info(f"Note: {self.config.pause_seconds}-second pause will be added between each image/slide")

        # Convert each file
        results = []
        for file_num, file_path in enumerate(sorted(files), 1):
            try:
                self.logger.info(f"\n[{file_num}/{len(files)}] Processing {file_path.name}")
                output_path = self.convert(file_path, output_dir, enhance)
                results.append((file_path, output_path))

                # Pause between files in batch mode
                if file_num < len(files):
                    self.logger.info(f"[PAUSE] Pausing {self.config.pause_seconds} seconds before next file...")
                    time.sleep(self.config.pause_seconds)

            except Exception as e:
                self.logger.error(f"[ERROR] Failed: {file_path.name} - {e}")
                results.append((file_path, None))

        # Summary
        successful = sum(1 for _, output in results if output)
        self.logger.info(f"\n[SUMMARY] {successful}/{len(files)} converted successfully")

        return results


# ==================== CLI Interface ====================

def main():
    """Command-line interface."""
    parser = argparse.ArgumentParser(
        description='Convert documents to Markdown using Enterprise LLM',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s document.pdf
  %(prog)s presentation.pptx -o output/
  %(prog)s /path/to/documents/ --batch
  %(prog)s document.pptx --no-enhance
  %(prog)s --check

Supported formats:
  - PDF (.pdf)
  - PowerPoint (.pptx, .ppt, .odp)

Configuration:
  Required files in current directory:
  - JWT_token.txt (Enterprise LLM authentication token)
  - model_url.txt (Enterprise LLM endpoint URL)

Requirements:
  - Poppler (for PDF support)
  - LibreOffice (for PowerPoint support)

Note: A 10-second pause is added between processing each image/slide
      to avoid exceeding rate limits.
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
        '--no-enhance',
        action='store_true',
        help='Disable enhancement for PowerPoint files'
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
        converter = DocVision()

        # Process input
        input_path = Path(args.input)
        output_dir = Path(args.output) if args.output else None
        enhance = not args.no_enhance

        if args.batch or input_path.is_dir():
            # Batch conversion
            if not input_path.is_dir():
                print(f"Error: {input_path} is not a directory", file=sys.stderr)
                return 1

            converter.batch_convert(input_path, output_dir, enhance)
        else:
            # Single file conversion
            if not input_path.is_file():
                print(f"Error: {input_path} is not a file", file=sys.stderr)
                return 1

            converter.convert(input_path, output_dir, enhance)

        return 0

    except KeyboardInterrupt:
        print("\n\nCancelled by user", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        return 1


def check_dependencies():
    """Check system dependencies and configuration."""
    print("DocVision Enterprise Dependency Check")
    print("=" * 40)

    # Check Python version
    print(f"\nPython: {sys.version}")
    if sys.version_info < (3, 8):
        print("  [WARN] Python 3.8+ recommended")

    # Check required packages
    print("\nPython packages:")
    packages = {
        'pdf2image': ('PDF to image conversion', True),
        'PIL': ('Image processing', True),
        'dotenv': ('Environment variables', True),
        'requests': ('HTTP requests', True)
    }

    for module, (description, required) in packages.items():
        try:
            if module == 'PIL':
                import PIL
            elif module == 'dotenv':
                import dotenv
            else:
                __import__(module)
            print(f"  [OK] {module:<12} {description}")
        except ImportError:
            symbol = "[FAIL]" if required else "[WARN]"
            print(f"  {symbol} {module:<12} {description}")

    # Check system dependencies
    print("\nSystem dependencies:")

    # Check Poppler
    if shutil.which('pdftoppm'):
        print(f"  [OK] Poppler     PDF support")
    else:
        print(f"  [FAIL] Poppler     PDF support (install poppler-utils)")

    # Check LibreOffice
    try:
        # Create a minimal instance just to check LibreOffice
        temp_converter = DocVision.__new__(DocVision)
        # Manually call _find_libreoffice without full initialization
        import platform

        system = platform.system()
        libreoffice_path = None

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
                libreoffice_path = path
                break

        # Check system PATH if not found
        if not libreoffice_path:
            libreoffice_path = shutil.which("soffice") or shutil.which("libreoffice")

        if libreoffice_path:
            print(f"  [OK] LibreOffice PowerPoint support")
        else:
            print(f"  [WARN] LibreOffice PowerPoint support (optional)")
    except Exception as e:
        print(f"  [WARN] LibreOffice check failed: {e}")

    # Check Enterprise LLM configuration
    print("\nEnterprise LLM Configuration:")

    config_ok = True

    if os.path.exists("JWT_token.txt"):
        with open("JWT_token.txt", "r") as f:
            token = f.read().strip()
        if token:
            masked_token = f"{token[:20]}..." if len(token) > 20 else "***"
            print(f"  [OK] JWT Token: {masked_token}")
        else:
            print(f"  [FAIL] JWT_token.txt exists but is empty")
            config_ok = False
    else:
        print(f"  [FAIL] JWT_token.txt not found")
        config_ok = False

    if os.path.exists("model_url.txt"):
        with open("model_url.txt", "r") as f:
            url = f.read().strip()
        if url:
            print(f"  [OK] Model URL: {url[:50]}...")
        else:
            print(f"  [FAIL] model_url.txt exists but is empty")
            config_ok = False
    else:
        print(f"  [FAIL] model_url.txt not found")
        config_ok = False

    print("\n" + "=" * 40)

    if config_ok:
        print("[OK] Enterprise LLM configuration complete")
    else:
        print("[FAIL] Enterprise LLM configuration incomplete")
        print("\nTo configure:")
        print("  1. Create JWT_token.txt with your authentication token")
        print("  2. Create model_url.txt with your model endpoint URL")

    print("\nRun 'pip install pdf2image pillow python-dotenv requests' to install missing packages")

    return 0


if __name__ == '__main__':
    sys.exit(main())