# coding=utf-8
"""
Notification text utilities.
"""


def truncate_at_line_boundary(text: str, max_bytes: int) -> str:
    """在行边界处截断，确保不在标题或内容中间断开

    先按字节截断，再回退到最近的换行符位置，保证每一行都完整。

    Args:
        text: 要截断的文本
        max_bytes: 最大字节数

    Returns:
        在最后一个完整行处结束的截断文本
    """
    if len(text.encode("utf-8")) <= max_bytes:
        return text

    truncated = text.encode("utf-8")[:max_bytes]
    rough_cut = ""
    for i in range(min(4, len(truncated))):
        try:
            rough_cut = truncated[: len(truncated) - i].decode("utf-8")
            break
        except UnicodeDecodeError:
            continue
    last_newline = rough_cut.rfind("\n")
    if last_newline > 0:
        return rough_cut[:last_newline]
    return rough_cut
