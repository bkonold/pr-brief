"""Helpers copied verbatim from qodo-ai/pr-agent pr_agent/tools/pr_description.py (MIT).

Pinned to upstream commit 9ed605cc992f18663d2527c35cf990813fba6654; see vendor/README.md.
Only the module-level functions from DIAGRAM_OPENING_FENCE_PATTERN to the end of the file are
copied. The imports and `get_logger` below stand in for the ones the upstream module has.
"""
import logging
import re
from graphlib import TopologicalSorter
from typing import List, Tuple


def get_logger() -> logging.Logger:
    return logging.getLogger("pr_agent")


DIAGRAM_OPENING_FENCE_PATTERN = re.compile(
    r'^[ \t]*(?P<fence>```mermaid)(?![A-Za-z0-9_-])',
    re.MULTILINE,
)
DIAGRAM_CLOSING_FENCE_PATTERN = re.compile(
    r'^[ \t]*(?P<fence>`{3,})(?=[ \t]*\r?$)',
    re.MULTILINE,
)
DIAGRAM_SQUARE_NODE_PATTERN = re.compile(
    r'(?<![\w-])(?P<node_id>[A-Za-z0-9_][A-Za-z0-9_-]*\s*)'
    r'\[(?![\[(\\/])(?P<label>"(?:\\.|[^"\\])*"|[^\[\]\n]*)\]'
)


def _diagram_label_positions(line: str) -> List[bool]:
    """For each position in the line, whether it sits inside an existing label."""
    square_depth = 0
    in_double_quotes = False
    escaped = False
    inside = [False]
    for char in line:
        if char == '"' and not escaped:
            in_double_quotes = not in_double_quotes
        elif not in_double_quotes:
            if char == '[':
                square_depth += 1
            elif char == ']' and square_depth:
                square_depth -= 1

        if char == '\\':
            escaped = not escaped
        else:
            escaped = False

        inside.append(in_double_quotes or square_depth > 0)
    return inside


def sanitize_diagram(diagram_raw: str) -> str:
    """Extract and sanitize a Mermaid diagram."""
    if not isinstance(diagram_raw, str):
        return ''
    diagram = diagram_raw.strip()
    opening_fence = DIAGRAM_OPENING_FENCE_PATTERN.search(diagram)
    if opening_fence is None:
        return ''
    diagram = diagram[opening_fence.start('fence'):]

    closing_fence = DIAGRAM_CLOSING_FENCE_PATTERN.search(diagram, len('```mermaid'))
    if closing_fence is None:
        diagram += '\n```'
    else:
        diagram = diagram[:closing_fence.end('fence')]

    def quote_node_label(match: re.Match) -> str:
        label = match.group('label').strip()
        if len(label) >= 2 and label.startswith('"') and label.endswith('"'):
            label = label[1:-1]
        label = label.replace('`', '').replace('\\"', '#quot;').replace('"', '#quot;')
        return f'{match.group("node_id")}["{label}"]'

    result = []
    for line in diagram.split('\n'):
        inside_label = _diagram_label_positions(line)
        line = DIAGRAM_SQUARE_NODE_PATTERN.sub(
            lambda match, inside_label=inside_label: (
                match.group(0)
                if inside_label[match.start()]
                else quote_node_label(match)
            ),
            line,
        )
        result.append(line)
    return '\n' + '\n'.join(result)


DIAGRAM_HEADER_PATTERN = re.compile(r'^(\s*(?:flowchart|graph)\s+)(?:TB|TD|BT|RL|LR)\b(.*)$')
DIAGRAM_CONNECTOR_PATTERN = re.compile(r'(<?[-=.~]{2,}[->ox]?)')
DIAGRAM_NODE_ID_PATTERN = re.compile(r'[A-Za-z0-9_]+')
DIAGRAM_QUOTED_LABEL_PATTERN = re.compile(r'"[^"]*"')
DIAGRAM_PIPE_LABEL_PATTERN = re.compile(r'\|[^|]*\|')  # pipe-form edge labels: -->|text|
DIAGRAM_SHAPE_PATTERN = re.compile(r'\[[^\[\]]*\]|\([^()]*\)|\{[^{}]*\}')
# A two-character connector opens a middle label (`A -- text --> B`); a longer one is a real link,
# so `A --- B --> C` still reads as a three-node chain.
DIAGRAM_LABEL_OPENERS = ('--', '==', '-.')


def _strip_diagram_labels(line: str) -> str:
    """Remove label text, so that arrows written inside a label are not read as edges."""
    line = DIAGRAM_QUOTED_LABEL_PATTERN.sub('', line)
    line = DIAGRAM_PIPE_LABEL_PATTERN.sub('', line)
    previous = None
    while previous != line:  # nested shapes such as [[...]] need more than one pass
        previous = line
        line = DIAGRAM_SHAPE_PATTERN.sub('', line)
    return line


def _parse_diagram_edges(lines: List[str]) -> List[Tuple[str, str]]:
    """Extract the directed edges of a mermaid flowchart body, tolerating its syntax variants."""
    edges = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith('%%'):  # a comment can still hold arrow-looking text
            continue

        cleaned = _strip_diagram_labels(line)
        # No connector left also means no edge, which is how subgraph/style/classDef/direction
        # statements drop out without needing a keyword list to keep in sync with mermaid.
        if not DIAGRAM_CONNECTOR_PATTERN.search(cleaned):
            continue

        # The capturing split yields chunk, connector, chunk, connector, ... Each chunk holds one
        # or more node ids joined by '&', unless the connector before it opened a middle label.
        parts = DIAGRAM_CONNECTOR_PATTERN.split(cleaned)
        node_groups = []
        for index, chunk in enumerate(parts[::2]):
            if index and parts[index * 2 - 1] in DIAGRAM_LABEL_OPENERS:
                continue  # `A -- text --> B`: this chunk is the edge label, not a node
            node_ids = []
            for token in chunk.split('&'):
                match = DIAGRAM_NODE_ID_PATTERN.search(token)
                if match:
                    node_ids.append(match.group(0))
            if node_ids:
                node_groups.append(node_ids)

        for left, right in zip(node_groups, node_groups[1:], strict=False):
            edges.extend((source, target) for source in left for target in right)
    return edges


def _longest_diagram_chain(edges: List[Tuple[str, str]]) -> int:
    """Length, in nodes, of the longest path through the graph. Raises ValueError on a cycle."""
    predecessors = {}
    for source, target in edges:
        predecessors.setdefault(source, set())
        predecessors.setdefault(target, set()).add(source)

    longest = {}
    for node in TopologicalSorter(predecessors).static_order():  # CycleError is a ValueError
        longest[node] = 1 + max((longest[p] for p in predecessors[node]), default=0)
    return max(longest.values(), default=0)


def apply_diagram_direction(diagram: str, direction: str, threshold: int) -> str:
    """Set the flowchart direction, adapting it to the shape of the graph unless one is pinned.

    Width in an LR flowchart is set by the longest path rather than by the node count, so the
    longest chain is what decides. 'LR' or 'TD' pins the result; any other value is treated as
    'adaptive'. Anything unexpected - no flowchart header, no edges, a cycle, an unusable
    threshold - returns the diagram untouched.
    """
    try:
        lines = diagram.split('\n')
        header = next(((index, match) for index, line in enumerate(lines)
                       if (match := DIAGRAM_HEADER_PATTERN.match(line))), None)
        if header is None:
            return diagram
        header_index, header_match = header

        requested = str(direction).strip().upper()
        if requested in ('LR', 'TD'):
            chosen = requested
        else:
            if requested != 'ADAPTIVE':
                get_logger().warning(f"Unknown pr_diagram_direction '{direction}', using adaptive")
            edges = _parse_diagram_edges(lines[header_index + 1:])
            if not edges:
                return diagram
            chosen = 'LR' if _longest_diagram_chain(edges) <= int(threshold) else 'TD'

        lines[header_index] = f"{header_match.group(1)}{chosen}{header_match.group(2)}"
        return '\n'.join(lines)
    except Exception as e:
        get_logger().debug(f"Failed to adapt the diagram direction: {e}")
        return diagram


def count_chars_without_html(string):
    if '<' not in string:
        return len(string)
    no_html_string = re.sub('<[^>]+>', '', string)
    return len(no_html_string)


def insert_br_after_x_chars(text: str, x=70):
    """
    Insert <br> into a string after a word that increases its length above x characters.
    Use proper HTML tags for code and new lines.
    """

    if not text:
        return ""
    if count_chars_without_html(text) < x:
        return text

    is_list = text.lstrip().startswith(("- ", "* "))

    # replace odd instances of ` with <code> and even instances of ` with </code>
    text = replace_code_tags(text)

    # convert list items to <li> only if the text is identified as a list
    if is_list:
        # To handle lists that start with indentation
        leading_whitespace = text[:len(text) - len(text.lstrip())]
        body = text.lstrip()
        body = "<li>" + body[2:]
        text = leading_whitespace + body

        text = text.replace("\n- ", '<br><li> ').replace("\n - ", '<br><li> ')
        text = text.replace("\n* ", '<br><li> ').replace("\n * ", '<br><li> ')

    # convert new lines to <br>
    text = text.replace("\n", '<br>')

    # split text into lines
    lines = text.split('<br>')
    words = []
    for i, line in enumerate(lines):
        words += line.split(' ')
        if i < len(lines) - 1:
            words[-1] += "<br>"

    new_text = []
    is_inside_code = False
    current_length = 0
    for word in words:
        is_saved_word = False
        if word == "<code>" or word == "</code>" or word == "<li>" or word == "<br>":
            is_saved_word = True

        len_word = count_chars_without_html(word)
        if not is_saved_word and (current_length + len_word > x):
            if is_inside_code:
                new_text.append("</code><br><code>")
            else:
                new_text.append("<br>")
            current_length = 0  # Reset counter
        new_text.append(word + " ")

        if not is_saved_word:
            current_length += len_word + 1  # Add 1 for the space

        if word == "<li>" or word == "<br>":
            current_length = 0

        if "<code>" in word:
            is_inside_code = True
        if "</code>" in word:
            is_inside_code = False

    processed_text = ''.join(new_text).strip()

    if is_list:
        processed_text = f"<ul>{processed_text}</ul>"

    return processed_text


def replace_code_tags(text):
    """
    Replace odd instances of ` with <code> and even instances of ` with </code>
    """
    parts = text.split('`')
    for i in range(1, len(parts), 2):
        parts[i] = '<code>' + parts[i] + '</code>'
    return ''.join(parts)
