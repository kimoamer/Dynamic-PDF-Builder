from contextlib import contextmanager
from .builder import DocumentBuilder

@contextmanager
def stream(output_path: str, theme: str = "claude"):
    """
    Experimental stream API:
    with stream("out.pdf", theme="claude") as s:
        s.write("# Hello")
    """
    builder = DocumentBuilder(theme=theme)
    
    class StreamProxy:
        def __init__(self, b):
            self.builder = b
            self.buffer = ""
            
        def write(self, chunk: str):
            self.buffer += chunk
            
        def close(self):
            # perform final render
            from .markdown.preprocessors import preprocess_markdown
            from .markdown.parser import markdown_to_blocks
            
            clean_text = preprocess_markdown(self.buffer)
            blocks = markdown_to_blocks(clean_text)
            self.builder._blocks.extend(blocks)
            self.builder.render(output_path)

    proxy = StreamProxy(builder)
    try:
        yield proxy
    finally:
        proxy.close()
