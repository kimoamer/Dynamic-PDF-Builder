import re

def extract_math(text: str) -> str:
    """Finds display math $$equation$$ and inline math $equation$ and processes them safely."""
    # This is a stub for pre-processing math blocks before markdown-it execution.
    # We could convert $$ math $$ into a fenced block ```math
    def replace_display(m):
        anchor = f" {{#{m.group(2)}}}" if m.group(2) else ""      # $$ ... $$ {#eq-id} numbers the equation
        return f"```math{anchor}\n{m.group(1)}\n```"

    # Replace $$ equations with markdown fenced blocks
    text = re.sub(r'\$\$(.*?)\$\$(?:[ \t]*\{#([A-Za-z][\w:.-]*)\})?', replace_display, text, flags=re.DOTALL)
    return text
    
def preprocess_markdown(text: str) -> str:
    text = extract_math(text)
    return text
