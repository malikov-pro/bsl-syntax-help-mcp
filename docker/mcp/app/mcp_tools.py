from __future__ import annotations

from fastmcp import FastMCP

from app.search import SearchError, lookup_document, search_documents

mcp = FastMCP("bsl-syntax-help")


def _format_error(exc: SearchError) -> str:
    message = str(exc)
    if exc.loaded_layers:
        message += f" Loaded layers: {', '.join(exc.loaded_layers)}."
    return message


@mcp.tool
def docinfo(name: str, platform_version: str, scope: str = "syntax") -> str:
    """Return one 1C platform syntax-help article by name.

    Args:
        name: Russian or English full name, or an alias (for example Массив.Найти).
        platform_version: Required platform version such as 8.3.23 or 8.3.27.
        scope: Always syntax in v1.
    """
    try:
        return lookup_document(name, platform_version, scope)
    except SearchError as exc:
        return _format_error(exc)


@mcp.tool
def docsearch(query: str, platform_version: str, scope: str = "syntax") -> str:
    """Search 1C platform syntax help. Do not mention 1C in the query.

    If you know the method or type name, pass only that name. Otherwise describe
    the needed behavior in Russian.

    Args:
        query: Search phrase or exact name.
        platform_version: Required platform version such as 8.3.23 or 8.3.27.
        scope: Always syntax in v1.
    """
    try:
        return search_documents(query, platform_version, scope)
    except SearchError as exc:
        return _format_error(exc)


def make_mcp_app():
    try:
        return mcp.http_app(path="/", transport="streamable-http", stateless_http=True)
    except TypeError:
        return mcp.http_app(path="/")
