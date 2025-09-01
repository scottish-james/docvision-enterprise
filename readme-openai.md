# DocVision - AI-Powered Document to Markdown Converter

[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4V-orange)](https://openai.com/)

## Overview

DocVision is an OCR-based document converter that transforms PDFs and PowerPoint presentations into clean, structured Markdown using OpenAI's Vision API. It solves the critical problem of extracting text from visual documents whilst maintaining correct reading order and structure.

**Key Features:**
- 📊 94% accuracy on real-world documents
- ⚡ 10 seconds per page/slide processing time
- 🔗 Preserves hyperlinks and formatting
- ✅ Maintains correct reading order (critical for compliance)

## How It Works

### High-Level Architecture

```mermaid
flowchart TB
    subgraph Input ["📁 Input Documents"]
        PDF[PDF Files]
        PPT[PowerPoint Files<br/>PPTX/PPT/ODP]
    end
    
    subgraph Processing ["⚙️ Processing Pipeline"]
        LibreOffice[LibreOffice<br/>Converter]
        Images[High-Res Images<br/>200 DPI]
        Vision[OpenAI GPT-4<br/>Vision API]
    end
    
    subgraph Output ["📄 Output"]
        MD[Markdown Files<br/>with Structure]
    end
    
    PDF --> Images
    PPT --> LibreOffice
    LibreOffice --> PDF
    Images --> Vision
    Vision --> MD
    
    style Input fill:#e1f5fe
    style Processing fill:#fff3e0
    style Output fill:#e8f5e9
```

### Detailed Processing Flow

```mermaid
flowchart TD
    Start([Start]) --> CheckType{Document Type?}
    
    CheckType -->|PDF| PDFPath[Convert PDF to Images<br/>using pdf2image]
    CheckType -->|PowerPoint| PPTPath[Convert to PDF<br/>using LibreOffice]
    
    PPTPath --> PDFPath
    PDFPath --> Loop[Process Each Page/Slide]
    
    Loop --> Resize[Resize Image if Needed<br/>Max 2048px]
    Resize --> Convert[Convert to RGB/PNG]
    Convert --> Base64[Encode as Base64]
    Base64 --> API[Send to OpenAI Vision API<br/>with Custom Prompt]
    
    API --> Extract[Extract Markdown Text]
    Extract --> More{More Pages?}
    
    More -->|Yes| Loop
    More -->|No| Combine[Combine All Pages<br/>with Separators]
    
    Combine --> Save[Save as .md File]
    Save --> End([End])
    
    style Start fill:#e8f5e9
    style End fill:#e8f5e9
    style API fill:#fff3e0
```

### API Interaction Flow

```mermaid
sequenceDiagram
    participant User
    participant DocVision
    participant LibreOffice
    participant OpenAI
    participant FileSystem
    
    User->>DocVision: Convert document.pptx
    DocVision->>LibreOffice: Convert to PDF
    LibreOffice-->>DocVision: Return PDF
    
    loop For Each Page
        DocVision->>DocVision: Convert page to image
        DocVision->>DocVision: Resize & encode image
        DocVision->>OpenAI: Send image + prompt
        OpenAI-->>DocVision: Return Markdown text
    end
    
    DocVision->>FileSystem: Save combined Markdown
    DocVision-->>User: Return output path
```

### Error Handling Strategy

```mermaid
flowchart LR
    subgraph Errors ["Error Types"]
        E1[Missing Dependencies]
        E2[API Failures]
        E3[File Format Issues]
        E4[Rate Limits]
    end
    
    subgraph Handling ["Handling Strategy"]
        H1[Check & Report]
        H2[Retry with Backoff]
        H3[Fallback to Basic]
        H4[Queue & Wait]
    end
    
    E1 --> H1
    E2 --> H2
    E3 --> H3
    E4 --> H4
    
    style Errors fill:#ffebee
    style Handling fill:#e8f5e9
```

## Installation

### Prerequisites

- Python 3.8 or higher
- OpenAI API key
- Poppler (for PDF support)
- LibreOffice (for PowerPoint support - optional)

### System Dependencies Installation

```mermaid
flowchart TD
    OS{Operating System?}
    
    OS -->|macOS| Mac[brew install poppler<br/>brew install --cask libreoffice]
    OS -->|Linux| Linux[sudo apt-get install poppler-utils<br/>sudo apt-get install libreoffice]
    OS -->|Windows| Win[Download Poppler for Windows<br/>Download LibreOffice installer]
    
    Mac --> Python
    Linux --> Python
    Win --> Python
    
    Python[pip install -r requirements.txt]
    Python --> Config[Create .env file<br/>Add OPENAI_API_KEY]
    Config --> Ready[✅ Ready to Use]
    
    style Ready fill:#e8f5e9
```

### Quick Start

1. **Clone the repository:**
```bash
git clone https://gitlab.com/your-org/docvision.git
cd docvision
```

2. **Install Python dependencies:**
```bash
pip install -r requirements.txt
```

3. **Configure OpenAI API key:**

Create a `.env` file in the project root:
```env
OPENAI_API_KEY=your_api_key_here
OPENAI_MODEL=gpt-4o
LOG_LEVEL=INFO
DPI=200
MAX_WORKERS=1
```

4. **Check installation:**
```bash
python docvision.py --check
```

## Usage

### Command Line Interface

**Convert a single document:**
```bash
python docvision.py document.pdf
python docvision.py presentation.pptx
```

**Batch convert a directory:**
```bash
python docvision.py /path/to/documents/ --batch
```

**Specify output directory:**
```bash
python docvision.py document.pdf -o output/
```

### Python API

```python
from docvision import DocVision

# Initialise converter
converter = DocVision(api_key="your_api_key")

# Convert single file
output_path = converter.convert("presentation.pptx")

# Batch convert directory
results = converter.batch_convert("/path/to/documents/")
```

## Understanding the Code Structure

```mermaid
classDiagram
    class DocVision {
        +config: Config
        +client: OpenAI
        +logger: Logger
        +convert(file_path, output_dir)
        +batch_convert(directory, output_dir)
        -_convert_pdf(pdf_path)
        -_convert_powerpoint(ppt_path)
        -_extract_text_from_image(image, context)
        -_find_libreoffice()
    }
    
    class Config {
        +openai_api_key: str
        +model: str
        +dpi: int
        +max_image_dimension: int
        +temperature: float
        +max_tokens: int
    }
    
    class ImageProcessor {
        +resize_image()
        +convert_to_rgb()
        +encode_base64()
    }
    
    class PromptManager {
        +get_prompt(context)
        +pdf_prompt: str
        +powerpoint_prompt: str
    }
    
    DocVision --> Config
    DocVision --> ImageProcessor
    DocVision --> PromptManager
```

## Key Configuration Options

| Parameter | Default | Description |
|-----------|---------|-------------|
| `OPENAI_MODEL` | gpt-4o | OpenAI model to use |
| `DPI` | 200 | Image resolution for conversion |
| `MAX_IMAGE_DIMENSION` | 2048 | Maximum image size (pixels) |
| `TEMPERATURE` | 0.1 | AI creativity (0=deterministic) |
| `MAX_TOKENS` | 4000 | Maximum response length |

## Performance Characteristics

```mermaid
graph LR
    subgraph InputFactors[Input Factors]
        A[Document Size]
        B[Page Count]
        C[Content Complexity]
    end
    
    subgraph ProcessingTime[Processing Time]
        D[~10 sec/page]
        E[API Calls]
        F[Image Processing]
    end
    
    subgraph OutputQuality[Output Quality]
        G[94% Accuracy]
        H[Structure Preserved]
        I[Links Maintained]
    end
    
    A --> D
    B --> E
    C --> F
    D --> G
    E --> H
    F --> I
    
    %% Define classes
    classDef input fill:#e1f5fe,stroke:#0277bd,stroke-width:2px;
    classDef processing fill:#fff3e0,stroke:#ef6c00,stroke-width:2px;
    classDef output fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px;

    %% Apply classes to subgraphs
    class InputFactors input;
    class ProcessingTime processing;
    class OutputQuality output;
```

## Common Use Cases

- **Knowledge Base Migration**: Convert PowerPoint training materials to searchable Markdown
- **Documentation Extraction**: Extract technical specs from PDF manuals
- **AI Training Data**: Prepare documents for RAG (Retrieval-Augmented Generation) systems
- **Compliance Documentation**: Ensure accurate extraction for regulated content
- **Content Management**: Convert visual presentations to text-based systems

## Troubleshooting

### Dependency Check Workflow

```mermaid
flowchart TD
    Start[Run: python docvision.py --check]
    Start --> Check{All Green?}
    
    Check -->|No| Missing{What's Missing?}
    Check -->|Yes| Ready[Ready to Use!]
    
    Missing -->|Python Package| PIP[pip install -r requirements.txt]
    Missing -->|Poppler| Pop[Install Poppler for your OS]
    Missing -->|LibreOffice| Libre[Install LibreOffice<br/>Note: Optional for PDF-only]
    Missing -->|API Key| Key[Add OPENAI_API_KEY to .env]
    
    PIP --> Recheck
    Pop --> Recheck
    Libre --> Recheck
    Key --> Recheck
    
    Recheck[Run --check again]
    Recheck --> Check
    
    style Ready fill:#e8f5e9
    style Start fill:#e1f5fe
```

## Limitations

- **Cost**: Uses OpenAI API (~$0.01-0.02 per page)
- **Internet Required**: Needs connection to OpenAI
- **Complex Layouts**: Best with standard document layouts
- **File Size**: Maximum 100MB per document

## Contributing

Contributions welcome! Areas for improvement:
- Support for additional document formats
- Local vision models for sensitive documents
- Improved table extraction
- Web interface for non-technical users

## License

MIT License - See [LICENSE](LICENSE) for details

---

*Built to bridge the gap between visual documents and AI-ready content.*